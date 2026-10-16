import ast
import inspect
import uuid

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

import risk.views
import services.ml.predict_default_risk
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
    Payout,
    PayoutVote,
)
from payments.models import Payment
from risk.models import (
    MemberRiskAssessment,
    MemberRiskFeatureSnapshot,
    MemberRiskOutcome,
    RiskAssessment,
)
from trust.models import TrustProfile

from services.ml.model_registry import ModelRegistry
from services.ml.predict_default_risk import DefaultRiskPredictor
from services.ml.test_default_risk_model import WRITE_SQL, MLTestCase
from services.ml.train_default_model import DefaultModelTrainer
from services.risk.member_features import MEMBER_DEFAULT_FEATURE_NAMES


User = get_user_model()


class MemberDefaultRiskAPITests(MLTestCase):
    """
    MLTestCase provides: an isolated ML_MODEL_DIR, self.user as an ACTIVE
    member of self.circle, and add_history() for labelled training data.
    """

    def setUp(self):
        super().setUp()

        self.client = APIClient()

        self.peer = self.make_user("peer")
        self.add_membership(self.circle, self.peer, MembershipStatus.ACTIVE)

        self.outsider = self.make_user("outsider")

        self.other_circle = Circle.objects.create(
            creator=self.outsider,
            name="Other Circle",
            description="Unrelated circle",
            status=CircleStatus.ACTIVE,
        )
        self.add_membership(
            self.other_circle,
            self.outsider,
            MembershipStatus.ACTIVE,
        )

    # Helpers

    def make_user(self, name):
        return User.objects.create_user(
            username=name,
            email=f"{name}@example.com",
            password="StrongPassword123!",
        )

    def add_membership(self, circle, user, membership_status):
        return CircleMembership.objects.create(
            circle=circle,
            user=user,
            status=membership_status,
            constitution_accepted=True,
        )

    def authenticate(self, user):
        token = RefreshToken.for_user(user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def url(self, circle_id, member_id):
        return reverse(
            "member-default-risk",
            kwargs={"circle_id": circle_id, "member_id": member_id},
        )

    def get(self, circle_id=None, member_id=None):
        return self.client.get(
            self.url(
                circle_id or self.circle.id,
                member_id or self.user.id,
            )
        )

    def train_model(self):
        self.add_history(10)
        DefaultModelTrainer.train()

    # Authentication

    def test_unauthenticated_request_is_rejected(self):
        self.train_model()

        response = self.get()

        self.assertEqual(response.status_code, 401)
        self.assertNotIn("default_probability", response.data)

    def test_invalid_token_is_rejected(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer not-a-token")

        response = self.get()

        self.assertEqual(response.status_code, 401)

    # Successful prediction

    def test_active_member_gets_prediction(self):
        self.train_model()
        self.authenticate(self.user)

        response = self.get()

        self.assertEqual(response.status_code, 200)
        data = response.data

        self.assertEqual(data["member_id"], str(self.user.id))
        self.assertEqual(data["circle_id"], str(self.circle.id))
        self.assertIs(data["informational_only"], True)
        self.assertEqual(data["model_version"], "logistic-default-v1")
        self.assertEqual(data["feature_version"], "features-v1")

    def test_probability_is_between_zero_and_one(self):
        self.train_model()
        self.authenticate(self.user)

        probability = self.get().data["default_probability"]

        self.assertIsInstance(probability, float)
        self.assertGreaterEqual(probability, 0.0)
        self.assertLessEqual(probability, 1.0)

    def test_response_contains_no_decision_labels(self):
        self.train_model()
        self.authenticate(self.user)

        data = self.get().data

        self.assertEqual(
            set(data),
            {
                "member_id",
                "circle_id",
                "default_probability",
                "model_version",
                "feature_version",
                "informational_only",
            },
        )

    def test_response_does_not_expose_member_features(self):
        # Several features summarize the target's history in OTHER
        # circles; peers must not see them, even for an active target.
        self.train_model()
        self.authenticate(self.user)

        response = self.get(member_id=self.peer.id)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("features", response.data)

        body = response.content.decode()
        for name in MEMBER_DEFAULT_FEATURE_NAMES:
            with self.subTest(feature=name):
                self.assertNotIn(name, body)

    def test_predictor_still_uses_features_internally(self):
        # Privacy is enforced at the API boundary only; the model input
        # is unchanged.
        self.train_model()

        prediction = DefaultRiskPredictor.predict(
            circle=self.circle,
            member=self.peer,
        )

        self.assertEqual(
            list(prediction["features"]),
            list(MEMBER_DEFAULT_FEATURE_NAMES),
        )

    def test_member_can_view_another_active_member(self):
        self.train_model()
        self.authenticate(self.user)

        response = self.get(member_id=self.peer.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["member_id"], str(self.peer.id))

    # Authorization

    def test_non_member_cannot_view_circle(self):
        self.train_model()
        self.authenticate(self.outsider)

        response = self.get()

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["detail"], "Circle not found.")

    def test_non_member_response_matches_nonexistent_circle(self):
        self.authenticate(self.outsider)

        not_member = self.get()
        missing = self.get(circle_id=uuid.uuid4())

        self.assertEqual(missing.status_code, 404)
        self.assertEqual(
            (not_member.status_code, not_member.data),
            (missing.status_code, missing.data),
        )

    def test_inactive_requester_membership_is_forbidden(self):
        self.train_model()
        requester = self.make_user("inactive")
        membership = self.add_membership(
            self.circle,
            requester,
            MembershipStatus.INVITED,
        )
        self.authenticate(requester)

        for membership_status in (
            MembershipStatus.INVITED,
            MembershipStatus.LEFT,
            MembershipStatus.REMOVED,
        ):
            with self.subTest(status=membership_status):
                membership.status = membership_status
                membership.save(update_fields=["status"])

                response = self.get()

                self.assertEqual(response.status_code, 403)
                self.assertNotIn("default_probability", response.data)

    def test_member_outside_circle_is_not_found(self):
        self.train_model()
        self.authenticate(self.user)

        response = self.get(member_id=self.outsider.id)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.data["detail"],
            "Member not found in this circle.",
        )

    def test_inactive_target_member_is_not_found(self):
        self.train_model()
        former = self.make_user("former")
        self.add_membership(self.circle, former, MembershipStatus.LEFT)
        self.authenticate(self.user)

        response = self.get(member_id=former.id)

        self.assertEqual(response.status_code, 404)

    def test_nonexistent_member_matches_member_outside_circle(self):
        self.authenticate(self.user)

        outside = self.get(member_id=self.outsider.id)
        missing = self.get(member_id=uuid.uuid4())

        self.assertEqual(missing.status_code, 404)
        self.assertEqual(
            (outside.status_code, outside.data),
            (missing.status_code, missing.data),
        )

    def test_nonexistent_circle_is_not_found(self):
        self.authenticate(self.user)

        response = self.get(circle_id=uuid.uuid4())

        self.assertEqual(response.status_code, 404)

    def test_malformed_ids_are_not_routed(self):
        self.authenticate(self.user)

        response = self.client.get(
            f"/api/risk/circles/not-a-uuid/members/{self.user.id}"
            "/default-risk/"
        )

        self.assertEqual(response.status_code, 404)

    def test_authorization_is_checked_before_model_availability(self):
        # No model exists; an outsider must still learn nothing.
        self.authenticate(self.outsider)

        response = self.get()

        self.assertEqual(response.status_code, 404)

    def test_only_get_is_allowed(self):
        self.train_model()
        self.authenticate(self.user)

        url = self.url(self.circle.id, self.user.id)

        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(url)
                self.assertEqual(response.status_code, 405)

    # Model availability

    def test_missing_model_returns_503(self):
        self.authenticate(self.user)

        with self.assertLogs("risk.views", level="WARNING"):
            response = self.get()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["code"], "model_unavailable")
        self.assertIn("no trained model", response.data["detail"])
        self.assertNotIn("default_probability", response.data)
        # The model directory must not leak to clients.
        self.assertNotIn(str(self.model_dir), str(response.data))
        self.assertFalse(
            ModelRegistry.artifact_path("logistic-default-v1").exists()
        )

    def test_incompatible_model_returns_503(self):
        self.train_model()
        artifact = ModelRegistry.load()
        artifact.feature_version = "features-v0"
        ModelRegistry.save(artifact)
        self.authenticate(self.user)

        with self.assertLogs("risk.views", level="ERROR"):
            response = self.get()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["code"], "model_incompatible")
        self.assertNotIn("default_probability", response.data)

    # Read-only guarantee

    def test_prediction_request_performs_no_writes(self):
        self.train_model()
        self.authenticate(self.user)

        watched = [
            LedgerTransaction,
            Payout,
            PayoutVote,
            ContributionObligation,
            Payment,
            AuditLog,
            TrustProfile,
            RiskAssessment,
            MemberRiskAssessment,
            MemberRiskFeatureSnapshot,
            MemberRiskOutcome,
        ]
        before = {m: m.objects.count() for m in watched}

        with CaptureQueriesContext(connection) as queries:
            response = self.get()

        self.assertEqual(response.status_code, 200)

        writes = [q["sql"] for q in queries if WRITE_SQL.match(q["sql"])]
        self.assertEqual(writes, [])
        self.assertEqual({m: m.objects.count() for m in watched}, before)


class DefaultRiskAPIArchitectureTests(SimpleTestCase):

    FORBIDDEN_PREFIXES = (
        "services.payouts",
        "services.finance",
        "services.payments",
        "services.circles",
        "services.governance",
    )

    def imported_modules(self, module):
        tree = ast.parse(inspect.getsource(module))
        names = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
            elif isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)

        return names

    def test_api_and_predictor_do_not_import_financial_services(self):
        for module in (risk.views, services.ml.predict_default_risk):
            with self.subTest(module=module.__name__):
                forbidden = [
                    name
                    for name in self.imported_modules(module)
                    if name.startswith(self.FORBIDDEN_PREFIXES)
                ]
                self.assertEqual(forbidden, [])
