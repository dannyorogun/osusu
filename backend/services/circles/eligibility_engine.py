from finance.models import (
    ContributionObligation,
    ObligationStatus,
)

from circles.models import (
    CircleMembership,
    MembershipStatus,
)


class EligibilityEngine:

    @staticmethod
    def eligible_members(circle):

        members = CircleMembership.objects.filter(
            circle=circle,
            status=MembershipStatus.ACTIVE,
        )

        eligible = []

        for membership in members:

            overdue = ContributionObligation.objects.filter(
                circle=circle,
                member=membership.user,
                status=ObligationStatus.OVERDUE,
            ).exists()

            if not overdue:
                eligible.append(membership.user)

        return eligible