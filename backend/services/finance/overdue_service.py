from django.utils import timezone

from finance.models import (
    ContributionObligation,
    ObligationStatus,
)


class OverdueService:

    @staticmethod
    def update(circle):

        overdue = ContributionObligation.objects.filter(
            circle=circle,
            status=ObligationStatus.PENDING,
            due_date__lt=timezone.now(),
        )

        count = overdue.update(
            status=ObligationStatus.OVERDUE
        )

        return count