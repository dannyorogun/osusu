"""
Mock payment provider — DEVELOPMENT AND TEST ONLY.

Webhook authentication here is a simple shared-secret HMAC so that local
development cannot be abused to fabricate payments. It is NOT equivalent
to a real provider's webhook security (no timestamp/replay window, no key
rotation, no provider-side signing infrastructure). Real providers must
use their own documented webhook signature verification.

Scheme:
    header  X-Osusu-Mock-Signature: sha256=<hex>
    <hex> = HMAC-SHA256(OSUSU_MOCK_WEBHOOK_SECRET, raw request body)

Body (JSON object):
    {"provider_event_id": str, "event_type": str,
     "payload": {"provider_payment_id": str, ...}}

The mock webhook is disabled unless OSUSU_MOCK_PAYMENTS_ENABLED is true
AND a strong OSUSU_MOCK_WEBHOOK_SECRET is configured (fail closed).
"""

import hashlib
import hmac
import json
from uuid import uuid4

from django.conf import settings

from services.payments.provider import (
    SUPPORTED_WEBHOOK_EVENTS,
    PaymentProvider,
    VerifiedWebhook,
    WebhookPayloadError,
    WebhookVerificationError,
)


SIGNATURE_HEADER = "X-Osusu-Mock-Signature"
SIGNATURE_PREFIX = "sha256="
MIN_SECRET_LENGTH = 32
PLACEHOLDER_SECRETS = frozenset({"change-me-in-development"})


class MockPaymentProvider(PaymentProvider):

    name = "mock"

    def __init__(self, *, webhook_secret=None):
        self._webhook_secret = (
            webhook_secret
            if webhook_secret is not None
            else getattr(settings, "OSUSU_MOCK_WEBHOOK_SECRET", "")
        ) or ""

    # Configuration

    @classmethod
    def webhook_enabled(cls):
        """
        True only when explicitly enabled AND a strong secret is set.
        Anything else — including a missing or placeholder secret — keeps
        the mock webhook disabled.
        """
        secret = getattr(settings, "OSUSU_MOCK_WEBHOOK_SECRET", "") or ""

        return (
            getattr(settings, "OSUSU_MOCK_PAYMENTS_ENABLED", False) is True
            and cls._secret_is_strong(secret)
        )

    @staticmethod
    def _secret_is_strong(secret):
        return (
            len(secret) >= MIN_SECRET_LENGTH
            and secret not in PLACEHOLDER_SECRETS
        )

    # Payments

    def create_payment(
        self,
        *,
        payment_id,
        amount,
        currency,
        description,
    ):
        return {
            "provider_payment_id": str(uuid4()),
            "checkout_url": (
                f"http://localhost:3000/payments/{payment_id}"
            ),
            "status": "pending",
        }

    # Webhooks

    def sign(self, body: bytes) -> str:
        """Header value a genuine mock provider would send for `body`."""
        digest = hmac.new(
            self._webhook_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()

        return f"{SIGNATURE_PREFIX}{digest}"

    def verify_webhook(self, *, body, headers) -> VerifiedWebhook:

        if not self._secret_is_strong(self._webhook_secret):
            raise WebhookVerificationError(
                "Mock webhook secret is not configured."
            )

        signature = headers.get(SIGNATURE_HEADER)

        if not signature or not signature.startswith(SIGNATURE_PREFIX):
            raise WebhookVerificationError("Missing webhook signature.")

        # Constant-time comparison over the raw bytes, before any parsing.
        if not hmac.compare_digest(
            signature.encode(),
            self.sign(body).encode(),
        ):
            raise WebhookVerificationError("Invalid webhook signature.")

        return self._parse(body)

    def _parse(self, body):
        try:
            data = json.loads(body)
        except (UnicodeDecodeError, ValueError) as exc:
            raise WebhookPayloadError("Webhook body is not valid JSON.") from exc

        if not isinstance(data, dict):
            raise WebhookPayloadError("Webhook body must be a JSON object.")

        provider_event_id = data.get("provider_event_id")
        event_type = data.get("event_type")
        payload = data.get("payload")

        if not isinstance(provider_event_id, str) or not provider_event_id:
            raise WebhookPayloadError("provider_event_id is required.")

        if not isinstance(event_type, str) or not event_type:
            raise WebhookPayloadError("event_type is required.")

        if event_type not in SUPPORTED_WEBHOOK_EVENTS:
            raise WebhookPayloadError("Unsupported webhook event type.")

        if not isinstance(payload, dict):
            raise WebhookPayloadError("payload must be a JSON object.")

        provider_payment_id = payload.get("provider_payment_id")

        if not isinstance(provider_payment_id, str) or not provider_payment_id:
            raise WebhookPayloadError("provider_payment_id is required.")

        return VerifiedWebhook(
            provider=self.name,
            provider_event_id=provider_event_id,
            event_type=event_type,
            provider_payment_id=provider_payment_id,
            payload=payload,
        )
