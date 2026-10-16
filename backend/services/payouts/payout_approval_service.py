from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from finance.models import (
    DECIDED_PAYOUT_STATUSES,
    Payout,
    PayoutStatus,
    PayoutVote,
)

from services.audit.audit_service import AuditService
from services.circles.eligibility_engine import EligibilityEngine


DECIDED_STATUSES = DECIDED_PAYOUT_STATUSES


def required_votes(circle):
    """
    Votes needed to decide a window: the constitution's quorum
    percentage of currently eligible voters, rounded up, at least one.
    """
    eligible = len(EligibilityEngine.eligible_members(circle))
    quorum = circle.constitution.quorum_percentage
    return max(1, -(-eligible * quorum // 100))


class PayoutApprovalService:

    @staticmethod
    @transaction.atomic
    def approve(circle, payout_window):
        """
        Decide a payout window: the PENDING candidate with the most votes
        (ties: the earliest-created candidate) becomes APPROVED and every
        other PENDING candidate becomes CANCELLED, atomically.

        Idempotent: an already-decided window returns its recipient
        unchanged. Refused until the constitution's quorum is reached.
        Only PENDING rows are ever cancelled; decided payouts are never
        touched.
        """

        # Lock the window first (no GROUP BY: Postgres refuses FOR UPDATE
        # with aggregates), then count votes in a separate query.
        rows = list(
            Payout.objects
            .select_for_update()
            .filter(
                circle=circle,
                payout_window=payout_window,
            )
            .order_by("id")
        )

        if not rows:
            raise ValueError(
                "No payout candidates exist."
            )

        decided = [r for r in rows if r.status in DECIDED_STATUSES]

        if decided:
            return decided[0]

        pending_ids = [
            r.pk for r in rows if r.status == PayoutStatus.PENDING
        ]

        if not pending_ids:
            raise ValueError(
                "This payout window has no open candidates."
            )

        votes = PayoutVote.objects.filter(
            payout_id__in=pending_ids
        ).count()

        needed = required_votes(circle)

        if votes < needed:
            raise ValueError(
                f"Quorum not reached: {votes} of {needed} required votes."
            )

        winner = (
            Payout.objects
            .filter(pk__in=pending_ids)
            .annotate(vote_count=Count("votes"))
            .order_by("-vote_count", "created_at")
            .first()
        )

        winner = next(r for r in rows if r.pk == winner.pk)
        winner.status = PayoutStatus.APPROVED
        winner.approved_at = timezone.now()

        winner.save(
            update_fields=[
                "status",
                "approved_at",
            ]
        )

        cancelled = (
            Payout.objects
            .filter(
                pk__in=pending_ids,
                status=PayoutStatus.PENDING,
            )
            .exclude(pk=winner.pk)
            .update(status=PayoutStatus.CANCELLED)
        )

        AuditService.record(
            action="PAYOUT_APPROVED",
            entity_type="Payout",
            entity_id=winner.id,
            user=winner.member,
            metadata={
                "window": payout_window,
                "votes": votes,
                "required_votes": needed,
                "cancelled_candidates": cancelled,
            },
        )

        return winner
