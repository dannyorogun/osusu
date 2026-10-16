from django.db import transaction
from django.utils import timezone

from circles.models import (
    CircleMembership,
    MembershipStatus,
    CircleStatus,
)

from services.audit.audit_service import AuditService


class ConstitutionService:

    @staticmethod
    @transaction.atomic
    def accept(*, circle, user):

        # Circle cannot accept new constitution agreements
        # once it has been financially locked.
        if circle.status in [
            CircleStatus.LOCKED,
            CircleStatus.ACTIVE,
            CircleStatus.COMPLETED,
        ]:
            raise ValueError(
                "The circle constitution can no longer be accepted."
            )

        # Find the user's membership
        try:
            membership = CircleMembership.objects.get(
                circle=circle,
                user=user,
            )
        except CircleMembership.DoesNotExist:
            raise ValueError(
                "You are not a member of this circle."
            )

        # User must be an active member
        if membership.status != MembershipStatus.ACTIVE:
            raise ValueError(
                "Only active members can accept the constitution."
            )

        # Prevent duplicate acceptance
        if membership.constitution_accepted:
            return membership

        # Record acceptance
        membership.constitution_accepted = True
        membership.constitution_accepted_at = timezone.now()

        membership.save(
            update_fields=[
                "constitution_accepted",
                "constitution_accepted_at",
            ]
        )

        # Audit trail
        AuditService.record(
            action="CONSTITUTION_ACCEPTED",
            entity_type="CircleMembership",
            entity_id=membership.id,
            user=user,
            metadata={
                "circle_id": str(circle.id),
                "accepted_at": membership.constitution_accepted_at.isoformat(),
            },
        )

        return membership