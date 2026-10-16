from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from finance.models import (
    ContributionObligation,
)

from circles.models import (
    CircleMembership,
    MembershipStatus,
)


class ObligationService:

    @staticmethod
    @transaction.atomic
    def create_period_obligations(
        *,
        circle,
        period_number,
    ):

        amount = circle.constitution.contribution_amount

        due = (
            timezone.now()
            + timedelta(days=7)
        )

        created = []

        members = CircleMembership.objects.filter(
            circle=circle,
            status=MembershipStatus.ACTIVE,
        )

        for membership in members:

            obligation, was_created = (
                ContributionObligation.objects.get_or_create(
                    circle=circle,
                    member=membership.user,
                    period_number=period_number,
                    defaults={
                        "amount_due": amount,
                        "due_date": due,
                    },
                )
            )

            if was_created:
                created.append(obligation)

        return created