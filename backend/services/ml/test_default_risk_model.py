import io
import re
import shutil
import tempfile
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from audit.models import AuditLog
from circles.models import (
    Circle,
    CircleMembership,
    CircleStatus,
    MembershipStatus,
)
from finance.models import (
    ContributionObligation,
    LedgerTransaction,
    ObligationStatus,
    Payout,
    PayoutVote,
)
from payments.models import Payment
from risk.models import (
    MemberRiskFeatureSnapshot,
    MemberRiskOutcome,
    RiskOutcomeType,
)
from trust.models import TrustEdge, TrustProfile

from services.ml.model_registry import (
    DEFAULT_MODEL_VERSION,
    ModelArtifactError,
    ModelArtifactNotFound,
    ModelRegistry,
)
from services.ml.predict_default_risk import DefaultRiskPredictor
from services.ml.train_default_model import (
    DefaultModelTrainer,
    InsufficientTrainingDataError,
)
from services.risk.dataset_builder import RiskDatasetBuilder
from services.risk.feature_snapshot_service import (
    RiskFeatureSnapshotService,
)
from services.risk.member_features import (
    MEMBER_DEFAULT_FEATURE_NAMES,
    MemberFeatureService,
    to_feature_vector,
)
from services.risk.outcome_service import RiskOutcomeService


User = get_user_model()

BASE_TIME = datetime(2026, 1, 1, tzinfo=dt_timezone.utc)

WRITE_SQL = re.compile(r"^\s*(INSERT|UPDATE|DELETE)\b", re.IGNORECASE)


class MLTestCase(TestCase):
    """Isolated model directory and a circle with one member per test."""

    def setUp(self):
        self.model_dir = Path(tempfile.mkdtemp(prefix="osusu-ml-test-"))
        self.addCleanup(shutil.rmtree, self.model_dir, ignore_errors=True)

        settings_override = override_settings(ML_MODEL_DIR=self.model_dir)
        settings_override.enable()
        self.addCleanup(settings_override.disable)

        self.user = User.objects.create_user(
            username="ml-member",
            email="ml-member@example.com",
            password="StrongPassword123!",
        )

        self.circle = Circle.objects.create(
            creator=self.user,
            name="ML Circle",
            description="Isolated ML test circle",
            status=CircleStatus.ACTIVE,
        )

        CircleMembership.objects.create(
            circle=self.circle,
            user=self.user,
            status=MembershipStatus.ACTIVE,
            constitution_accepted=True,
        )

    def add_labelled_snapshot(self, *, day, defaulted, created_at=None):
        """
        A historical snapshot plus its later-observed outcome. Defaulters
        get risky feature values so the classes are learnable.
        """
        if defaulted:
            values = dict(
                payment_rate=Decimal("0.4000"),
                overdue_rate=Decimal("0.6000") + Decimal(day % 3) / 10,
                late_payments=2 + day % 3,
                defaults=1 + day % 2,
                payments_made=1,
            )
        else:
            values = dict(
                payment_rate=Decimal("1.0000"),
                overdue_rate=Decimal("0.0000"),
                late_payments=0,
                defaults=0,
                payments_made=3 + day % 3,
            )

        snapshot = MemberRiskFeatureSnapshot.objects.create(
            circle=self.circle,
            member=self.user,
            completed_cycles=day % 2,
            votes_participated=day % 4,
            trust_connections=1,
            successful_trust_connections=0 if defaulted else 1,
            **values,
        )

        MemberRiskFeatureSnapshot.objects.filter(pk=snapshot.pk).update(
            created_at=created_at or BASE_TIME + timedelta(days=day),
        )
        snapshot.refresh_from_db()

        RiskOutcomeService.record(
            snapshot=snapshot,
            outcome_type=(
                RiskOutcomeType.DEFAULTED
                if defaulted
                else RiskOutcomeType.PAID_ON_TIME
            ),
        )

        return snapshot

    def add_history(self, count=10):
        # Alternating classes so both appear before and after the split.
        return [
            self.add_labelled_snapshot(day=day, defaulted=day % 2 == 0)
            for day in range(count)
        ]


