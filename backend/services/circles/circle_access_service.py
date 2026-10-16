"""
Circle-level authorization.

Knowing a circle's UUID grants nothing: every circle-scoped action must
pass through this service. It only reads (SELECT) and never mutates
state.

Rules (from the existing product model, which defines only two
authorities: the circle creator and its ACTIVE members):
- ACTIVE membership        -> ordinary circle access
- INVITED / LEFT / REMOVED -> no access
- creator (with ACTIVE membership) -> state-changing lifecycle actions
  (formation evaluation, financial lock)

Error semantics, chosen to avoid disclosing which circles/users exist:
- CircleNotFound: the circle does not exist OR the user was never a
  member. Callers must render both identically.
- CircleAccessForbidden: the user has a membership record but it is not
  ACTIVE, or the action needs the creator. These users already know the
  circle exists.
- CircleMemberNotFound: the target user does not exist OR is not an
  ACTIVE member of the circle. Callers must render both identically.
"""

from circles.models import (
    CircleMembership,
    MembershipStatus,
)


class CircleAccessError(Exception):
    pass


class CircleNotFound(CircleAccessError):
    pass


class CircleAccessForbidden(CircleAccessError):
    pass


class CircleMemberNotFound(CircleAccessError):
    pass


class CircleAccessService:

    @staticmethod
    def require_active_member(*, circle_id, user):
        """
        Return the user's ACTIVE membership (with .circle loaded).
        """
        membership = (
            CircleMembership.objects
            .select_related("circle")
            .filter(
                circle_id=circle_id,
                user_id=user.pk,
            )
            .first()
        )

        if membership is None:
            raise CircleNotFound("Circle not found.")

        if membership.status != MembershipStatus.ACTIVE:
            raise CircleAccessForbidden(
                "Only active circle members can access this circle."
            )

        return membership

    @classmethod
    def require_creator(cls, *, circle_id, user):
        """
        Return the creator's ACTIVE membership. A creator who is no longer
        an active member loses creator authority too.
        """
        membership = cls.require_active_member(
            circle_id=circle_id,
            user=user,
        )

        if membership.circle.creator_id != user.pk:
            raise CircleAccessForbidden(
                "Only the circle creator can perform this action."
            )

        return membership

    @staticmethod
    def require_active_target_member(*, circle_id, member_id):
        """
        Return the target user's ACTIVE membership (with .user loaded).
        """
        membership = (
            CircleMembership.objects
            .select_related("user")
            .filter(
                circle_id=circle_id,
                user_id=member_id,
                status=MembershipStatus.ACTIVE,
            )
            .first()
        )

        if membership is None:
            raise CircleMemberNotFound("Member not found in this circle.")

        return membership
