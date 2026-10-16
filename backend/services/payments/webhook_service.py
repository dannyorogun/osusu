from django.db import transaction
from django.utils import timezone

from payments.models import (
    Payment,
    PaymentStatus,
    WebhookEvent,
)

from services.payments.payment_completion_service import (
    PaymentCompletionService,
)
from services.payments.provider import (
    SUPPORTED_WEBHOOK_EVENTS,
    VerifiedWebhook,
)


class PaymentWebhookService:

    @staticmethod
    @transaction.atomic
    def process(*, event: VerifiedWebhook):
        """
        Apply an AUTHENTICATED provider event. Callers must obtain `event`
        from the provider's verify_webhook(); a provider_payment_id on its
        own proves nothing.

        Atomic: any rejection (unknown payment, invalid transition) rolls
        back every write, including the WebhookEvent record, so rejected
        events leave no trace and can be retried.
        """
        if not isinstance(event, VerifiedWebhook):
            raise TypeError("Only verified provider webhooks can be processed.")

        if event.event_type not in SUPPORTED_WEBHOOK_EVENTS:
            raise ValueError(
                f"Unsupported webhook event: {event.event_type}"
            )

        event_type = event.event_type

        webhook, created = WebhookEvent.objects.get_or_create(
            provider_event_id=event.provider_event_id,
            defaults={
                "provider": event.provider,
                "event_type": event_type,
                "payload": event.payload,
            },
        )

        if not created and webhook.processed:
            return webhook

        payment = (
            Payment.objects
            .select_for_update()
            .get(
                provider=event.provider,
                provider_payment_id=event.provider_payment_id,
            )
        )

        if event_type == "payment.completed":

            PaymentCompletionService.complete(
                payment
            )

        elif event_type == "payment.failed":

            if payment.status == PaymentStatus.COMPLETED:
                raise ValueError(
                    "A completed payment cannot be marked as failed."
                )

            if payment.status == PaymentStatus.FAILED:
                webhook.processed = True
                webhook.processed_at = timezone.now()
                webhook.save(
                    update_fields=[
                        "processed",
                        "processed_at",
                    ]
                )
                return webhook

            # Only PENDING -> FAILED is a valid transition.
            if payment.status != PaymentStatus.PENDING:
                raise ValueError(
                    "Payment cannot be marked as failed from its "
                    "current state."
                )

            payment.status = PaymentStatus.FAILED

            payment.save(
                update_fields=["status"]
            )

        else:
            raise ValueError(
                f"Unsupported webhook event: {event_type}"
            )

        webhook.processed = True
        webhook.processed_at = timezone.now()

        webhook.save(
            update_fields=[
                "processed",
                "processed_at",
            ]
        )

        return webhook