class FeatureDefinitionTests(MLTestCase):

    def test_dataset_builder_uses_shared_feature_order(self):
        self.assertEqual(
            list(RiskDatasetBuilder.FEATURE_NAMES),
            list(MEMBER_DEFAULT_FEATURE_NAMES),
        )

    def test_vector_follows_feature_names_order(self):
        values = {
            name: index
            for index, name in enumerate(MEMBER_DEFAULT_FEATURE_NAMES)
        }

        # Insertion order must not matter; names decide the order.
        shuffled = dict(reversed(list(values.items())))

        self.assertEqual(
            to_feature_vector(shuffled),
            [float(i) for i in range(len(MEMBER_DEFAULT_FEATURE_NAMES))],
        )

    def test_vector_rejects_missing_features(self):
        values = {name: 0 for name in MEMBER_DEFAULT_FEATURE_NAMES}
        del values["defaults"]

        with self.assertRaises(ValueError):
            to_feature_vector(values)

    def test_dataset_rows_match_snapshot_attributes(self):
        snapshot = self.add_labelled_snapshot(day=0, defaulted=True)

        dataset = RiskDatasetBuilder.build_member_default_dataset()

        self.assertEqual(
            dataset.X[0],
            [
                float(getattr(snapshot, name))
                for name in MEMBER_DEFAULT_FEATURE_NAMES
            ],
        )

    def test_current_features_match_stored_snapshot(self):
        # Training/serving parity: prediction-time features must equal
        # what a snapshot stores for the same state, including the
        # 4-decimal rounding of rates (1/3 here).
        other = User.objects.create_user(
            username="ml-peer",
            email="ml-peer@example.com",
            password="StrongPassword123!",
        )
        CircleMembership.objects.create(
            circle=self.circle,
            user=other,
            status=MembershipStatus.ACTIVE,
            constitution_accepted=True,
        )
        TrustEdge.objects.create(
            inviter=self.user,
            invited=other,
            completed_together=1,
            successful_cycles_together=1,
        )
        TrustProfile.objects.create(user=self.user, votes_participated=4)

        for period, status in enumerate(
            [
                ObligationStatus.PAID,
                ObligationStatus.OVERDUE,
                ObligationStatus.PENDING,
            ],
            start=1,
        ):
            ContributionObligation.objects.create(
                circle=self.circle,
                member=self.user,
                period_number=period,
                amount_due=Decimal("50.00"),
                due_date=timezone.now(),
                status=status,
            )

        snapshot = RiskFeatureSnapshotService.create_member_snapshot(
            circle=self.circle,
            member=self.user,
        )
        snapshot.refresh_from_db()

        current = MemberFeatureService.compute_current(
            circle=self.circle,
            member=self.user,
        )

        self.assertEqual(current["payment_rate"], Decimal("0.3333"))
        self.assertEqual(
            to_feature_vector(current),
            to_feature_vector(snapshot),
        )

    def test_compute_current_is_read_only(self):
        with CaptureQueriesContext(connection) as queries:
            MemberFeatureService.compute_current(
                circle=self.circle,
                member=self.user,
            )

        writes = [q["sql"] for q in queries if WRITE_SQL.match(q["sql"])]
        self.assertEqual(writes, [])
        self.assertFalse(TrustProfile.objects.exists())


