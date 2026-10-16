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

from risk.models import RiskOutcomeType

from services.risk.dataset_builder import (
    RiskDatasetBuilder,
)

from services.risk.feature_snapshot_service import (
    RiskFeatureSnapshotService,
)

from services.risk.outcome_service import (
    RiskOutcomeService,
)


User = get_user_model()


class RiskDatasetBuilderTests(TestCase):

    def setUp(self):

        self.user = User.objects.create_user(
            username="daniel",
            email="daniel@example.com",
            password="StrongPassword123!",
        )

        self.circle = Circle.objects.create(
            creator=self.user,
            name="ML Test Circle",
            description="Dataset testing",
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

    def test_builds_default_dataset(self):

        snapshot = (
            RiskFeatureSnapshotService.create_member_snapshot(
                circle=self.circle,
                member=self.user,
                snapshot_period=1,
            )
        )

        RiskOutcomeService.record(
            snapshot=snapshot,
            outcome_type=RiskOutcomeType.DEFAULTED,
            outcome_period=2,
        )

        dataset = (
            RiskDatasetBuilder
            .build_member_default_dataset()
        )

        self.assertEqual(
            len(dataset.X),
            1,
        )

        self.assertEqual(
            len(dataset.y),
            1,
        )

        self.assertEqual(
            dataset.y[0],
            1,
        )

        self.assertEqual(
            len(dataset.X[0]),
            9,
        )

        self.assertEqual(
            dataset.snapshot_ids[0],
            str(snapshot.id),
        )

    def test_ignores_snapshots_without_outcomes(self):

        RiskFeatureSnapshotService.create_member_snapshot(
            circle=self.circle,
            member=self.user,
            snapshot_period=1,
        )

        dataset = (
            RiskDatasetBuilder
            .build_member_default_dataset()
        )

        self.assertEqual(
            len(dataset.X),
            0,
        )

        self.assertEqual(
            len(dataset.y),
            0,
        )