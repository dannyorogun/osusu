from circles.models import (
    RestructureVote,
    RestructureStatus,
)

from services.circles.eligibility_engine import (
    EligibilityEngine
)


class RestructureVoteService:

    @staticmethod
    def vote(
        *,
        restructure,
        member,
        approved,
    ):

        if restructure.status != RestructureStatus.VOTING:
            raise ValueError(
                "Voting has ended."
            )

        eligible = EligibilityEngine.eligible_members(
            restructure.circle
        )

        if member not in eligible:
            raise ValueError(
                "Member is not eligible to vote."
            )

        vote, created = (
            RestructureVote.objects.get_or_create(
                restructure=restructure,
                member=member,
                defaults={
                    "approved": approved,
                },
            )
        )

        if not created:
            vote.approved = approved
            vote.save()

        return vote