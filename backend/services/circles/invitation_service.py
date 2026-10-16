from django.db import transaction
from django.utils import timezone
from services.trust.trust_graph_service import (
    TrustGraphService,
)

from circles.models import (
    CircleInvitation,
    CircleMembership,
    MembershipStatus,
    InvitationStatus,
    CircleStatus,
)

from services.audit.audit_service import AuditService


class InvitationService:

    @staticmethod
    @transaction.atomic
    def create_invitation(*, circle, inviter, email):

        # Circle must still be recruiting
        if circle.status != CircleStatus.RECRUITING:
            raise ValueError(
                "This circle is no longer accepting invitations."
            )

        # Inviter must be an active member
        if not CircleMembership.objects.filter(
            circle=circle,
            user=inviter,
            status=MembershipStatus.ACTIVE,
        ).exists():
            raise ValueError(
                "Only active members can invite people."
            )

        # Check member limit
        active_members = CircleMembership.objects.filter(
            circle=circle,
            status=MembershipStatus.ACTIVE,
        ).count()

        if active_members >= circle.constitution.member_limit:
            raise ValueError(
                "The circle has reached its member limit."
            )

        # Check whether user already belongs to circle
        if CircleMembership.objects.filter(
            circle=circle,
            user__email__iexact=email,
        ).exists():
            raise ValueError(
                "This user already belongs to the circle."
            )

        # Prevent duplicate pending invitations
        if CircleInvitation.objects.filter(
            circle=circle,
            email__iexact=email,
            status=InvitationStatus.PENDING,
        ).exists():
            raise ValueError(
                "A pending invitation already exists for this email."
            )

        invitation = CircleInvitation.objects.create(
            circle=circle,
            inviter=inviter,
            email=email.lower(),
        )

        AuditService.record(
            action="INVITATION_CREATED",
            entity_type="CircleInvitation",
            entity_id=invitation.id,
            user=inviter,
            metadata={
                "circle_id": str(circle.id),
                "email": email.lower(),
            },
        )

        return invitation

    @staticmethod
    @transaction.atomic
    def accept_invitation(*, invitation, user):

        if invitation.status != InvitationStatus.PENDING:
            raise ValueError(
                "Invitation is no longer valid."
            )

        if invitation.is_expired():

            invitation.status = InvitationStatus.EXPIRED

            invitation.save(
                update_fields=["status"]
            )

            raise ValueError(
                "Invitation has expired."
            )

        # Security check:
        # invitation must belong to the user's email
        if invitation.email.lower() != user.email.lower():
            raise ValueError(
                "This invitation was not sent to your email address."
            )

        if invitation.circle.status != CircleStatus.RECRUITING:
            raise ValueError(
                "This circle is no longer accepting members."
            )

        # Check member limit again at acceptance time
        # because another person may have joined after
        # the invitation was created.
        active_members = CircleMembership.objects.filter(
            circle=invitation.circle,
            status=MembershipStatus.ACTIVE,
        ).count()

        if active_members >= invitation.circle.constitution.member_limit:
            raise ValueError(
                "The circle has reached its member limit."
            )

        # Prevent duplicate membership
        if CircleMembership.objects.filter(
            circle=invitation.circle,
            user=user,
        ).exists():
            raise ValueError(
                "You already belong to this circle."
            )

        membership = CircleMembership.objects.create(
            circle=invitation.circle,
            user=user,
            invited_by=invitation.inviter,
            status=MembershipStatus.ACTIVE,
            joined_at=timezone.now(),
        )

        invitation.status = InvitationStatus.ACCEPTED
        invitation.accepted_at = timezone.now()

        invitation.save(
            update_fields=[
                "status",
                "accepted_at",
            ]
        )
        TrustGraphService.create_edge(
        inviter=invitation.inviter,
        invited=membership.user,
            )

        AuditService.record(
            action="INVITATION_ACCEPTED",
            entity_type="CircleInvitation",
            entity_id=invitation.id,
            user=user,
            metadata={
                "circle_id": str(invitation.circle.id),
            },
        )

        return membership