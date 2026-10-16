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

from finance.models import (
    ContributionObligation,
    ObligationStatus,
)

from risk.models import MemberRiskFeatureSnapshot

from services.risk.feature_snapshot_service import (
    RiskFeatureSnapshotService,
)

from trust.models import TrustEdge


User = get_user_model()


class RiskFeatureSnapshotServiceTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="daniel",
            email="daniel@example.com",
            password="StrongPassword123!",
        )

        self.other_user = User.objects.create_user(
            username="other",
            email="other@example.com",
            password="StrongPassword123!",
        )

        self.circle = Circle.objects.create(
            creator=self.user,
            name="Risk Test Circle",
            description="Risk snapshot test",
            status=CircleStatus.ACTIVE,
        )

        CircleConstitution.objects.create(
            circle=self.circle,
            member_limit=2,
            contribution_amount=Decimal("50.00"),
            contribution_frequency="weekly",
            payout_amount=Decimal("100.00"),
            payout_frequency="biweekly",
            cycle_length=2,
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

        CircleMembership.objects.create(
            circle=self.circle,
            user=self.other_user,
            status=MembershipStatus.ACTIVE,
            constitution_accepted=True,
        )

    def test_creates_member_feature_snapshot(self):

        ContributionObligation.objects.create(
            circle=self.circle,
            member=self.user,
            period_number=1,
            amount_due=Decimal("50.00"),
            due_date=self.circle.created_at,
            status=ObligationStatus.PAID,
        )

        TrustEdge.objects.create(
            inviter=self.user,
            invited=self.other_user,
            completed_together=1,
            successful_cycles_together=1,
        )

        snapshot = (
            RiskFeatureSnapshotService.create_member_snapshot(
                circle=self.circle,
                member=self.user,
                snapshot_period=1,
            )
        )

        self.assertIsNotNone(snapshot)

        self.assertEqual(
            snapshot.circle,
            self.circle,
        )

        self.assertEqual(
            snapshot.member,
            self.user,
        )

        self.assertEqual(
            snapshot.payment_rate,
            Decimal("1"),
        )

        self.assertEqual(
            snapshot.overdue_rate,
            Decimal("0"),
        )

        self.assertEqual(
            snapshot.payments_made,
            1,
        )

        self.assertEqual(
            snapshot.trust_connections,
            1,
        )

        self.assertEqual(
            snapshot.successful_trust_connections,
            1,
        )

        self.assertEqual(
            snapshot.snapshot_period,
            1,
        )

        self.assertEqual(
            snapshot.feature_version,
            "features-v1",
        )

        self.assertEqual(
            MemberRiskFeatureSnapshot.objects.count(),
            1,
        )