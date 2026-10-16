from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal


SUPPORTED_WEBHOOK_EVENTS = frozenset({
    "payment.completed",
    "payment.failed",
})


class WebhookError(Exception):
    """Base class: the webhook must not cause any state change."""


class WebhookVerificationError(WebhookError):
    """The request could not be proven to come from the provider."""


class WebhookPayloadError(WebhookError):
    """The request is authentic but its content is invalid."""


@dataclass(frozen=True)
class VerifiedWebhook:
    """
    A provider event whose authenticity has been verified. Only a
    provider's verify_webhook() should construct one.
    """

    provider: str
    provider_event_id: str
    event_type: str
    provider_payment_id: str
    payload: dict = field(default_factory=dict)


class PaymentProvider(ABC):

    name: str

    @abstractmethod
    def create_payment(
        self,
        *,
        payment_id,
        amount: Decimal,
        currency: str,
        description: str,
    ):
        pass

    @abstractmethod
    def verify_webhook(
        self,
        *,
        body: bytes,
        headers: Mapping[str, str],
    ) -> VerifiedWebhook:
        """
        Authenticate a webhook from the RAW request body and headers, then
        parse it. Must raise WebhookVerificationError before parsing
        anything if authenticity cannot be proven, and
        WebhookPayloadError for authentic but invalid content.

        Real providers must implement their own documented signature
        scheme here (e.g. timestamped HMAC with replay tolerance). Knowing
        a provider_payment_id is never proof of authenticity.
        """
