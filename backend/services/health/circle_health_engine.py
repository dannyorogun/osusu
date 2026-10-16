from decimal import Decimal

from circles.models import (
    CircleMembership,
    MembershipStatus,
)

from finance.models import (
    ContributionObligation,
    ObligationStatus,
)

from services.finance.treasury_engine import (
    TreasuryEngine,
)

from services.payouts.treasury_guard import (
    TreasuryGuard,
)

from services.trust.trust_graph_service import (
    TrustGraphService,
)


class CircleHealthEngine:

    @staticmethod
    def calculate(circle):

        constitution = circle.constitution

        members = CircleMembership.objects.filter(
            circle=circle,
            status=MembershipStatus.ACTIVE,
        )

        member_count = members.count()

        obligations = ContributionObligation.objects.filter(
            circle=circle,
        )

        total_obligations = obligations.count()

        paid_obligations = obligations.filter(
            status=ObligationStatus.PAID,
        ).count()

        overdue_obligations = obligations.filter(
            status=ObligationStatus.OVERDUE,
        ).count()

        if total_obligations > 0:
            payment_rate = (
                Decimal(paid_obligations)
                / Decimal(total_obligations)
            )
        else:
            payment_rate = Decimal("1")

        treasury_balance = (
            TreasuryEngine.current_balance(circle)
        )

        required_payout = constitution.payout_amount

        if required_payout > 0:
            funding_ratio = (
                treasury_balance
                / required_payout
            )
        else:
            funding_ratio = Decimal("1")

        trust_edges = (
            TrustGraphService.get_graph_for_circle(
                circle
            )
        )

        trust_connections = trust_edges.count()

        successful_connections = (
            trust_edges.filter(
                successful_cycles_together__gt=0
            ).count()
        )

        if trust_connections > 0:
            trust_health = (
                Decimal(successful_connections)
                / Decimal(trust_connections)
            )
        else:
            trust_health = Decimal("1")

        health_score = (
            payment_rate * Decimal("40")
            + min(funding_ratio, Decimal("1"))
            * Decimal("40")
            + trust_health * Decimal("20")
        )

        health_score = min(
            health_score,
            Decimal("100"),
        )

        if health_score >= Decimal("80"):
            status = "healthy"
        elif health_score >= Decimal("60"):
            status = "watch"
        else:
            status = "at_risk"

        return {
            "circle_id": str(circle.id),
            "member_count": member_count,
            "payment_rate": round(
                payment_rate * Decimal("100"),
                2,
            ),
            "overdue_obligations": overdue_obligations,
            "treasury_balance": treasury_balance,
            "required_payout": required_payout,
            "funding_ratio": round(
                funding_ratio,
                2,
            ),
            "trust_connections": trust_connections,
            "successful_connections": (
                successful_connections
            ),
            "trust_health": round(
                trust_health * Decimal("100"),
                2,
            ),
            "health_score": round(
                health_score,
                2,
            ),
            "status": status,
        }