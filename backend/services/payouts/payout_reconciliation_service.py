"""
READ-ONLY reconciliation of payout attempts, payouts and the ledger, and,
when a provider settlement report is supplied, of provider transfers
against local attempts. Writes nothing and never marks anything failed.
"""

from collections import Counter, defaultdict
from datetime import timedelta

from django.utils import timezone

from finance.models import (
    LedgerTransaction,
    Payout,
    PayoutAttempt,
    PayoutAttemptState,
    PayoutStatus,
    TransactionType,
)
from services.payouts import provider as contract
from services.payouts.payout_attempt_service import ATTEMPT_PAYOUT_STATUS
from services.payouts.payout_resolution_service import STALE_PREPARED_AFTER


# Assumption: replace with the selected provider's documented settlement
# window before any live use.
SUBMITTED_OVERDUE_AFTER = timedelta(days=3)

CRITICAL = "critical"
REVIEW = "review"
INFO = "info"


class PayoutReconciliationService:

    @staticmethod
    def report(*, circle=None, provider_records=None, provider_name=None, now=None):
        """
        Returns a list of findings ({"kind", "severity", ...}, values as
        strings). provider_records: an iterable of
        services.payouts.provider.ProviderTransferRecord from ONE
        provider's settlement report covering every transfer up to now
        (provider_name names it; inferred from the records if omitted),
        or None when no report is available.
        """
        now = now or timezone.now()
        findings = []

        def add(kind, severity, **fields):
            findings.append({
                "kind": kind,
                "severity": severity,
                **{k: ("" if v is None else str(v)) for k, v in fields.items()},
            })

        payouts = Payout.objects.all()
        attempts = PayoutAttempt.objects.select_related("payout")
        ledger = LedgerTransaction.objects.filter(
            transaction_type__in=[TransactionType.PAYOUT, TransactionType.PAYOUT_RETURN],
        )
        if circle is not None:
            payouts = payouts.filter(circle=circle)
            attempts = attempts.filter(payout__circle=circle)
            ledger = ledger.filter(circle=circle)

        by_payout = defaultdict(list)
        for attempt in attempts.order_by("payout_id", "attempt_number"):
            by_payout[attempt.payout_id].append(attempt)

        rows = defaultdict(lambda: defaultdict(list))
        for row in ledger:
            rows[(row.metadata or {}).get("payout_id")][row.transaction_type].append(row)

        for payout in payouts.exclude(
            status__in=[PayoutStatus.PENDING, PayoutStatus.CANCELLED, PayoutStatus.APPROVED],
        ):
            history = by_payout.get(payout.pk, [])
            if not history:
                # Executed before Sprint 33 (no attempt record exists).
                add("legacy_payout_without_attempt", INFO, payout_id=payout.pk,
                    circle_id=payout.circle_id, status=payout.status)
                continue

            latest = history[-1]
            expected = ATTEMPT_PAYOUT_STATUS[PayoutAttemptState(latest.state)]
            if payout.status != expected:
                add("payout_attempt_status_mismatch", CRITICAL, payout_id=payout.pk,
                    payout_status=payout.status, attempt_id=latest.pk,
                    attempt_state=latest.state)

            payout_rows = rows[str(payout.pk)][TransactionType.PAYOUT]
            return_rows = rows[str(payout.pk)][TransactionType.PAYOUT_RETURN]

            if latest.state in (PayoutAttemptState.SUCCEEDED, PayoutAttemptState.RETURNED):
                if len(payout_rows) != 1 or payout_rows[0].payment_reference != latest.provider_reference:
                    add("settled_attempt_ledger_mismatch", CRITICAL, payout_id=payout.pk,
                        attempt_id=latest.pk, provider_reference=latest.provider_reference,
                        payout_rows=len(payout_rows))
            elif payout_rows:
                add("ledger_payout_without_settled_attempt", CRITICAL, payout_id=payout.pk,
                    attempt_id=latest.pk, attempt_state=latest.state)

            if latest.state == PayoutAttemptState.RETURNED and len(return_rows) != 1:
                add("returned_without_compensation", CRITICAL, payout_id=payout.pk,
                    attempt_id=latest.pk, return_rows=len(return_rows))
            elif latest.state != PayoutAttemptState.RETURNED and return_rows:
                add("compensation_without_return", CRITICAL, payout_id=payout.pk,
                    attempt_id=latest.pk)

            age = now - latest.created_at
            if latest.state == PayoutAttemptState.UNKNOWN:
                add("attempt_outcome_unknown", CRITICAL, payout_id=payout.pk,
                    attempt_id=latest.pk, provider=latest.provider,
                    idempotency_key=latest.idempotency_key,
                    error_class=latest.error_class, age=age,
                    action="Confirm with the provider; do not execute again.")
            elif latest.state == PayoutAttemptState.PREPARED and age >= STALE_PREPARED_AFTER:
                add("attempt_prepared_stale", CRITICAL, payout_id=payout.pk,
                    attempt_id=latest.pk, provider=latest.provider,
                    idempotency_key=latest.idempotency_key, age=age,
                    action="May have been sent; resolve before anything else.")
            elif latest.state == PayoutAttemptState.SUBMITTED and age >= SUBMITTED_OVERDUE_AFTER:
                add("attempt_submitted_overdue", REVIEW, payout_id=payout.pk,
                    attempt_id=latest.pk, provider_reference=latest.provider_reference,
                    age=age)

        if provider_records is None:
            return findings

        records = list(provider_records)
        provider_names = (
            {provider_name} if provider_name
            else {record.provider for record in records}
        )
        known = {
            (a.provider, a.provider_reference): a
            for history in by_payout.values()
            for a in history
            if a.provider_reference
        }
        seen = Counter()

        for record in records:
            seen[(record.provider, record.provider_reference)] += 1
            attempt = known.get((record.provider, record.provider_reference))
            if attempt is None:
                add("provider_transfer_unrecorded", CRITICAL, provider=record.provider,
                    provider_reference=record.provider_reference, amount=record.amount,
                    provider_status=record.status)
                continue
            if record.amount is not None and record.amount != attempt.payout.amount:
                add("provider_amount_mismatch", CRITICAL, attempt_id=attempt.pk,
                    provider_reference=record.provider_reference,
                    provider_amount=record.amount, payout_amount=attempt.payout.amount)
            expected = {
                contract.SETTLED: PayoutAttemptState.SUCCEEDED,
                contract.REJECTED: PayoutAttemptState.FAILED,
                contract.RETURNED: PayoutAttemptState.RETURNED,
            }.get(record.status)
            if expected is not None and attempt.state != expected:
                add("provider_status_differs", CRITICAL, attempt_id=attempt.pk, provider_reference=record.provider_reference,
                    provider_status=record.status, attempt_state=attempt.state)

        for key, count in seen.items():
            if count > 1:
                add("provider_transfer_duplicated", CRITICAL, provider=key[0],
                    provider_reference=key[1], count=count)

        for (provider, reference), attempt in known.items():
            if (
                provider in provider_names
                and attempt.state == PayoutAttemptState.SUCCEEDED
                and (provider, reference) not in seen
            ):
                add("settled_attempt_missing_at_provider", CRITICAL,
                    attempt_id=attempt.pk, provider_reference=reference)

        return findings
