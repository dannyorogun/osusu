from circles.models import (
    RestructureStatus,
)


class RestructureResultService:

    @staticmethod
    def evaluate(restructure):

        votes = restructure.votes.all()

        total = votes.count()

        yes = votes.filter(
            approved=True
        ).count()

        if total == 0:
            return False

        percentage = (
            yes
            / total
        ) * 100

        if percentage >= restructure.circle.constitution.quorum_percentage:

            restructure.status = (
                RestructureStatus.APPROVED
            )

            restructure.save()

            return True

        return False