from decimal import Decimal

from circles.models import MembershipStatus


class CashFlowEngine:

    PAYOUT_INTERVALS = {
        "weekly": 1,
        "biweekly": 2,
        "monthly": 4,
    }

    @staticmethod
    def simulate(circle):

        constitution = circle.constitution

        members = circle.memberships.filter(
            status=MembershipStatus.ACTIVE
        ).count()

        contribution = constitution.contribution_amount
        payout = constitution.payout_amount
        cycle_length = constitution.cycle_length

        payout_interval = CashFlowEngine.PAYOUT_INTERVALS.get(
            (constitution.payout_frequency or "").lower()
        )

        # payout_frequency is free text; an unknown value cannot be
        # simulated and must fail the check, not raise (HTTP 500).
        if payout_interval is None:
            return {
                "passed": False,
                "timeline": [],
                "failures": [
                    {"reason": "unsupported_payout_frequency"},
                ],
                "ending_treasury": Decimal("0"),
                "payouts_completed": 0,
            }

        treasury = Decimal("0")

        timeline = []

        payouts_completed = 0

        failures = []

        for week in range(1, cycle_length + 1):

            # Collect contributions

            treasury += contribution * members

            event = {
                "week": week,
                "contribution": contribution * members,
                "treasury_before_payout": treasury,
                "payout": Decimal("0"),
                "treasury_after_payout": treasury,
            }

            # Payout week?

            if week % payout_interval == 0:

                if payouts_completed < members:

                    if treasury >= payout:

                        treasury -= payout

                        payouts_completed += 1

                        event["payout"] = payout

                        event["treasury_after_payout"] = treasury

                    else:

                        failures.append(
                            {
                                "week": week,
                                "required": payout,
                                "available": treasury,
                            }
                        )

            timeline.append(event)

        passed = len(failures) == 0

        return {
            "passed": passed,
            "timeline": timeline,
            "failures": failures,
            "ending_treasury": treasury,
            "payouts_completed": payouts_completed,
        }