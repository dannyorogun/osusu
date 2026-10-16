from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext

from circles.models import CircleMembership, MembershipStatus
from finance.models import TransactionType
from knowledge.models import KnowledgeDocumentType as T

from services.finance.treasury_engine import TreasuryEngine
from services.knowledge.document_builder import KnowledgeDocumentBuilder
from services.knowledge.schema import (
    KNOWLEDGE_SCHEMA_VERSION,
    display_name,
    document_hash,
    money,
)
from services.ml.test_default_risk_model import MLTestCase
from services.ml.train_default_model import DefaultModelTrainer
from services.risk.member_features import MEMBER_DEFAULT_FEATURE_NAMES

from .fixtures import SECRET_EMAIL, KnowledgeFixture, written_tables


def by_type(documents):
    grouped = {}
    for d in documents:
        grouped.setdefault(d.document_type, []).append(d)
    return grouped


class DocumentBuilderTests(KnowledgeFixture):

    def build(self, circle=None):
        return KnowledgeDocumentBuilder.build_circle_documents(
            circle or self.circle,
        )

    def one(self, document_type):
        (document,) = by_type(self.build())[document_type]
        return document

    # Structure

    def test_builds_the_six_document_types(self):
        documents = by_type(self.build())

        self.assertEqual(
            set(documents),
            {choice for choice in T.values},
        )
        for document_type in (
            T.CIRCLE_SUMMARY,
            T.CIRCLE_FINANCIAL_SUMMARY,
            T.PAYOUT_SUMMARY,
            T.RISK_SUMMARY,
            T.AUDIT_SUMMARY,
        ):
            self.assertEqual(len(documents[document_type]), 1)

    def test_output_is_deterministic(self):
        first = self.build()
        second = self.build()

        self.assertEqual(first, second)
        self.assertEqual(
            [d.content_hash for d in first],
            [d.content_hash for d in second],
        )

    def test_traceability_metadata(self):
        for document in self.build():
            with self.subTest(document=document.document_type):
                self.assertEqual(
                    document.metadata["schema_version"],
                    KNOWLEDGE_SCHEMA_VERSION,
                )
                self.assertEqual(
                    document.metadata["document_type"],
                    document.document_type,
                )
                self.assertEqual(
                    document.metadata["circle_id"],
                    str(self.circle.id),
                )
                self.assertEqual(
                    document.metadata["source_entity_id"],
                    document.entity_id,
                )

        summary = self.one(T.CIRCLE_SUMMARY)
        self.assertEqual(
            (summary.entity_type, summary.entity_id),
            ("circle", str(self.circle.id)),
        )

    # Circle and constitution

    def test_circle_summary_values(self):
        content = self.one(T.CIRCLE_SUMMARY).content

        for expected in (
            "Circle Manchester Developers is currently active.",
            "Description: Saving together for conference tickets.",
            "Created: 2026-01-05 09:30 UTC.",
            "Financially locked: not locked.",
            "The circle has 3 active members.",
            "Inactive memberships: 1 left, 1 removed.",
            "- bob: active member, joined 2026-01-05 09:30 UTC, accepted "
            "the constitution on 2026-01-05 09:30 UTC, invited by Alice "
            "Adeyemi.",
            "circle creator",
        ):
            self.assertIn(expected, content)

    def test_constitution_values(self):
        content = self.one(T.CIRCLE_SUMMARY).content

        for expected in (
            "Members contribute £50.00 weekly.",
            "The configured payout amount is £100.00 biweekly.",
            "The cycle length is 2 periods.",
            "The member limit is 5.",
            "Governance quorum is 60%.",
            "The grace period is 7 days.",
            "The reserve is enabled with £25.00.",
            "Replacing members before the financial lock is not allowed.",
        ):
            self.assertIn(expected, content)

    def test_trust_counts_only_edges_inside_the_circle(self):
        content = self.one(T.CIRCLE_SUMMARY).content

        # alice->bob (successful) and bob->carol; alice->outsider excluded.
        self.assertIn(
            "There are 2 trust connections between members of this "
            "circle; 1 of them have completed at least one successful "
            "cycle together.",
            content,
        )

    # Treasury

    def test_treasury_values_come_from_treasury_engine(self):
        content = self.one(T.CIRCLE_FINANCIAL_SUMMARY).content

        self.assertEqual(
            TreasuryEngine.current_balance(self.circle),
            Decimal("65.00"),
        )
        for expected in (
            "The current treasury balance of Manchester Developers is "
            "£65.00, based on 4 completed ledger transactions.",
            "- Contributions: £100.00 across 2 transactions.",
            "- Payouts: £60.00 across 1 transaction.",
            "- Reserve: £25.00 across 1 transaction.",
            "- Refunds: £0.00 across 0 transactions.",
            "Contribution obligations in total: 4.",
            "- Paid: 2 totalling £100.00.",
            "- Overdue: 1 totalling £50.00.",
        ):
            self.assertIn(expected, content)

        # The pending ledger row is not treasury money.
        self.assertNotIn("999", content)

    def test_ledger_totals_agree_with_current_balance(self):
        totals = TreasuryEngine.ledger_totals(self.circle)
        incoming = sum(
            totals[t]["total"]
            for t in (
                TransactionType.CONTRIBUTION,
                TransactionType.RESERVE,
                TransactionType.ADJUSTMENT,
            )
        )
        outgoing = sum(
            totals[t]["total"]
            for t in (TransactionType.PAYOUT, TransactionType.REFUND)
        )

        self.assertEqual(set(totals), set(TransactionType.values))
        self.assertEqual(
            incoming - outgoing,
            TreasuryEngine.current_balance(self.circle),
        )

    # Contributions

    def test_member_contribution_documents(self):
        documents = {
            d.entity_id: d
            for d in by_type(self.build())[T.MEMBER_CONTRIBUTION_SUMMARY]
        }

        # Active members, plus dave (left) who has obligations; erin
        # (removed, no obligations) gets no document.
        self.assertEqual(
            set(documents),
            {
                str(m.id)
                for m in (self.m_alice, self.m_bob, self.m_carol, self.m_dave)
            },
        )

        alice = documents[str(self.m_alice.id)]
        self.assertEqual(alice.entity_type, "circle_membership")
        self.assertEqual(alice.subject_user_id, str(self.alice.id))
        for expected in (
            "Alice Adeyemi is an active member of Manchester Developers.",
            "Alice Adeyemi has 2 contribution obligations: 1 paid, 1 "
            "pending, 0 overdue, 0 waived.",
            "- Period 1: £50.00 due 2026-01-05 09:30 UTC, status paid, "
            "paid 2026-01-12 09:30 UTC.",
            "- Period 2: £50.00 due 2026-01-05 09:30 UTC, status pending.",
        ):
            self.assertIn(expected, alice.content)

        self.assertIn(
            "dave is a left member",
            documents[str(self.m_dave.id)].content,
        )

    # Payouts

    def test_payout_summary(self):
        content = self.one(T.PAYOUT_SUMMARY).content

        for expected in (
            "The constitution sets payouts of £100.00 biweekly.",
            "## Payout window 1",
            "- bob: £100.00, status approved, approved 2026-01-12 09:30 "
            "UTC, paid not recorded, 2 member votes.",
            "- Alice Adeyemi: £100.00, status pending, approved not "
            "recorded, paid not recorded, 0 member votes.",
        ):
            self.assertIn(expected, content)

    # Risk

    def test_risk_summary_without_model(self):
        content = self.one(T.RISK_SUMMARY).content

        self.assertIn(
            "rated the circle medium risk, score 42.50.",
            content,
        )
        self.assertIn(
            "- funding risk (medium): Treasury covers 65% of the next "
            "payout.",
            content,
        )
        self.assertIn(
            "No trained default-risk model is available",
            content,
        )
        self.assertNotIn("probability", content)

    # Audit

    def test_audit_summary_uses_allowlisted_wording(self):
        content = self.one(T.AUDIT_SUMMARY).content

        self.assertIn("The 3 most recent recorded events", content)
        self.assertIn("Circle created by Alice Adeyemi.", content)
        self.assertIn("An invitation to join was sent by Alice", content)
        self.assertIn("Payout window 1 was opened by Alice", content)
        # Other circle's events are not included.
        self.assertEqual(content.count("Circle created"), 1)

    # Privacy

    def test_no_emails_or_private_details_anywhere(self):
        for document in self.build():
            text = document.title + document.content + str(document.metadata)
            with self.subTest(document=document.document_type):
                self.assertNotIn("@", text)
                self.assertNotIn(SECRET_EMAIL, text)
                self.assertNotIn("private", text)
                self.assertNotIn("outsider", text)
                self.assertNotIn("Birmingham", text)
                self.assertNotIn("password", text.lower())
                for feature in MEMBER_DEFAULT_FEATURE_NAMES:
                    self.assertNotIn(feature, text)

    def test_email_like_username_becomes_pseudonym(self):
        name = display_name(self.carol)

        self.assertEqual(name, f"Member {str(self.carol.id)[:8]}")
        self.assertIn(name, self.one(T.CIRCLE_SUMMARY).content)

    def test_money_formatting_is_decimal_exact(self):
        self.assertEqual(money(Decimal("1234.5")), "£1,234.50")
        self.assertEqual(money(Decimal("-0.005")), "-£0.01")
        self.assertEqual(money(Decimal("0")), "£0.00")

    # Hashing

    def test_same_input_same_hash_changed_input_changed_hash(self):
        before = self.one(T.CIRCLE_FINANCIAL_SUMMARY).content_hash
        self.assertEqual(
            before,
            self.one(T.CIRCLE_FINANCIAL_SUMMARY).content_hash,
        )

        self.ledger(TransactionType.CONTRIBUTION, "50.00", self.bob)

        after = self.one(T.CIRCLE_FINANCIAL_SUMMARY)
        self.assertNotEqual(before, after.content_hash)
        self.assertIn("£115.00", after.content)

    def test_hash_is_sha256_of_canonical_fields(self):
        document = self.one(T.CIRCLE_SUMMARY)

        self.assertRegex(document.content_hash, r"^[0-9a-f]{64}$")
        self.assertEqual(
            document.content_hash,
            document_hash(
                document_type=document.document_type,
                entity_type=document.entity_type,
                entity_id=document.entity_id,
                title=document.title,
                content=document.content,
            ),
        )

    # Read-only and performance

    def test_building_is_read_only(self):
        with CaptureQueriesContext(connection) as queries:
            self.build()

        self.assertEqual(written_tables(queries), set())

    def test_query_count_does_not_grow_with_members(self):
        with CaptureQueriesContext(connection) as small:
            self.build()

        for n in range(5):
            user = self.make_user(f"extra{n}")
            CircleMembership.objects.create(
                circle=self.circle,
                user=user,
                status=MembershipStatus.ACTIVE,
                invited_by=self.bob,
            )
            self.obligation(user, 1, "pending")

        with CaptureQueriesContext(connection) as large:
            documents = self.build()

        self.assertEqual(len(large), len(small))
        self.assertEqual(
            len(by_type(documents)[T.MEMBER_CONTRIBUTION_SUMMARY]),
            9,
        )


class RiskSummaryWithModelTests(MLTestCase):
    """Uses Sprint 20's isolated training fixture: a real trained model."""

    def test_includes_probability_but_never_features(self):
        self.add_history(10)
        DefaultModelTrainer.train()

        (risk,) = [
            d for d in KnowledgeDocumentBuilder.build_circle_documents(
                self.circle,
            )
            if d.document_type == T.RISK_SUMMARY
        ]

        self.assertIn("Probabilities come from model logistic-default-v1", risk.content)
        self.assertIn("informational risk signals only", risk.content)
        self.assertRegex(
            risk.content,
            r"estimated default probability \d{1,3}\.\d{2}%\.",
        )
        for feature in MEMBER_DEFAULT_FEATURE_NAMES:
            self.assertNotIn(feature, risk.content)

        again = [
            d for d in KnowledgeDocumentBuilder.build_circle_documents(
                self.circle,
            )
            if d.document_type == T.RISK_SUMMARY
        ][0]
        self.assertEqual(risk.content_hash, again.content_hash)
