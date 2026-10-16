from django.db import transaction

from risk.models import MemberRiskFeatureSnapshot

from services.risk.member_risk_engine import (
    MemberRiskEngine,
)

from services.trust.trust_graph_service import (
    TrustGraphService,
)


class RiskFeatureSnapshotService:

    @staticmethod
    @transaction.atomic
    def create_member_snapshot(
        *,
        circle,
        member,
        snapshot_period=None,
        prediction_horizon_periods=1,
):
        result = MemberRiskEngine.analyze_member(
            circle=circle,
            member=member,
        )

        trust_edges = TrustGraphService.get_graph_for_circle(
            circle
        )

        member_connections = trust_edges.filter(
            inviter=member
            ) | trust_edges.filter(
            invited=member
)

        trust_connections = member_connections.count()

        successful_trust_connections = (
            member_connections.filter(
                successful_cycles_together__gt=0
            ).count()
        )

        snapshot = MemberRiskFeatureSnapshot.objects.create(
            circle=circle,
            member=member,

            payment_rate=result["payment_rate"],
            overdue_rate=result["overdue_rate"],

            completed_cycles=result["completed_cycles"],
            payments_made=result["payments_made"],
            late_payments=result["late_payments"],
            defaults=result["defaults"],
            votes_participated=result["votes_participated"],

            trust_connections=trust_connections,
            successful_trust_connections=(
                successful_trust_connections
            ),

            snapshot_period=snapshot_period,
            prediction_horizon_periods=prediction_horizon_periods,
            feature_version="features-v1",
        )

        return snapshot