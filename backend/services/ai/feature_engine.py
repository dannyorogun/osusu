from decimal import Decimal

from finance.models import (
    ContributionObligation,
    ObligationStatus,
)

from circles.models import (
    CircleMembership,
)

from circles.models import (
    CircleInvitation,
    InvitationStatus,
)


class FeatureEngine:

    @staticmethod
    def member_features(circle, member):

        obligations = ContributionObligation.objects.filter(
            circle=circle,
            member=member,
        )

        total = obligations.count()

        paid = obligations.filter(
            status=ObligationStatus.PAID
        ).count()

        overdue = obligations.filter(
            status=ObligationStatus.OVERDUE
        ).count()

        payment_rate = (
            paid / total
            if total
            else 1
        )

        invites_sent = CircleInvitation.objects.filter(
            inviter=member,
            circle=circle,
        )

        accepted_invites = invites_sent.filter(
            status=InvitationStatus.ACCEPTED
        ).count()

        invite_success = (
            accepted_invites / invites_sent.count()
            if invites_sent.exists()
            else 1
        )

        return {
            "payment_rate": payment_rate,
            "overdue_count": overdue,
            "invite_success": invite_success,
            "total_obligations": total,
        }

    @staticmethod
    def circle_features(circle):

        members = CircleMembership.objects.filter(
            circle=circle,
            status="active",
        )

        payment_rates = []

        overdue_members = 0

        for membership in members:

            features = FeatureEngine.member_features(
                circle,
                membership.user,
            )

            payment_rates.append(
                features["payment_rate"]
            )

            if features["overdue_count"] > 0:
                overdue_members += 1

        average_payment = (
            sum(payment_rates)
            / len(payment_rates)
            if payment_rates
            else 1
        )

        return {
            "average_payment_rate": average_payment,
            "overdue_members": overdue_members,
            "active_members": members.count(),
        }