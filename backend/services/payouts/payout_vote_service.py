from django.db import transaction

from finance.models import (
    Payout,
    PayoutStatus,
    PayoutVote,
)

from services.audit.audit_service import AuditService
from services.circles.eligibility_engine import (
    EligibilityEngine,
)


class PayoutVoteService:

    @staticmethod
    @transaction.atomic
    def cast_vote(
        *,
        payout,
        voter,
    ):
        """
        One vote per eligible member per payout window, for a PENDING
        candidate only. Voting again for the same candidate is a no-op;
        voting for a different candidate in the same window is refused.
        """

        # Lock the whole window (in a fixed order) so two concurrent votes
        # by one member for different candidates cannot both succeed.
        window = list(
            Payout.objects
            .select_for_update()
            .filter(
                circle_id=payout.circle_id,
                payout_window=payout.payout_window,
            )
            .order_by("id")
        )
        payout = next(p for p in window if p.pk == payout.pk)

        if payout.status != PayoutStatus.PENDING:
            raise ValueError(
                "Voting for this payout window has closed."
            )

        eligible = EligibilityEngine.eligible_members(
            payout.circle
        )

        if voter not in eligible:
            raise ValueError(
                "Only eligible members can vote."
            )

        existing = (
            PayoutVote.objects
            .filter(
                payout__in=window,
                member=voter,
            )
            .first()
        )

        if existing is not None:
            if existing.payout_id == payout.pk:
                return payout
            raise ValueError(
                "You have already voted in this payout window."
            )

        PayoutVote.objects.create(
            payout=payout,
            member=voter,
        )

        AuditService.record(
            action="PAYOUT_VOTE_CAST",
            entity_type="Payout",
            entity_id=payout.id,
            user=voter,
            metadata={"window": payout.payout_window},
        )

        return payout
