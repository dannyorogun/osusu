from django.db.models import Count

from finance.models import (
    ContributionObligation,
    ObligationStatus,
)

from circles.models import (
    CircleMembership,
    MembershipStatus,
)

from trust.models import TrustProfile


class TrustFeatureEngine:

    @staticmethod
    def compute(user):
        """
        Read-only trust counts for a user. Performs no writes, so it is
        safe to call from prediction paths.
        """

        completed_cycles = CircleMembership.objects.filter(
            user=user,
            status=MembershipStatus.ACTIVE,
            circle__status="completed",
        ).count()

        payments_made = ContributionObligation.objects.filter(
            member=user,
            status=ObligationStatus.PAID,
        ).count()

        late_payments = ContributionObligation.objects.filter(
            member=user,
            status=ObligationStatus.OVERDUE,
        ).count()

        defaults = ContributionObligation.objects.filter(
            member=user,
            status=ObligationStatus.OVERDUE,
        ).count()

        return {
            "completed_cycles": completed_cycles,
            "payments_made": payments_made,
            "late_payments": late_payments,
            "defaults": defaults,
        }

    @staticmethod
    def calculate(user):

        counts = TrustFeatureEngine.compute(user)

        profile, _ = TrustProfile.objects.get_or_create(
            user=user,
        )

        profile.completed_cycles = counts["completed_cycles"]
        profile.payments_made = counts["payments_made"]
        profile.late_payments = counts["late_payments"]
        profile.defaults = counts["defaults"]

        profile.save(
            update_fields=[
                "completed_cycles",
                "payments_made",
                "late_payments",
                "defaults",
                "updated_at",
            ]
        )

        return profile