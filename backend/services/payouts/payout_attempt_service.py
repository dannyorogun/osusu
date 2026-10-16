"""
The payout-attempt state machine (finance.models.PayoutAttemptState).

Every attempt state change goes through here, together with the payout's
status and an audit entry, in one transaction:

    attempt PREPARED / SUBMITTED / UNKNOWN -> payout PROCESSING
    attempt SUCCEEDED                      -> payout PAID     (+1 PAYOUT row)
    attempt FAILED                         -> payout FAILED
    attempt RETURNED                       -> payout RETURNED (+1 PAYOUT_RETURN row)

Lock order everywhere: the Payout row, then the attempt row.

Evidence is applied idempotently: repeating it, or receiving it out of
order (an "accepted" after a settlement), changes nothing. Evidence that
contradicts a definitive state (a rejection after a settlement, a second
provider reference) raises PayoutAttemptTransitionError and changes
nothing: it needs reconciliation, never a silent overwrite.
"""

import hashlib

from django.db import transaction
from django.utils import timezone

from finance.models import (
    Payout,
    PayoutAttempt,
    PayoutAttemptState,
    PayoutAttemptTransitionError,
    PayoutStatus,
)
from services.audit.audit_service import AuditService
from services.payouts import provider as contract


CURRENCY = "GBP"

# Executing a payout in these statuses creates a new attempt.
EXECUTABLE_STATUSES = (
    PayoutStatus.APPROVED,
    PayoutStatus.FAILED,
)

ATTEMPT_PAYOUT_STATUS = {
    PayoutAttemptState.PREPARED: PayoutStatus.PROCESSING,
    PayoutAttemptState.SUBMITTED: PayoutStatus.PROCESSING,
    PayoutAttemptState.UNKNOWN: PayoutStatus.PROCESSING,
    PayoutAttemptState.SUCCEEDED: PayoutStatus.PAID,
    PayoutAttemptState.FAILED: PayoutStatus.FAILED,
    PayoutAttemptState.RETURNED: PayoutStatus.RETURNED,
}

# State reached by an outcome, and the states in which that outcome is
# already reflected (applied again = no-op).
OUTCOME_TARGET = {
    contract.ACCEPTED: PayoutAttemptState.SUBMITTED,
    contract.UNKNOWN: PayoutAttemptState.UNKNOWN,
    contract.REJECTED: PayoutAttemptState.FAILED,
    contract.NOT_SENT: PayoutAttemptState.FAILED,
}

ALREADY_REFLECTED = {
    contract.ACCEPTED: {PayoutAttemptState.SUBMITTED, PayoutAttemptState.SUCCEEDED,
                        PayoutAttemptState.RETURNED},
    contract.UNKNOWN: {PayoutAttemptState.UNKNOWN, PayoutAttemptState.SUBMITTED,
                       PayoutAttemptState.SUCCEEDED, PayoutAttemptState.FAILED,
                       PayoutAttemptState.RETURNED},
    contract.REJECTED: {PayoutAttemptState.FAILED},
    contract.NOT_SENT: {PayoutAttemptState.FAILED},
    contract.SETTLED: {PayoutAttemptState.SUCCEEDED, PayoutAttemptState.RETURNED},
    contract.RETURNED: {PayoutAttemptState.RETURNED},
}

AUDIT_ACTIONS = {
    PayoutAttemptState.PREPARED: "PAYOUT_ATTEMPT_PREPARED",
    PayoutAttemptState.SUBMITTED: "PAYOUT_ATTEMPT_SUBMITTED",
    PayoutAttemptState.UNKNOWN: "PAYOUT_OUTCOME_UNKNOWN",
    PayoutAttemptState.FAILED: "PAYOUT_EXECUTION_FAILED",
    PayoutAttemptState.SUCCEEDED: "PAYOUT_COMPLETED",
    PayoutAttemptState.RETURNED: "PAYOUT_RETURNED",
}


def idempotency_key(payout, attempt_number):
    """
    Stable per attempt; never reused for a different attempt. A new
    attempt exists only after the previous one was confirmed failed, so a
    new key can never duplicate a transfer that might have happened.
    """
    return f"osusu-payout-{payout.id}-{attempt_number}"


def request_hash(payout):
    raw = f"{payout.id}|{payout.member_id}|{payout.amount}|{CURRENCY}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def latest_attempt(payout):
    return payout.attempts.order_by("-attempt_number").first()


def evidence_target(payout, attempt):
    """
    The attempt that settlement/return evidence applies to: `attempt` if
    given (it must be the payout's latest), else the latest. Evidence about
    an older (failed) attempt never touches a newer one.
    """
    latest = latest_attempt(payout)
    if attempt is None:
        return latest
    if latest is None or attempt.pk != latest.pk:
        raise PayoutAttemptTransitionError(
            "Evidence names a superseded payout attempt; reconcile before "
            "recording anything."
        )
    return latest


