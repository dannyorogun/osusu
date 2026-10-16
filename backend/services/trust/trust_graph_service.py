from django.db import transaction

from circles.models import CircleMembership
from trust.models import TrustEdge


class TrustGraphService:

    @staticmethod
    @transaction.atomic
    def create_edge(*, inviter, invited):
        """
        Create a trust relationship between the person
        who invited a member and the invited member.

        If the relationship already exists, return it.
        """

        if inviter == invited:
            raise ValueError(
                "A user cannot create a trust edge to themselves."
            )

        edge, _ = TrustEdge.objects.get_or_create(
            inviter=inviter,
            invited=invited,
        )

        return edge

    @staticmethod
    @transaction.atomic
    def record_cycle_together(
        *,
        inviter,
        invited,
    ):
        """
        Record that two connected members successfully
        participated in another cycle together.
        """

        edge = (
            TrustEdge.objects
            .select_for_update()
            .filter(
                inviter=inviter,
                invited=invited,
            )
            .first()
        )

        if edge is None:
            edge = TrustGraphService.create_edge(
                inviter=inviter,
                invited=invited,
            )

        edge.completed_together += 1
        edge.successful_cycles_together += 1

        edge.save(
            update_fields=[
                "completed_together",
                "successful_cycles_together",
                "updated_at",
            ]
        )

        return edge

    @staticmethod
    def get_user_connections(user):
        """
        Return the people directly connected to a user.
        """

        outgoing = (
            TrustEdge.objects
            .filter(inviter=user)
            .select_related("invited")
        )

        incoming = (
            TrustEdge.objects
            .filter(invited=user)
            .select_related("inviter")
        )

        return {
            "outgoing": outgoing,
            "incoming": incoming,
        }

    @staticmethod
    def get_graph_for_circle(circle):
        """
        Return trust relationships between members
        of a specific circle.
        """

        member_ids = CircleMembership.objects.filter(
            circle=circle,
        ).values_list(
            "user_id",
            flat=True,
        )

        return TrustEdge.objects.filter(
            inviter_id__in=member_ids,
            invited_id__in=member_ids,
        ).select_related(
            "inviter",
            "invited",
        )