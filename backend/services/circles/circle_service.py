from django.db import transaction
from django.utils import timezone

from circles.models import (
    Circle,
    CircleConstitution,
    CircleMembership,
    MembershipStatus,
)

from services.audit.audit_service import AuditService


class CircleService:

    @staticmethod
    @transaction.atomic
    def create_circle(
        *,
        creator,
        name,
        description="",
        member_limit=10,
        contribution_amount=50,
    ):

        circle = Circle.objects.create(
            creator=creator,
            name=name,
            description=description,
            status="recruiting",
        )

        CircleConstitution.objects.create(
            circle=circle,
            member_limit=member_limit,
            contribution_amount=contribution_amount,
        )

        CircleMembership.objects.create(
            circle=circle,
            user=creator,
            invited_by=None,
            status=MembershipStatus.ACTIVE,
            joined_at=timezone.now(),
        )

        AuditService.record(
            action="CIRCLE_CREATED",
            entity_type="Circle",
            entity_id=circle.id,
            user=creator,
            metadata={
                "member_limit": member_limit,
                "contribution": str(contribution_amount),
            },
        )

        return circle