class TrainingValidationTests(MLTestCase):

    def test_empty_history_fails_clearly(self):
        with self.assertRaisesMessage(
            InsufficientTrainingDataError,
            "No labelled history",
        ):
            DefaultModelTrainer.train()

        self.assertFalse(
            ModelRegistry.artifact_path(DEFAULT_MODEL_VERSION).exists()
        )

    def test_single_class_history_fails_clearly(self):
        for day in range(10):
            self.add_labelled_snapshot(day=day, defaulted=False)

        with self.assertRaisesMessage(
            InsufficientTrainingDataError,
            "DEFAULTED (1)",
        ):
            DefaultModelTrainer.train()

    def test_empty_test_period_fails_when_evaluation_required(self):
        same_time = BASE_TIME
        for day in range(6):
            self.add_labelled_snapshot(
                day=day,
                defaulted=day % 2 == 0,
                created_at=same_time,
            )

        with self.assertRaisesMessage(
            InsufficientTrainingDataError,
            "empty test set",
        ):
            DefaultModelTrainer.train()

        result = DefaultModelTrainer.train(require_evaluation=False)

        self.assertEqual(result.test_size, 0)
        self.assertEqual(result.metrics, {})

    def test_snapshots_without_later_outcomes_are_not_training_data(self):
        snapshot = MemberRiskFeatureSnapshot.objects.create(
            circle=self.circle,
            member=self.user,
        )
        MemberRiskOutcome.objects.create(
            snapshot=snapshot,
            circle=self.circle,
            member=self.user,
            outcome_type=RiskOutcomeType.DEFAULTED,
            observed_at=snapshot.created_at,
        )

        with self.assertRaises(InsufficientTrainingDataError):
            DefaultModelTrainer.train()

    def test_management_command_reports_insufficient_data(self):
        with self.assertRaisesMessage(CommandError, "Cannot train"):
            call_command("train_default_model")


class TrainingTests(MLTestCase):

    def test_trains_time_aware_and_writes_artifact(self):
        self.add_history(10)

        result = DefaultModelTrainer.train()

        self.assertEqual(result.model_version, "logistic-default-v1")
        self.assertEqual(result.train_size, 8)
        self.assertEqual(result.test_size, 2)
        self.assertEqual(
            result.split_timestamp,
            BASE_TIME + timedelta(days=8),
        )
        self.assertEqual(
            result.artifact_path,
            self.model_dir / "logistic-default-v1.joblib",
        )
        self.assertTrue(result.artifact_path.exists())

        for key in (
            "accuracy",
            "precision",
            "recall",
            "brier_score",
            "log_loss",
            "roc_auc",
        ):
            self.assertIn(key, result.metrics)

    def test_artifact_contents(self):
        self.add_history(10)
        DefaultModelTrainer.train()

        artifact = ModelRegistry.load()

        self.assertEqual(artifact.model_version, DEFAULT_MODEL_VERSION)
        self.assertEqual(
            artifact.feature_names,
            list(MEMBER_DEFAULT_FEATURE_NAMES),
        )
        self.assertEqual(artifact.feature_version, "features-v1")
        self.assertIsInstance(artifact.pipeline, Pipeline)
        self.assertIsInstance(
            artifact.pipeline.named_steps["scaler"],
            StandardScaler,
        )
        self.assertIsInstance(
            artifact.pipeline.named_steps["classifier"],
            LogisticRegression,
        )
        self.assertEqual(
            artifact.pipeline.n_features_in_,
            len(MEMBER_DEFAULT_FEATURE_NAMES),
        )
        self.assertEqual(artifact.train_size, 8)

    def test_no_temporary_files_left_behind(self):
        self.add_history(10)
        DefaultModelTrainer.train()

        self.assertEqual(
            sorted(p.name for p in self.model_dir.iterdir()),
            ["logistic-default-v1.joblib"],
        )

    def test_management_command_trains_model(self):
        self.add_history(10)

        output = io.StringIO()
        call_command("train_default_model", stdout=output)

        self.assertIn("Trained logistic-default-v1", output.getvalue())
        self.assertTrue(
            ModelRegistry.artifact_path(DEFAULT_MODEL_VERSION).exists()
        )

    def test_invalid_model_version_is_rejected(self):
        for version in ("../escape", "Upper", "", "a/b"):
            with self.subTest(version=version):
                with self.assertRaises(ValueError):
                    ModelRegistry.artifact_path(version)


