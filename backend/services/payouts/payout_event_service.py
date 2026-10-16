from django.db import transaction
from django.utils import timezone

from finance.models import PayoutAttempt
from payments.models import WebhookEvent
from services.payouts import provider as contract
from services.payouts.payout_attempt_service import PayoutAttemptService


class UnknownPayoutEvent(ValueError):
    """The event names no payout attempt of this provider."""


class PayoutEventService:

    @staticmethod
    @transaction.atomic
    def process(*, event):
        """
        Apply an AUTHENTICATED provider payout event (from a provider's
        PayoutEventVerifier; none is configured yet).

        - De-duplicated by the existing WebhookEvent table
          (provider_event_id is unique): a processed duplicate returns
          {"status": "duplicate"} and changes nothing.
        - Only identifiers and the outcome are stored, never the raw body.
        - Matched to an attempt by (provider, provider reference), else by
          our idempotency key when the provider echoes it.
        - Applied through the attempt state machine: an out-of-order event
          that is already reflected changes nothing; a contradictory one
          raises and rolls back (including the WebhookEvent row), so it
          is visible for reconciliation and can be redelivered.
        """
        if not isinstance(event, contract.VerifiedPayoutEvent):
            raise TypeError("Only verified provider payout events can be processed.")

        if event.outcome not in contract.EVENT_OUTCOMES:
            raise ValueError(f"Unsupported payout event outcome: {event.outcome}")

        webhook, created = WebhookEvent.objects.select_for_update().get_or_create(
            provider_event_id=event.event_id,
            defaults={
                "provider": event.provider,
                "event_type": event.event_type[:100],
                "payload": {
                    "kind": "payout",
                    "provider_reference": event.provider_reference,
                    "outcome": event.outcome,
                    "provider_status": event.provider_status or None,
                },
            },
        )

        if not created:
            if webhook.provider != event.provider:
                raise ValueError("Event id already used by a different provider.")
            if webhook.processed:
                return {"status": "duplicate", "webhook": webhook, "attempt": None}

        attempt = None
        if event.provider_reference:
            attempt = PayoutAttempt.objects.filter(
                provider=event.provider,
                provider_reference=event.provider_reference,
            ).first()
        if attempt is None and event.idempotency_key:
            attempt = PayoutAttempt.objects.filter(
                provider=event.provider,
                idempotency_key=event.idempotency_key,
            ).first()
        if attempt is None:
            raise UnknownPayoutEvent("No payout attempt matches this event.")

        if event.amount is not None and event.amount != attempt.payout.amount:
            raise ValueError("Event amount does not match the payout amount.")

        attempt = PayoutAttemptService.record(
            attempt,
            contract.Classified(
                event.outcome,
                event.provider_reference,
                (event.provider_status or "")[: contract.STATUS_MAX],
            ),
            evidence_reference=f"event:{event.event_id}"[:200],
        )

        webhook.processed = True
        webhook.processed_at = timezone.now()
        webhook.save(update_fields=["processed", "processed_at"])

        return {"status": "processed", "webhook": webhook, "attempt": attempt}
