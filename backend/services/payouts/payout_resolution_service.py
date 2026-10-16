"""
Status resolution for live payout attempts (PREPARED / SUBMITTED /
UNKNOWN). The only way out of an uncertain state is provider evidence;
nothing here re-sends a payment or infers failure from silence.
"""

from datetime import timedelta

from django.utils import timezone

from finance.models import PayoutAttempt, PayoutAttemptState
from services.payouts import provider as contract
from services.payouts.payout_attempt_service import PayoutAttemptService


# A PREPARED attempt older than this was committed but its send was never
# recorded (crash, killed worker): whether it reached the provider is
# unknown. Assumption: no provider call legitimately takes this long.
STALE_PREPARED_AFTER = timedelta(minutes=15)

DECISIVE_OUTCOMES = (contract.SETTLED, contract.ACCEPTED, contract.REJECTED)


def operator_action(attempt):
    return (
        f"Confirm the outcome of payout attempt {attempt.id} with provider "
        f"'{attempt.provider}' (idempotency key {attempt.idempotency_key}"
        + (f", provider reference {attempt.provider_reference}" if attempt.provider_reference else "")
        + "). Do not execute this payout again. Record the outcome only "
        "from the provider's authoritative evidence; until then the amount "
        "stays reserved."
    )


def classify_lookup(result):
    """
    A status lookup answers with the provider's current status, so a
    'settled' answer is authoritative (unlike a send() acknowledgement).
    'Not found' (None) is never a failure: it may not be visible yet.
    """
    if result is None:
        return contract.Classified(contract.UNKNOWN, error_class="not_found")
    outcome, reference, status = contract._fields(result)
    reference = reference if isinstance(reference, str) else ""
    status = contract._short(status, contract.STATUS_MAX)
    if outcome == contract.REJECTED:
        return contract.Classified(contract.REJECTED, reference, status, "rejected")
    if outcome in (contract.SETTLED, contract.ACCEPTED) and reference:
        return contract.Classified(outcome, reference[:contract.REFERENCE_MAX], status)
    return contract.Classified(contract.UNKNOWN, error_class="unrecognised_lookup")


class PayoutResolutionService:

    @staticmethod
    def resolve(attempt, provider=None, *, now=None):
        """
        Try to resolve one live attempt. Returns
        {"result": "unchanged" | "resolved" | "unresolved", "attempt", "action"}.

        1. With a provider that declares supports_status_lookup (and is the
           attempt's provider), ask it by idempotency key / reference and
           apply a decisive answer.
        2. A PREPARED attempt older than STALE_PREPARED_AFTER becomes
           UNKNOWN (it may have been sent).
        3. Anything still live is "unresolved", with the operator action.
        """
        now = now or timezone.now()
        attempt = PayoutAttempt.objects.get(pk=attempt.pk)

        if not attempt.is_live:
            return {"result": "unchanged", "attempt": attempt, "action": None}

        if (
            provider is not None
            and getattr(provider, "name", None) == attempt.provider
            and contract.supports_status_lookup(provider)
        ):
            try:
                answer = provider.lookup_status(
                    idempotency_key=attempt.idempotency_key,
                    provider_reference=attempt.provider_reference or None,
                )
            except Exception:
                answer = None
            classified = classify_lookup(answer)
            if classified.outcome in DECISIVE_OUTCOMES:
                attempt = PayoutAttemptService.record(
                    attempt, classified, evidence_reference="status_lookup",
                )
                if not attempt.is_live:
                    return {"result": "resolved", "attempt": attempt, "action": None}

        if (
            attempt.state == PayoutAttemptState.PREPARED
            and now - attempt.created_at >= STALE_PREPARED_AFTER
        ):
            attempt = PayoutAttemptService.record(
                attempt,
                contract.Classified(contract.UNKNOWN, error_class="stale_prepared"),
                reason="prepared attempt was never recorded as sent",
            )

        return {
            "result": "unresolved",
            "attempt": attempt,
            "action": operator_action(attempt),
        }
