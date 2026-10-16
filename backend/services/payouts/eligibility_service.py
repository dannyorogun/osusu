from finance.models import (
    DECIDED_PAYOUT_STATUSES,
    Payout,
    ObligationStatus,
)

from circles.models import (
    CircleMembership,
    MembershipStatus,
)


class PayoutEligibilityService:

    @staticmethod
    def eligible(circle):

        memberships = CircleMembership.objects.filter(
            circle=circle,
            status=MembershipStatus.ACTIVE,
            constitution_accepted=True,
        )

        eligible = []

        for membership in memberships:

            overdue = membership.user.contribution_obligations.filter(
                circle=circle,
                status=ObligationStatus.OVERDUE,
            ).exists()

            # Selected recipients only: a cancelled (losing) candidate
            # stays eligible for later windows. A RETURNED recipient is
            # not re-selected automatically (a new governance decision).
            already_received = Payout.objects.filter(
                circle=circle,
                member=membership.user,
                status__in=DECIDED_PAYOUT_STATUSES,
            ).exists()

            if overdue:
                continue

            if already_received:
                continue

            eligible.append(membership.user)

        return eligible