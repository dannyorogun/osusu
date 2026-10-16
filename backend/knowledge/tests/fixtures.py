import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.test import TestCase, override_settings

from audit.models import AuditLog
from circles.models import (
    Circle,
    CircleConstitution,
    CircleMembership,
    CircleStatus,
    MembershipStatus,
)
from finance.models import (
    ContributionObligation,
    LedgerTransaction,
    ObligationStatus,
    Payout,
    PayoutStatus,
    PayoutVote,
    TransactionStatus,
    TransactionType,
)
from payments.models import Payment
from risk.models import RiskAssessment, RiskSignal
from trust.models import TrustEdge, TrustProfile


User = get_user_model()

T0 = datetime(2026, 1, 5, 9, 30, tzinfo=timezone.utc)
T1 = datetime(2026, 1, 12, 9, 30, tzinfo=timezone.utc)

WRITE_SQL = re.compile(
    r'^\s*(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+"?(\w+)"?',
    re.IGNORECASE,
)

SECRET_EMAIL = "secret-invitee@example.com"


def written_tables(queries):
    """Tables touched by INSERT/UPDATE/DELETE statements."""
    tables = set()
    for query in queries:
        match = WRITE_SQL.match(query["sql"])
        if match:
            tables.add(match.group(2))
    return tables


# Namespace for deterministic fixture user ids (uuid5 of the username).
FIXTURE_NAMESPACE = uuid.UUID("0b5e55a1-0000-4000-8000-000000000029")


