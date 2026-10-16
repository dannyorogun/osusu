from trust.models import TrustEdge
from services.trust.trust_graph_service import (
    TrustGraphService,
)


class TrustGraphStats:

    @staticmethod
    def user_summary(user):

        invited_count = TrustEdge.objects.filter(
            inviter=user,
        ).count()

        invited_by_count = TrustEdge.objects.filter(
            invited=user,
        ).count()

        successful_connections = (
            TrustEdge.objects.filter(
                inviter=user,
                successful_cycles_together__gt=0,
            ).count()
        )

        return {
            "invited_count": invited_count,
            "invited_by_count": invited_by_count,
            "successful_connections": (
                successful_connections
            ),
        }

    @staticmethod
    def circle_summary(circle):

        edges = TrustGraphService.get_graph_for_circle(
            circle
        )

        return {
            "connections": edges.count(),
            "successful_connections": (
                edges.filter(
                    successful_cycles_together__gt=0
                ).count()
            ),
        }