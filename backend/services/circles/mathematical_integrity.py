from decimal import Decimal

from circles.models import MembershipStatus


class MathematicalIntegrityEngine:

    CONTRIBUTION_PERIODS_PER_CYCLE = {
        "weekly": 1,
        "biweekly": 1,
        "monthly": 1,
    }

    PAYOUT_INTERVALS = {
        "weekly": 1,
        "biweekly": 2,
        "monthly": 4,
    }

    @staticmethod
    def validate(circle):

        constitution = circle.constitution

        member_count = circle.memberships.filter(
            status=MembershipStatus.ACTIVE
        ).count()

        contribution = constitution.contribution_amount
        payout = constitution.payout_amount
        cycle_length = constitution.cycle_length

        contribution_frequency = (
            constitution.contribution_frequency.lower()
        )

        payout_frequency = (
            constitution.payout_frequency.lower()
        )

        checks = {}

        # --------------------------------------------------
        # 1. Basic financial validation
        # --------------------------------------------------

        checks["members_exist"] = member_count >= 2

        checks["contribution_positive"] = (
            contribution > Decimal("0")
        )

        checks["payout_positive"] = (
            payout > Decimal("0")
        )

        checks["cycle_length_positive"] = (
            cycle_length > 0
        )

        checks["contribution_frequency_supported"] = (
            contribution_frequency
            in MathematicalIntegrityEngine.CONTRIBUTION_PERIODS_PER_CYCLE
        )

        checks["payout_frequency_supported"] = (
            payout_frequency
            in MathematicalIntegrityEngine.PAYOUT_INTERVALS
        )

        if not all(checks.values()):

            return {
                "passed": False,
                "checks": checks,
                "member_count": member_count,
                "total_contributions": Decimal("0"),
                "total_payouts": Decimal("0"),
                "reserve": Decimal("0"),
                "required_funds": Decimal("0"),
                "surplus": Decimal("0"),
                "payout_events": 0,
            }

        # --------------------------------------------------
        # 2. Calculate contribution periods
        # --------------------------------------------------

        # MVP interpretation:
        # cycle_length represents weeks.

        contribution_periods = cycle_length

        total_contributions = (
            contribution
            * member_count
            * contribution_periods
        )

        # --------------------------------------------------
        # 3. Calculate payout events
        # --------------------------------------------------

        payout_interval = (
            MathematicalIntegrityEngine.PAYOUT_INTERVALS[
                payout_frequency
            ]
        )

        payout_events = cycle_length // payout_interval

        checks["payout_frequency_fits_cycle"] = (
            cycle_length % payout_interval == 0
        )

        # For the MVP, every member receives exactly
        # one payout during the cycle.
        checks["one_payout_per_member"] = (
            payout_events == member_count
        )

        total_payouts = (
            payout
            * payout_events
        )

        # --------------------------------------------------
        # 4. Reserve
        # --------------------------------------------------

        if constitution.reserve_enabled:

            reserve = constitution.reserve_amount

            checks["reserve_valid"] = (
                reserve >= Decimal("0")
            )

        else:

            reserve = Decimal("0")

            checks["reserve_valid"] = True

        # --------------------------------------------------
        # 5. Required funds
        # --------------------------------------------------

        required_funds = (
            total_payouts + reserve
        )

        checks["contributions_cover_obligations"] = (
            total_contributions >= required_funds
        )

        # --------------------------------------------------
        # 6. Payout amount must match the intended pot
        # --------------------------------------------------

        if payout_events > 0:

            expected_payout = (
                total_contributions
                - reserve
            ) / payout_events

            checks["payout_matches_cycle"] = (
                payout == expected_payout
            )

        else:

            expected_payout = Decimal("0")

            checks["payout_matches_cycle"] = False

        passed = all(checks.values())

        return {
            "passed": passed,
            "checks": checks,
            "member_count": member_count,
            "contribution_periods": contribution_periods,
            "payout_events": payout_events,
            "contribution_frequency": contribution_frequency,
            "payout_frequency": payout_frequency,
            "total_contributions": total_contributions,
            "total_payouts": total_payouts,
            "reserve": reserve,
            "required_funds": required_funds,
            "surplus": (
                total_contributions
                - required_funds
            ),
            "expected_payout": expected_payout,
        }