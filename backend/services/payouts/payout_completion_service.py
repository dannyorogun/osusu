from django.conf import settings
from django.db import transaction
from django.utils import timezone

from finance.models import (
    Payout,
    PayoutAttemptState,
    PayoutAttemptTransitionError,
    PayoutStatus,
    TransactionType,
)

from services.finance.ledger_service import (
    LedgerService,
)

from services.payouts.mock_payout_provider import REFERENCE_PREFIX
from services.payouts.payout_attempt_service import (
    check_reference,
    evidence_target,
    move,
)


class PayoutCompletionService:

    @staticmethod
    @transaction.atomic
    def complete(
        *,
        payout,
        provider_reference,
        provider_status="",
        evidence_reference="",
        attempt=None,
    ):
        """
        Record AUTHORITATIVE settlement of a payout's live attempt: the
        attempt becomes SUCCEEDED, the payout PAID, and exactly one PAYOUT
        ledger row is appended, in one transaction under the payout lock.

        Callers must hold provider evidence of settlement (a send() result
        from a provider that confirms settlement synchronously, a status
        lookup, or a verified event); PayoutAttemptService.record is the
        normal entry point.

        Exactly once: the payout lock serialises completions; a repeat
        with the same reference returns the PAID payout; the ledger is
        de-duplicated by payment_reference and by a database constraint
        allowing one PAYOUT row per payout.
        """

        payout = (
            Payout.objects
            .select_for_update()
            .select_related(
                "circle",
                "member",
            )
            .get(pk=payout.pk)
        )

        if not provider_reference:
            raise ValueError("Settlement requires the provider's reference.")

        # Defence in depth: a mock confirmation never completes a payout
        # outside development, whoever calls this.
        if (
            str(provider_reference).startswith(REFERENCE_PREFIX)
            and getattr(settings, "OSUSU_PAYOUT_MOCK_ALLOWED", False) is not True
        ):
            raise ValueError(
                "A mock payout confirmation cannot complete a payout."
            )

        attempt = evidence_target(payout, attempt)

        if payout.status in (PayoutStatus.PAID, PayoutStatus.RETURNED):
            # Duplicate success evidence: nothing to do, unless it names a
            # different transfer (reconciliation, never a second row).
            if attempt is not None:
                check_reference(attempt, provider_reference)
            return payout

        if payout.status != PayoutStatus.PROCESSING or attempt is None or not attempt.is_live:
            raise ValueError(
                "Only a payout with a live attempt can be completed."
            )

        check_reference(attempt, provider_reference)

        if not attempt.can_transition_to(PayoutAttemptState.SUCCEEDED):
            raise PayoutAttemptTransitionError(
                f"Payout attempt cannot move from {attempt.state} to succeeded."
            )

        row = LedgerService.record_transaction(
            circle=payout.circle,
            member=payout.member,
            transaction_type=TransactionType.PAYOUT,
            # Ledger amounts are positive magnitudes; the type gives the
            # direction (TreasuryEngine subtracts PAYOUT and REFUND). A
            # negative amount here would increase the treasury balance.
            amount=payout.amount,
            period_number=payout.payout_window,
            reference=f"PAYOUT-{payout.payout_window}",
            payment_reference=provider_reference,
            metadata={
                "payout_id": str(payout.id),
            },
        )

        # LedgerService returns an existing row for a known reference: it
        # must be this payout's, or the reference belongs to something else.
        if (
            row.transaction_type != TransactionType.PAYOUT
            or row.metadata.get("payout_id") != str(payout.id)
        ):
            raise ValueError(
                "This provider reference is already recorded for a different "
                "ledger entry."
            )

        move(
            attempt,
            payout,
            PayoutAttemptState.SUCCEEDED,
            provider_reference=provider_reference,
            provider_status=provider_status,
            evidence_reference=evidence_reference,
        )

        payout.paid_at = timezone.now()
        payout.save(update_fields=["paid_at"])

        return payout
