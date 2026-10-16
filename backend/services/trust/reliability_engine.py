from decimal import Decimal

from trust.models import TrustProfile


class ReliabilityEngine:

    @staticmethod
    def calculate(profile: TrustProfile):

        if profile.payments_made == 0:
            payment_reliability = Decimal("0")
        else:
            payment_reliability = (
                Decimal(
                    profile.payments_made
                    - profile.late_payments
                )
                / Decimal(profile.payments_made)
            )

        cycle_reliability = min(
            Decimal(profile.completed_cycles)
            / Decimal("5"),
            Decimal("1"),
        )

        participation_reliability = (
            Decimal(profile.votes_participated)
            / Decimal(
                max(profile.votes_participated, 10)
            )
        )

        reliability = (
            payment_reliability * Decimal("0.60")
            + cycle_reliability * Decimal("0.25")
            + participation_reliability * Decimal("0.15")
        )

        return round(
            reliability * Decimal("100"),
            2,
        )