class KnowledgeFixture(TestCase):
    """
    Circle A ("Manchester Developers") with members in every state,
    obligations in every status, ledger rows of every type, payouts with
    votes, a stored risk assessment, audit events and trust edges.
    Circle B ("Birmingham Bakers") belongs to an outsider.

    ML_MODEL_DIR points at an empty directory: no trained model exists.
    """

    def setUp(self):
        # User ids are deterministic (see make_user), so per-user state in
        # process-wide caches would leak between tests: start each test
        # with an empty assistant rate-limit window.
        caches["assistant_rate_limit"].clear()
        self.addCleanup(caches["assistant_rate_limit"].clear)

        model_dir = Path(tempfile.mkdtemp(prefix="osusu-knowledge-test-"))
        self.addCleanup(shutil.rmtree, model_dir, ignore_errors=True)
        no_model = override_settings(ML_MODEL_DIR=model_dir)
        no_model.enable()
        self.addCleanup(no_model.disable)

        self.alice = self.make_user("alice", first="Alice", last="Adeyemi")
        self.bob = self.make_user("bob")
        self.carol = self.make_user("carol@example.com")  # email-like
        self.dave = self.make_user("dave")
        self.erin = self.make_user("erin")
        self.outsider = self.make_user("outsider")

        self.circle = Circle.objects.create(
            creator=self.alice,
            name="Manchester Developers",
            description="Saving together for conference tickets.",
            status=CircleStatus.ACTIVE,
        )
        Circle.objects.filter(pk=self.circle.pk).update(created_at=T0)
        self.circle.refresh_from_db()

        self.constitution = CircleConstitution.objects.create(
            circle=self.circle,
            member_limit=5,
            contribution_amount=Decimal("50.00"),
            contribution_frequency="weekly",
            payout_amount=Decimal("100.00"),
            payout_frequency="biweekly",
            cycle_length=2,
            quorum_percentage=60,
            grace_period_days=7,
            reserve_enabled=True,
            reserve_amount=Decimal("25.00"),
            allow_replacement_before_lock=False,
        )

        self.m_alice = self.add_member(
            self.alice, MembershipStatus.ACTIVE, accepted=True,
        )
        self.m_bob = self.add_member(
            self.bob, MembershipStatus.ACTIVE, accepted=True,
            invited_by=self.alice,
        )
        self.m_carol = self.add_member(
            self.carol, MembershipStatus.ACTIVE, accepted=False,
            invited_by=self.outsider,  # inviter outside this circle
        )
        self.m_dave = self.add_member(self.dave, MembershipStatus.LEFT)
        self.m_erin = self.add_member(self.erin, MembershipStatus.REMOVED)

        self.obligation(self.alice, 1, ObligationStatus.PAID, paid_at=T1)
        self.alice_pending = self.obligation(
            self.alice, 2, ObligationStatus.PENDING,
        )
        self.obligation(self.bob, 1, ObligationStatus.OVERDUE)
        self.obligation(self.dave, 1, ObligationStatus.PAID, paid_at=T1)

        # Balance = 50 + 50 + 25 - 60 = 65.00 (pending row excluded).
        self.ledger(TransactionType.CONTRIBUTION, "50.00", self.alice)
        self.ledger(TransactionType.CONTRIBUTION, "50.00", self.dave)
        self.ledger(TransactionType.RESERVE, "25.00", None)
        self.ledger(TransactionType.PAYOUT, "60.00", self.bob)
        self.ledger(
            TransactionType.CONTRIBUTION, "999.00", self.bob,
            status=TransactionStatus.PENDING,
        )

        self.payout_bob = Payout.objects.create(
            circle=self.circle,
            member=self.bob,
            amount=Decimal("100.00"),
            payout_window=1,
            status=PayoutStatus.APPROVED,
            approved_at=T1,
        )
        PayoutVote.objects.create(payout=self.payout_bob, member=self.alice)
        PayoutVote.objects.create(payout=self.payout_bob, member=self.carol)
        Payout.objects.create(
            circle=self.circle,
            member=self.alice,
            amount=Decimal("100.00"),
            payout_window=1,
        )

        assessment = RiskAssessment.objects.create(
            circle=self.circle,
            risk_level="medium",
            risk_score=Decimal("42.50"),
        )
        RiskAssessment.objects.filter(pk=assessment.pk).update(created_at=T1)
        RiskSignal.objects.create(
            assessment=assessment,
            signal_type="FUNDING_RISK",
            severity="medium",
            message="Treasury covers 65% of the next payout.",
        )

        self.audit("CIRCLE_CREATED", "Circle", self.circle.id, self.alice)
        self.audit(
            "INVITATION_CREATED", "CircleInvitation", "inv-1", self.alice,
            {"circle_id": str(self.circle.id), "email": SECRET_EMAIL},
        )
        self.audit(
            "PAYOUT_WINDOW_CREATED", "Circle", self.circle.id, self.alice,
            {"window": 1, "candidates": 2},
        )

        TrustEdge.objects.create(
            inviter=self.alice, invited=self.bob,
            completed_together=1, successful_cycles_together=1,
        )
        TrustEdge.objects.create(inviter=self.bob, invited=self.carol)
        TrustEdge.objects.create(
            inviter=self.alice, invited=self.outsider,
            successful_cycles_together=3,
        )

        self.other_circle = Circle.objects.create(
            creator=self.outsider,
            name="Birmingham Bakers",
            description="Monthly sourdough fund.",
            status=CircleStatus.ACTIVE,
        )
        CircleConstitution.objects.create(
            circle=self.other_circle,
            contribution_amount=Decimal("75.00"),
            contribution_frequency="monthly",
            payout_amount=Decimal("300.00"),
            payout_frequency="monthly",
        )
        self.add_member(
            self.outsider, MembershipStatus.ACTIVE, circle=self.other_circle,
        )
        self.audit(
            "CIRCLE_CREATED", "Circle", self.other_circle.id, self.outsider,
        )

    # Builders

    def make_user(self, username, first="", last=""):
        # Deterministic ids: documents label members "Member <first 8 hex
        # of the user id>" (services/knowledge/schema.py). Random ids made
        # that token, and so its lexical hash bucket, change every run, and
        # occasionally collide with a query word (flaky Q6). Stable ids make
        # every retrieval score reproducible.
        return User.objects.create_user(
            id=uuid.uuid5(FIXTURE_NAMESPACE, username),
            username=username,
            email=f"{username.split('@')[0]}-private@example.com",
            password="StrongPassword123!",
            first_name=first,
            last_name=last,
        )

    def add_member(self, user, status, *, accepted=False, invited_by=None,
                   circle=None):
        return CircleMembership.objects.create(
            circle=circle or self.circle,
            user=user,
            status=status,
            invited_by=invited_by,
            joined_at=T0,
            constitution_accepted=accepted,
            constitution_accepted_at=T0 if accepted else None,
        )

    def obligation(self, member, period, status, paid_at=None):
        return ContributionObligation.objects.create(
            circle=self.circle,
            member=member,
            period_number=period,
            amount_due=Decimal("50.00"),
            due_date=T0,
            status=status,
            paid_at=paid_at,
        )

    def ledger(self, transaction_type, amount, member,
               status=TransactionStatus.COMPLETED):
        return LedgerTransaction.objects.create(
            circle=self.circle,
            member=member,
            transaction_type=transaction_type,
            amount=Decimal(amount),
            period_number=1,
            status=status,
        )

    def audit(self, action, entity_type, entity_id, user, metadata=None):
        return AuditLog.objects.create(
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            user=user,
            metadata=metadata or {},
        )

    # Assertions

    def domain_snapshot(self):
        """Every piece of financial / governance / trust state."""
        def rows(model, *fields):
            return list(model.objects.order_by("pk").values_list(*fields))

        return {
            "circles": rows(Circle, "pk", "status", "financial_locked_at"),
            "memberships": rows(CircleMembership, "pk", "status",
                                "constitution_accepted"),
            "obligations": rows(ContributionObligation, "pk", "status",
                                "paid_at", "amount_due"),
            "ledger": rows(LedgerTransaction, "pk", "status", "amount"),
            "payments": rows(Payment, "pk", "status"),
            "payouts": rows(Payout, "pk", "status", "approved_at", "paid_at"),
            "votes": rows(PayoutVote, "pk"),
            "risk": rows(RiskAssessment, "pk", "risk_level"),
            "trust_edges": rows(TrustEdge, "pk", "successful_cycles_together"),
            "trust_profiles": rows(TrustProfile, "pk"),
            "audit": rows(AuditLog, "pk"),
        }
