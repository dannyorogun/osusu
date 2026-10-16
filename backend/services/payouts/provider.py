"""
Provider-independent payout execution contract.

No live provider implements this yet. A provider adapter is an object with:

    name: str
    production_ready: bool               (False until independently reviewed)
    confirms_settlement_on_send: bool    (default False)
    supports_status_lookup: bool         (default False)

    send(*, member, amount, idempotency_key) -> PayoutSendResult | dict
    lookup_status(*, idempotency_key, provider_reference) -> PayoutSendResult | None
        (only when supports_status_lookup)

Capabilities are read with getattr and default to the SAFE value: a
provider that does not declare a capability does not have it. Osusu never
assumes that a provider de-duplicates on the idempotency key or can be
queried for status.

How send() outcomes are classified (classify_send_result):

- PayoutSendResult / dict with outcome "settled" and a provider reference:
  SETTLED only if the provider declares confirms_settlement_on_send
  (settlement is authoritative on the synchronous response); otherwise it
  is treated as ACCEPTED (awaiting settlement evidence).
- outcome "accepted" with a reference: ACCEPTED (attempt SUBMITTED).
- outcome "rejected": REJECTED (attempt FAILED). The adapter must return
  this ONLY for the provider's documented definitive rejection.
- PayoutNotSent raised: NOT_SENT (attempt FAILED). The adapter must raise
  it ONLY when it can prove no request reached the provider.
- Anything else, including every other exception, a missing reference,
  an unrecognised outcome or a legacy {"status": "failed"}: UNKNOWN.
  Money may have moved; nothing is retried.
"""

from collections.abc import Mapping
from dataclasses import dataclass


ACCEPTED = "accepted"
SETTLED = "settled"
REJECTED = "rejected"
NOT_SENT = "not_sent"
UNKNOWN = "unknown"

# Lengths of PayoutAttempt fields.
REFERENCE_MAX = 150
STATUS_MAX = 50


class PayoutNotSent(Exception):
    """
    Raised by a provider adapter only when it can prove the request never
    left Osusu (e.g. local validation, connection refused before any byte
    was written). Any other exception is treated as an unknown outcome.
    """


@dataclass(frozen=True)
class PayoutSendResult:
    outcome: str
    provider_reference: str = ""
    provider_status: str = ""


@dataclass(frozen=True)
class Classified:
    outcome: str
    provider_reference: str = ""
    provider_status: str = ""
    error_class: str = ""


def confirms_settlement_on_send(provider):
    return getattr(provider, "confirms_settlement_on_send", False) is True


def supports_status_lookup(provider):
    return (
        getattr(provider, "supports_status_lookup", False) is True
        and callable(getattr(provider, "lookup_status", None))
    )


def _short(value, limit):
    return value[:limit] if isinstance(value, str) else ""


def _fields(result):
    if isinstance(result, PayoutSendResult):
        return result.outcome, result.provider_reference, result.provider_status
    if isinstance(result, Mapping):
        outcome = result.get("outcome")
        if outcome is None and result.get("status") == "sent":
            # Pre-Sprint 33 adapters: "sent" means accepted, not settled.
            outcome = ACCEPTED
        return outcome, result.get("provider_reference"), result.get("provider_status")
    return None, None, None


def classify_result(provider, result, *, error_class=""):
    """Classify a send() or lookup_status() result. Never raises."""
    outcome, reference, status = _fields(result)
    reference = reference if isinstance(reference, str) else ""
    status = _short(status, STATUS_MAX)

    if outcome == REJECTED:
        return Classified(REJECTED, _short(reference, REFERENCE_MAX), status, "rejected")

    if outcome in (ACCEPTED, SETTLED) and reference and len(reference) <= REFERENCE_MAX:
        if outcome == SETTLED and confirms_settlement_on_send(provider):
            return Classified(SETTLED, reference, status)
        return Classified(ACCEPTED, reference, status)

    return Classified(UNKNOWN, "", status, error_class or "unrecognised_response")


def classify_exception(error):
    if isinstance(error, PayoutNotSent):
        return Classified(NOT_SENT, error_class=NOT_SENT)
    # Class name only: messages may carry request details.
    return Classified(UNKNOWN, error_class=type(error).__name__[:100])


@dataclass(frozen=True)
class VerifiedPayoutEvent:
    """
    A payout status event whose authenticity a provider-specific verifier
    has proven (signature over the raw body, timestamp tolerance, constant
    time comparison, per the provider's official protocol). Only such a
    verifier may construct one. No verifier exists yet: none is
    configured until a provider is selected.

    outcome: ACCEPTED | SETTLED | REJECTED | "returned"
    """

    provider: str
    event_id: str
    event_type: str
    provider_reference: str
    outcome: str
    provider_status: str = ""
    amount: object = None
    # Our idempotency key, when the provider's event carries it.
    idempotency_key: str = ""


RETURNED = "returned"
EVENT_OUTCOMES = frozenset({ACCEPTED, SETTLED, REJECTED, RETURNED})


class PayoutEventVerifier:
    """
    Interface for authenticating provider payout webhooks. The base class
    refuses everything: an unsigned or unverifiable event is never
    trusted, and no generic signature scheme is provided.
    """

    provider = None

    def verify(self, *, body: bytes, headers) -> VerifiedPayoutEvent:
        raise NotImplementedError(
            "No payout webhook verification is configured: a provider's "
            "official signature protocol must be implemented first."
        )


@dataclass(frozen=True)
class ProviderTransferRecord:
    """One row of a provider's settlement/transaction report."""

    provider: str
    provider_reference: str
    amount: object
    status: str
