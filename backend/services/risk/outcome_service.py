from django.db import transaction

from risk.models import (
    MemberRiskOutcome,
    RiskOutcomeType,
)


class RiskOutcomeService:

    @staticmethod
    @transaction.atomic
    def record(
        *,
        snapshot,
        outcome_type,
        outcome_period=None,
        metadata=None,
    ):
        outcome, created = (
            MemberRiskOutcome.objects.get_or_create(
                snapshot=snapshot,
                outcome_type=outcome_type,
                defaults={
                    "circle": snapshot.circle,
                    "member": snapshot.member,
                    "outcome_period": outcome_period,
                    "metadata": metadata or {},
                    "outcome_version": "outcomes-v1",
                },
            )
        )

        return outcome