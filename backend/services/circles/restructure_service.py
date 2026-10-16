from django.db import transaction

from circles.models import (
    CircleRestructure,
    RestructureStatus,
)

from services.circles.restructure_engine import (
    RestructureEngine
)

from services.audit.audit_service import (
    AuditService
)


class RestructureService:

    @staticmethod
    @transaction.atomic
    def propose(circle, user):

        data = RestructureEngine.calculate(circle)

        restructure = CircleRestructure.objects.create(
            circle=circle,
            proposed_by=user,
            removed_members=data["removed_members"],
            remaining_members=data["remaining_members"],
            new_payout_amount=data["new_payout_amount"],
            remaining_periods=data["remaining_periods"],
            status=RestructureStatus.VOTING,
        )

        AuditService.record(
            action="RESTRUCTURE_PROPOSED",
            entity_type="CircleRestructure",
            entity_id=restructure.id,
            user=user,
            metadata=data,
        )

        return restructure