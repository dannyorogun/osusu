import uuid

from django.db import transaction

from payments.models import (
    Payment,
    PaymentStatus,
)

from services.payments.mock_provider import (
    MockPaymentProvider,
)


class PaymentService:

    @staticmethod
    @transaction.atomic
    def create_payment(*, obligation):

        existing = Payment.objects.filter(
            obligation=obligation,
        ).first()

        if existing:
            return existing

        payment = Payment.objects.create(
            obligation=obligation,
            provider="mock",
            amount=obligation.amount_due,
            currency="GBP",
            status=PaymentStatus.CREATED,
            idempotency_key=str(uuid.uuid4()),
        )

        provider = MockPaymentProvider()

        result = provider.create_payment(
            payment_id=payment.id,
            amount=payment.amount,
            currency=payment.currency,
            description=(
                f"Osusu contribution "
                f"Period {obligation.period_number}"
            ),
        )

        payment.provider_payment_id = (
            result["provider_payment_id"]
        )

        payment.status = PaymentStatus.PENDING

        payment.metadata = {
            "checkout_url": result["checkout_url"],
        }

        payment.save(
            update_fields=[
                "provider_payment_id",
                "status",
                "metadata",
            ]
        )

        return payment