def audit(attempt, payout, *, previous, reason=""):
    AuditService.record(
        action=AUDIT_ACTIONS[attempt.state],
        entity_type="Payout",
        entity_id=payout.id,
        user=payout.member,
        metadata={
            "window": payout.payout_window,
            "attempt_id": str(attempt.id),
            "attempt_number": attempt.attempt_number,
            "from_state": previous,
            "to_state": attempt.state,
            "provider": attempt.provider,
            "provider_reference": attempt.provider_reference or None,
            "provider_status": attempt.provider_status or None,
            "error_class": attempt.error_class or None,
            "evidence_reference": attempt.evidence_reference or None,
            "reason": reason or None,
        },
    )


def lock(attempt_or_id):
    """Lock the attempt's payout, then the attempt. Inside a transaction."""
    attempt_id = getattr(attempt_or_id, "pk", attempt_or_id)
    payout_id = PayoutAttempt.objects.values_list("payout_id", flat=True).get(pk=attempt_id)
    payout = (
        Payout.objects
        .select_for_update()
        .select_related("circle", "member")
        .get(pk=payout_id)
    )
    attempt = PayoutAttempt.objects.select_for_update().get(pk=attempt_id)
    return payout, attempt


def move(attempt, payout, state, *, reason="", **fields):
    """Apply one permitted transition and the payout status it implies."""
    previous = attempt.state
    attempt.transition_to(state)
    now = timezone.now()
    for name, value in fields.items():
        if value:
            setattr(attempt, name, value)
    if state == PayoutAttemptState.SUBMITTED:
        attempt.submitted_at = attempt.submitted_at or now
    if state in (PayoutAttemptState.SUCCEEDED, PayoutAttemptState.FAILED):
        attempt.resolved_at = now
    if state == PayoutAttemptState.RETURNED:
        attempt.returned_at = now
    attempt.save()

    payout.status = ATTEMPT_PAYOUT_STATUS[state]
    payout.save(update_fields=["status"])

    audit(attempt, payout, previous=previous, reason=reason)
    return attempt


def check_reference(attempt, reference):
    if reference and attempt.provider_reference and reference != attempt.provider_reference:
        raise PayoutAttemptTransitionError(
            "Provider evidence names a different provider reference than "
            "this attempt; reconcile before recording anything."
        )


class PayoutAttemptService:

    @staticmethod
    def prepare(payout, *, provider_name):
        """
        Persist a PREPARED attempt and move the payout to PROCESSING. The
        caller holds the payout row lock inside a transaction that commits
        BEFORE the provider is called. The partial unique constraint
        (one non-failed attempt per payout) backs the lock.
        """
        if payout.status not in EXECUTABLE_STATUSES:
            raise PayoutAttemptTransitionError(
                "Only approved or confirmed-failed payouts can be attempted."
            )

        previous = latest_attempt(payout)
        if previous is not None and previous.state != PayoutAttemptState.FAILED:
            raise PayoutAttemptTransitionError(
                "This payout has an unresolved or successful attempt."
            )

        number = (previous.attempt_number if previous else 0) + 1

        attempt = PayoutAttempt.objects.create(
            payout=payout,
            attempt_number=number,
            idempotency_key=idempotency_key(payout, number),
            request_hash=request_hash(payout),
            state=PayoutAttemptState.PREPARED,
            provider=provider_name[:30],
        )

        payout.status = PayoutStatus.PROCESSING
        payout.save(update_fields=["status"])

        audit(attempt, payout, previous=None)
        return attempt

    @staticmethod
    @transaction.atomic
    def record(attempt, classified, *, evidence_reference="", reason=""):
        """
        Apply a classified outcome (services.payouts.provider.Classified)
        from a send() response, status lookup or verified event.
        Returns the attempt (unchanged when the outcome is already
        reflected).
        """
        payout, attempt = lock(attempt)
        outcome = classified.outcome

        if outcome == contract.SETTLED:
            from services.payouts.payout_completion_service import (
                PayoutCompletionService,
            )
            PayoutCompletionService.complete(
                payout=payout,
                attempt=attempt,
                provider_reference=classified.provider_reference,
                provider_status=classified.provider_status,
                evidence_reference=evidence_reference,
            )
            attempt.refresh_from_db()
            return attempt

        if outcome == contract.RETURNED:
            from services.payouts.payout_return_service import PayoutReturnService
            PayoutReturnService.record_return(
                payout=payout,
                attempt=attempt,
                provider_reference=classified.provider_reference,
                evidence_reference=evidence_reference,
            )
            attempt.refresh_from_db()
            return attempt

        if outcome not in OUTCOME_TARGET:
            raise PayoutAttemptTransitionError(f"Unsupported outcome: {outcome}")

        check_reference(attempt, classified.provider_reference)

        if attempt.state in ALREADY_REFLECTED[outcome]:
            return attempt

        return move(
            attempt,
            payout,
            OUTCOME_TARGET[outcome],
            reason=reason,
            provider_reference=classified.provider_reference,
            provider_status=classified.provider_status,
            error_class=classified.error_class,
            evidence_reference=evidence_reference,
        )
