from django.db import transaction

from finance.models import (
    LedgerTransaction,
    Payout,
    PayoutAttemptState,
    PayoutStatus,
    TransactionType,
)
from services.finance.ledger_service import LedgerService
from services.payouts.payout_attempt_service import (
    check_reference,
    evidence_target,
    move,
)


def return_reference(attempt):
    return f"payout-return:{attempt.provider}:{attempt.provider_reference}"


class PayoutReturnService:

    @staticmethod
    @transaction.atomic
    def record_return(*, payout, provider_reference, evidence_reference="", attempt=None):
        """
        Record AUTHORITATIVE provider evidence that a settled payout was
        returned or reversed: the attempt becomes RETURNED, the payout
        RETURNED, and one compensating incoming PAYOUT_RETURN row is
        appended. The original PAYOUT row is never edited.

        Assumption (documented in docs/payout-uncertain-outcomes.md): a
        return is of the full payout amount. A partial return is not
        modelled and must go through a reviewed ledger correction.
        Whether the member is paid again is a new governance decision;
        nothing is retried.

        Idempotent: a repeated return changes nothing.
        """
        payout = (
            Payout.objects
            .select_for_update()
            .select_related("circle", "member")
            .get(pk=payout.pk)
        )
        attempt = evidence_target(payout, attempt)

        if attempt is None:
            raise ValueError("This payout has no provider attempt to return.")

        check_reference(attempt, provider_reference)

        if payout.status == PayoutStatus.RETURNED:
            return payout

        if payout.status != PayoutStatus.PAID or attempt.state != PayoutAttemptState.SUCCEEDED:
            raise ValueError("Only a settled payout can be returned.")

        original = LedgerTransaction.objects.get(
            transaction_type=TransactionType.PAYOUT,
            metadata__payout_id=str(payout.id),
        )

        LedgerService.record_transaction(
            circle=payout.circle,
            member=payout.member,
            transaction_type=TransactionType.PAYOUT_RETURN,
            amount=original.amount,
            period_number=payout.payout_window,
            reference=f"PAYOUT-RETURN-{payout.payout_window}",
            payment_reference=return_reference(attempt),
            metadata={
                "payout_id": str(payout.id),
                "compensates_transaction_id": str(original.id),
                "evidence_reference": evidence_reference or None,
            },
        )

        move(
            attempt,
            payout,
            PayoutAttemptState.RETURNED,
            evidence_reference=evidence_reference,
        )

        return payout