class PredictionTests(MLTestCase):

    def train(self):
        self.add_history(10)
        DefaultModelTrainer.train()

    def add_obligations(self, member, statuses):
        for period, status in enumerate(statuses, start=1):
            ContributionObligation.objects.create(
                circle=self.circle,
                member=member,
                period_number=period,
                amount_due=Decimal("50.00"),
                due_date=timezone.now(),
                status=status,
            )

    def test_prediction_output_structure(self):
        self.train()

        prediction = DefaultRiskPredictor.predict(
            circle=self.circle,
            member=self.user,
        )

        self.assertEqual(prediction["member_id"], str(self.user.id))
        self.assertEqual(prediction["circle_id"], str(self.circle.id))
        self.assertEqual(
            prediction["model_version"],
            "logistic-default-v1",
        )
        self.assertTrue(prediction["informational_only"])
        self.assertIsInstance(prediction["default_probability"], float)
        self.assertEqual(
            list(prediction["features"]),
            list(MEMBER_DEFAULT_FEATURE_NAMES),
        )

    def test_probability_is_between_zero_and_one(self):
        self.train()

        probability = DefaultRiskPredictor.predict(
            circle=self.circle,
            member=self.user,
        )["default_probability"]

        self.assertGreaterEqual(probability, 0.0)
        self.assertLessEqual(probability, 1.0)

    def test_riskier_member_gets_higher_probability(self):
        self.train()

        reliable = User.objects.create_user(
            username="reliable",
            email="reliable@example.com",
            password="StrongPassword123!",
        )
        risky = User.objects.create_user(
            username="risky",
            email="risky@example.com",
            password="StrongPassword123!",
        )
        self.add_obligations(reliable, [ObligationStatus.PAID] * 3)
        self.add_obligations(risky, [ObligationStatus.OVERDUE] * 3)

        reliable_p = DefaultRiskPredictor.predict(
            circle=self.circle,
            member=reliable,
        )["default_probability"]
        risky_p = DefaultRiskPredictor.predict(
            circle=self.circle,
            member=risky,
        )["default_probability"]

        self.assertGreater(risky_p, reliable_p)

    def test_missing_model_fails_clearly(self):
        with self.assertRaisesMessage(
            ModelArtifactNotFound,
            "train_default_model",
        ):
            DefaultRiskPredictor.predict(
                circle=self.circle,
                member=self.user,
            )

    def test_incompatible_feature_definition_is_rejected(self):
        self.train()

        artifact = ModelRegistry.load()
        artifact.feature_names = list(reversed(artifact.feature_names))
        ModelRegistry.save(artifact)

        with self.assertRaises(ModelArtifactError):
            DefaultRiskPredictor.predict(
                circle=self.circle,
                member=self.user,
            )

    def test_prediction_has_no_financial_or_database_side_effects(self):
        self.train()
        self.add_obligations(
            self.user,
            [ObligationStatus.PAID, ObligationStatus.OVERDUE],
        )

        watched = [
            LedgerTransaction,
            Payout,
            PayoutVote,
            ContributionObligation,
            Payment,
            AuditLog,
            TrustProfile,
            MemberRiskFeatureSnapshot,
            MemberRiskOutcome,
        ]
        before = {m: m.objects.count() for m in watched}
        obligation_states = list(
            ContributionObligation.objects
            .order_by("period_number")
            .values_list("status", "amount_due")
        )

        with CaptureQueriesContext(connection) as queries:
            DefaultRiskPredictor.predict(
                circle=self.circle,
                member=self.user,
            )

        writes = [q["sql"] for q in queries if WRITE_SQL.match(q["sql"])]
        self.assertEqual(writes, [])

        self.assertEqual(
            {m: m.objects.count() for m in watched},
            before,
        )
        self.assertEqual(
            list(
                ContributionObligation.objects
                .order_by("period_number")
                .values_list("status", "amount_due")
            ),
            obligation_states,
        )
