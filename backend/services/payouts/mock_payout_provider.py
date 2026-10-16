import hashlib


REFERENCE_PREFIX = "mock_payout_"


class MockPayoutProvider:
    """
    DEVELOPMENT/TEST payout provider. Sends nothing.

    The provider reference is derived from the caller's idempotency key,
    so a repeated key yields the same reference.

    It reports synchronous settlement (confirms_settlement_on_send) so the
    development journey reaches PAID. That is a property of this mock
    only: it proves nothing about a real provider, most of which settle
    asynchronously (services/payouts/provider.py).
    """

    name = "mock"
    # Never production-ready: ExecutePayoutService and
    # PayoutCompletionService refuse it outside development.
    is_mock = True
    production_ready = False
    confirms_settlement_on_send = True
    supports_status_lookup = False

    @staticmethod
    def send(
        *,
        member,
        amount,
        idempotency_key,
    ):

        digest = hashlib.sha256(
            idempotency_key.encode("utf-8")
        ).hexdigest()[:32]

        return {
            "provider_reference": f"{REFERENCE_PREFIX}{digest}",
            "outcome": "settled",
            "status": "sent",
            "amount": str(amount),
        }
