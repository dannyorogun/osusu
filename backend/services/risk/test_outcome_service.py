from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from circles.models import (
    Circle,
    CircleConstitution,
    CircleMembership,
    MembershipStatus,
    CircleStatus,
)

from risk.models import (
    MemberRiskOutcome,
    RiskOutcomeType,
)

from services.risk.feature_snapshot_service import (
    RiskFeatureSnapshotService,
)

from services.risk.outcome_service import (
    RiskOutcomeService,
)


User = get_user_model()


class RiskOutcomeServiceTests(TestCase):

    def setUp(self):

        self.user = User.objects.create_user(
            username="daniel",
            email="daniel@example.com",
            password="StrongPassword123!",
        )

        self.circle = Circle.objects.create(
            creator=self.user,
            name="Outcome Test Circle",
            description="Outcome testing",
            status=CircleStatus.ACTIVE,
        )

        CircleConstitution.objects.create(
            circle=self.circle,
            member_limit=1,
            contribution_amount=Decimal("50.00"),
            contribution_frequency="weekly",
            payout_amount=Decimal("50.00"),
            payout_frequency="weekly",
            cycle_length=1,
            quorum_percentage=50,
            grace_period_days=7,
            reserve_enabled=False,
            reserve_amount=Decimal("0.00"),
            allow_replacement_before_lock=True,
        )

        CircleMembership.objects.create(
            circle=self.circle,
            user=self.user,
            status=MembershipStatus.ACTIVE,
            constitution_accepted=True,
        )

        self.snapshot = (
            RiskFeatureSnapshotService.create_member_snapshot(
                circle=self.circle,
                member=self.user,
                snapshot_period=1,
            )
        )

    def test_records_outcome(self):

        outcome = RiskOutcomeService.record(
            snapshot=self.snapshot,
            outcome_type=RiskOutcomeType.PAID_LATE,
            outcome_period=2,
            metadata={
                "days_late": 3,
            },
        )

        self.assertIsNotNone(outcome)

        self.assertEqual(
            outcome.snapshot,
            self.snapshot,
        )

        self.assertEqual(
            outcome.circle,
            self.circle,
        )

        self.assertEqual(
            outcome.member,
            self.user,
        )

        self.assertEqual(
            outcome.outcome_type,
            RiskOutcomeType.PAID_LATE,
        )

        self.assertEqual(
            outcome.outcome_period,
            2,
        )

        self.assertEqual(
            outcome.metadata["days_late"],
            3,
        )

        self.assertEqual(
            MemberRiskOutcome.objects.count(),
            1,
        )

    def test_duplicate_outcome_is_idempotent(self):

        first = RiskOutcomeService.record(
            snapshot=self.snapshot,
            outcome_type=RiskOutcomeType.DEFAULTED,
            outcome_period=2,
        )

        second = RiskOutcomeService.record(
            snapshot=self.snapshot,
            outcome_type=RiskOutcomeType.DEFAULTED,
            outcome_period=2,
        )

        self.assertEqual(
            first.id,
            second.id,
        )

        self.assertEqual(
            MemberRiskOutcome.objects.count(),
            1,
        )