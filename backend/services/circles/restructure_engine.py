from decimal import Decimal

from circles.models import (
    CircleMembership,
    MembershipStatus,
)


class RestructureEngine:

    @staticmethod
    def calculate(circle):

        constitution = circle.constitution

        active_members = CircleMembership.objects.filter(
            circle=circle,
            status=MembershipStatus.ACTIVE,
        ).count()

        removed = (
            constitution.member_limit
            - active_members
        )

        remaining_periods = (
            constitution.cycle_length
        )

        contribution = constitution.contribution_amount

        new_payout = (
            contribution
            * active_members
            * 2
        )

        return {
            "removed_members": removed,
            "remaining_members": active_members,
            "remaining_periods": remaining_periods,
            "new_payout_amount": new_payout,
        }