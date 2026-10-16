from django.db import transaction
from django.utils import timezone

from circles.models import CircleStatus

from finance.models import (
    ContributionObligation,
    ObligationStatus,
    TransactionType,
)

from services.finance.ledger_service import LedgerService


class ContributionService:

    @staticmethod
    @transaction.atomic
    def record(
        *,
        circle,
        member,
        period_number,
        payment_reference=None,
    ):
        if circle.status not in [
            CircleStatus.LOCKED,
            CircleStatus.ACTIVE,
        ]:
            raise ValueError(
                "Contributions cannot be recorded."
            )

        obligation = (
            ContributionObligation.objects
            .select_for_update()
            .get(
                circle=circle,
                member=member,
                period_number=period_number,
            )
        )

        if obligation.status == ObligationStatus.PAID:
            return obligation

        if obligation.status == ObligationStatus.WAIVED:
            raise ValueError(
                "This obligation has been waived."
            )

        LedgerService.record_transaction(
            circle=circle,
            member=member,
            transaction_type=TransactionType.CONTRIBUTION,
            amount=obligation.amount_due,
            period_number=period_number,
            reference=f"P{period_number}",
            payment_reference=payment_reference,
            metadata={
                "obligation_id": str(obligation.id),
            },
        )

        obligation.status = ObligationStatus.PAID
        obligation.paid_at = timezone.now()

        obligation.save(
            update_fields=[
                "status",
                "paid_at",
            ]
        )

        return obligation