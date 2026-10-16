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


class RiskFeatureEngine:

    @staticmethod
    def build_circle_features(circle):

        obligations = ContributionObligation.objects.filter(
            circle=circle,
        )

        total = obligations.count()

        paid = obligations.filter(
            status=ObligationStatus.PAID,
        ).count()

        overdue = obligations.filter(
            status=ObligationStatus.OVERDUE,
        ).count()

        if total > 0:

            payment_rate = (
                Decimal(paid)
                / Decimal(total)
            )

            overdue_rate = (
                Decimal(overdue)
                / Decimal(total)
            )

        else:

            payment_rate = Decimal("1")
            overdue_rate = Decimal("0")

        treasury = TreasuryEngine.current_balance(
            circle
        )

        required_payout = (
            circle.constitution.payout_amount
        )

        if required_payout > 0:

            funding_ratio = (
                treasury / required_payout
            )

        else:

            funding_ratio = Decimal("1")

        trust_edges = (
            TrustGraphService.get_graph_for_circle(
                circle
            )
        )

        connections = trust_edges.count()

        successful_connections = (
            trust_edges.filter(
                successful_cycles_together__gt=0
            ).count()
        )

        if connections > 0:

            successful_connection_ratio = (
                Decimal(successful_connections)
                / Decimal(connections)
            )

        else:

            successful_connection_ratio = Decimal("1")

        return {
            "payment_rate": float(
                payment_rate
            ),

            "overdue_rate": float(
                overdue_rate
            ),

            "funding_ratio": float(
                funding_ratio
            ),

            "trust_connections": connections,

            "successful_connection_ratio": float(
                successful_connection_ratio
            ),
        }