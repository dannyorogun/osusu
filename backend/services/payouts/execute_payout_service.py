from django.conf import settings
from django.db import transaction

from finance.models import (
    Payout,
    PayoutAttemptState,
    PayoutStatus,
)

from services.finance.treasury_engine import TreasuryEngine
from services.payouts import provider as contract
from services.payouts.mock_payout_provider import MockPayoutProvider
from services.payouts.payout_attempt_service import (
    EXECUTABLE_STATUSES,
    PayoutAttemptService,
    idempotency_key,  # noqa: F401 (re-exported)
    latest_attempt,
)


class PayoutProviderUnavailable(Exception):
    """
    No provider may send this payout: payouts are disabled, or the provider
    is the development mock outside development, or it is not marked
    production-ready. Raised before any provider call or database write.
    """


def mock_payouts_allowed():
    return getattr(settings, "OSUSU_PAYOUT_MOCK_ALLOWED", False) is True


def get_payout_provider():
    """
    The configured payout provider (settings.OSUSU_PAYOUT_PROVIDER). Fails
    closed: only "mock" resolves, and only in development. No live provider
    is integrated (OPERATIONS.md, "Payout provider").
    """
    name = getattr(settings, "OSUSU_PAYOUT_PROVIDER", "disabled")
    if name == "mock" and mock_payouts_allowed():
        return MockPayoutProvider
    raise PayoutProviderUnavailable(
        "Payouts are disabled: no payout provider is configured."
    )


def ensure_provider_may_send(provider):
    """
    Outside development only a provider that declares production_ready =
    True may send, and the mock never may. Test doubles and the mock run
    only where the mock is allowed.
    """
    if mock_payouts_allowed():
        return
    if getattr(provider, "is_mock", False) or getattr(
        provider, "production_ready", False
    ) is not True:
        raise PayoutProviderUnavailable(
            "Payouts are disabled: the payout provider is not approved for "
            "production."
        )


RESULT_BY_STATE = {
    PayoutAttemptState.SUCCEEDED: "paid",
    PayoutAttemptState.SUBMITTED: "submitted",
    PayoutAttemptState.UNKNOWN: "unknown",
    PayoutAttemptState.FAILED: "failed",
    PayoutAttemptState.PREPARED: "unknown",
}


class ExecutePayoutService:
    """
    Sends an approved payout through the payout provider, in three steps
    with explicit boundaries. No database transaction or row lock is held
    while the provider is called, and no transaction makes the external
    payment atomic with the ledger: the attempt record is what ties them.

    A. Prepare (durable transaction, payout row locked):
       - PAID: "already_paid", no provider call.
       - PROCESSING (an attempt is prepared, submitted or of unknown
         outcome): "in_progress", no provider call. A payout whose money
         may be moving is never executed again; its attempt must first be
         resolved (PayoutResolutionService / provider evidence).
       - RETURNED: refused; paying again is a new governance decision.
       - Otherwise only APPROVED, or FAILED (a CONFIRMED failure), runs.
       - Available treasury (completed ledger minus amounts reserved for
         other in-progress payouts) must cover the amount.
       - No usable provider: PayoutProviderUnavailable before any write.
       - A PREPARED attempt with a new idempotency key is committed and the
         payout becomes PROCESSING (its amount is now reserved).
    B. Send, outside any transaction. Every exception except the
       provider's explicit PayoutNotSent counts as an UNKNOWN outcome.
    C. Record the classified outcome (durable transaction):
       settled (only from a provider that confirms settlement on send)
       -> "paid", one PAYOUT row; accepted -> "submitted"; definitive
       rejection or proven not-sent -> "failed" (may be executed again);
       anything else -> "unknown". If recording itself fails the attempt
       stays PREPARED, which is treated exactly like UNKNOWN.

    A crash between A and C leaves a PREPARED attempt: the payout stays
    PROCESSING and reserved, and is never blindly re-sent.
    """

    @staticmethod
    def execute(payout, provider=None):

        with transaction.atomic(durable=True):

            payout = (
                Payout.objects
                .select_for_update()
                .select_related("circle", "member")
                .get(pk=payout.pk)
            )

            if payout.status == PayoutStatus.PAID:
                return {"status": "already_paid", "payout": payout,
                        "attempt": latest_attempt(payout)}

            if payout.status == PayoutStatus.PROCESSING:
                return {"status": "in_progress", "payout": payout,
                        "attempt": latest_attempt(payout)}

            if payout.status == PayoutStatus.RETURNED:
                raise ValueError(
                    "This payout was returned by the provider. Paying it "
                    "again needs a new decision; it is not retried."
                )

            if payout.status not in EXECUTABLE_STATUSES:
                raise ValueError(
                    "Only approved payouts can be executed."
                )

            available = TreasuryEngine.available_balance(
                payout.circle, exclude=payout,
            )
            if available < payout.amount:
                raise ValueError(
                    "Treasury cannot fund this payout."
                )

            # Resolved after the PAID / PROCESSING checks, so a repeated
            # request is still answered when payouts are disabled; before
            # any write.
            provider = provider or get_payout_provider()
            ensure_provider_may_send(provider)

            attempt = PayoutAttemptService.prepare(
                payout,
                provider_name=getattr(provider, "name", "unknown"),
            )

        try:
            result = provider.send(
                member=payout.member,
                amount=payout.amount,
                idempotency_key=attempt.idempotency_key,
            )
        except Exception as error:
            classified = contract.classify_exception(error)
        else:
            classified = contract.classify_result(provider, result)

        try:
            with transaction.atomic(durable=True):
                attempt = PayoutAttemptService.record(
                    attempt, classified, evidence_reference="send_response",
                )
        except Exception as error:
            # The outcome could not be recorded as classified (e.g. the
            # reference conflicts with an existing record). Never "failed":
            # fall back to UNKNOWN, else leave it PREPARED.
            try:
                with transaction.atomic(durable=True):
                    attempt = PayoutAttemptService.record(
                        attempt,
                        contract.Classified(
                            contract.UNKNOWN,
                            error_class=f"recording_failed:{type(error).__name__}"[:100],
                        ),
                        reason="the provider response could not be recorded",
                    )
            except Exception:
                pass

        payout.refresh_from_db()

        return {
            "status": RESULT_BY_STATE[attempt.state],
            "payout": payout,
            "attempt": attempt,
        }
