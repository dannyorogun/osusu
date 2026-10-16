from django.db import transaction
from django.utils import timezone

from payments.models import (
    Payment,
    PaymentStatus,
)

from services.finance.contribution_service import (
    ContributionService,
)


class PaymentCompletionService:

    @staticmethod
    @transaction.atomic
    def complete(payment):

        payment = (
            Payment.objects
            .select_for_update()
            .select_related(
                "obligation",
                "obligation__circle",
                "obligation__member",
            )
            .get(pk=payment.pk)
        )

        if payment.status == PaymentStatus.COMPLETED:
            return payment

        if payment.status != PaymentStatus.PENDING:
            raise ValueError(
                "Payment cannot be completed from its current state."
            )

        obligation = payment.obligation

        ContributionService.record(
            circle=obligation.circle,
            member=obligation.member,
            period_number=obligation.period_number,
            payment_reference=payment.provider_payment_id,
        )

        payment.status = PaymentStatus.COMPLETED
        payment.completed_at = timezone.now()

        payment.save(
            update_fields=[
                "status",
                "completed_at",
            ]
        )

        return payment