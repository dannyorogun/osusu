from decimal import Decimal

from finance.models import (
    ContributionObligation,
    ObligationStatus,
)

from services.finance.treasury_engine import (
    TreasuryEngine,
)

from services.trust.trust_graph_service import (
    TrustGraphService,
)


class RiskEngine:

    @staticmethod
    def analyze_circle(circle):

        signals = []

        obligations = ContributionObligation.objects.filter(
            circle=circle,
        )

        total_obligations = obligations.count()

        overdue_obligations = obligations.filter(
            status=ObligationStatus.OVERDUE,
        ).count()

        paid_obligations = obligations.filter(
            status=ObligationStatus.PAID,
        ).count()

        # --------------------------------------------------
        # PAYMENT RISK
        # --------------------------------------------------

        if total_obligations > 0:

            overdue_rate = (
                Decimal(overdue_obligations)
                / Decimal(total_obligations)
            )

            payment_rate = (
                Decimal(paid_obligations)
                / Decimal(total_obligations)
            )

        else:

            overdue_rate = Decimal("0")
            payment_rate = Decimal("1")

        if overdue_rate >= Decimal("0.20"):

            signals.append({
                "type": "PAYMENT_RISK",
                "severity": "high",
                "message": (
                    "More than 20% of contribution "
                    "obligations are overdue."
                ),
                "value": str(
                    round(overdue_rate * 100, 2)
                ),
            })

        elif overdue_rate > Decimal("0"):

            signals.append({
                "type": "PAYMENT_RISK",
                "severity": "medium",
                "message": (
                    "The circle has overdue "
                    "contribution obligations."
                ),
                "value": str(
                    round(overdue_rate * 100, 2)
                ),
            })

        # --------------------------------------------------
        # FUNDING RISK
        # --------------------------------------------------

        treasury_balance = (
            TreasuryEngine.current_balance(circle)
        )

        required_payout = (
            circle.constitution.payout_amount
        )

        if required_payout > 0:

            funding_ratio = (
                treasury_balance
                / required_payout
            )

        else:

            funding_ratio = Decimal("1")

        if funding_ratio < Decimal("0.50"):

            signals.append({
                "type": "FUNDING_RISK",
                "severity": "high",
                "message": (
                    "Treasury holds less than 50% "
                    "of the required payout amount."
                ),
                "value": str(
                    round(funding_ratio * 100, 2)
                ),
            })

        elif funding_ratio < Decimal("1"):

            signals.append({
                "type": "FUNDING_RISK",
                "severity": "medium",
                "message": (
                    "Treasury is below the next "
                    "required payout amount."
                ),
                "value": str(
                    round(funding_ratio * 100, 2)
                ),
            })

        # --------------------------------------------------
        # TRUST NETWORK RISK
        # --------------------------------------------------

        trust_edges = (
            TrustGraphService.get_graph_for_circle(
                circle
            )
        )

        total_connections = trust_edges.count()

        successful_connections = (
            trust_edges.filter(
                successful_cycles_together__gt=0
            ).count()
        )

        if total_connections > 0:

            successful_ratio = (
                Decimal(successful_connections)
                / Decimal(total_connections)
            )

        else:

            successful_ratio = Decimal("1")

        if (
            total_connections >= 3
            and successful_ratio < Decimal("0.50")
        ):

            signals.append({
                "type": "NETWORK_RISK",
                "severity": "medium",
                "message": (
                    "A significant portion of the "
                    "circle's trust connections lack "
                    "successful cycle history."
                ),
                "value": str(
                    round(successful_ratio * 100, 2)
                ),
            })

        # --------------------------------------------------
        # OVERALL RISK
        # --------------------------------------------------

        high_risk_count = sum(
            1
            for signal in signals
            if signal["severity"] == "high"
        )

        medium_risk_count = sum(
            1
            for signal in signals
            if signal["severity"] == "medium"
        )

        if high_risk_count > 0:

            overall_risk = "high"

        elif medium_risk_count > 0:

            overall_risk = "medium"

        else:

            overall_risk = "low"

        return {
            "circle_id": str(circle.id),
            "overall_risk": overall_risk,
            "payment_rate": round(
                payment_rate * 100,
                2,
            ),
            "overdue_obligations": overdue_obligations,
            "treasury_balance": treasury_balance,
            "required_payout": required_payout,
            "total_obligations": total_obligations,
            "funding_ratio": round(
                funding_ratio,
                2,
            ),
            "trust_connections": total_connections,
            "successful_connections": (
                successful_connections
            ),
            "signals": signals,
        }