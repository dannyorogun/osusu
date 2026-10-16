"""Ledger corrections: LedgerCorrectionService and its operator commands."""

from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.core.management.base import CommandError

from audit.models import AuditLog
from circles.tests import CircleAuthorizationFixture
from finance.models import (
    LedgerTransaction,
    Payout,
    PayoutStatus,
    TransactionStatus,
    TransactionType,
)
from services.finance.ledger_correction_service import (
    CorrectionInvalid,
    CorrectionNotAuthorized,
    LedgerCorrectionService,
)
from services.finance.ledger_service import LedgerService
from services.finance.treasury_engine import (
    INCOMING_TYPES,
    OUTGOING_TYPES,
    TreasuryEngine,
)


class TreasuryClassificationTests(CircleAuthorizationFixture):

    def test_every_type_has_exactly_one_direction(self):
        incoming, outgoing = set(INCOMING_TYPES), set(OUTGOING_TYPES)
        self.assertFalse(incoming & outgoing)
        self.assertEqual(incoming | outgoing, set(TransactionType.values))

    def test_outgoing_adjustment_lowers_balance_incoming_raises_it(self):
        for kind, amount in (
            (TransactionType.CONTRIBUTION, "100.00"),
            (TransactionType.ADJUSTMENT, "10.10"),
            (TransactionType.ADJUSTMENT_OUT, "25.05"),
        ):
            LedgerService.record_transaction(
                circle=self.circle, member=None, transaction_type=kind,
                amount=Decimal(amount), period_number=1,
            )
        self.assertEqual(TreasuryEngine.current_balance(self.circle), Decimal("85.05"))
        totals = TreasuryEngine.ledger_totals(self.circle)
        self.assertEqual(totals[TransactionType.ADJUSTMENT_OUT], {"total": Decimal("25.05"), "count": 1})


class LedgerCorrectionFixture(CircleAuthorizationFixture):

    def setUp(self):
        super().setUp()
        self.operator = self.make_user("operator")
        self.operator.user_permissions.add(
            Permission.objects.get(codename="record_ledger_correction")
        )
        # Re-fetch: Django caches permissions on the instance.
        self.operator = type(self.operator).objects.get(pk=self.operator.pk)
        self.contribution = LedgerService.record_transaction(
            circle=self.circle, member=self.member,
            transaction_type=TransactionType.CONTRIBUTION,
            amount=Decimal("500.00"), period_number=1, payment_reference="c-1",
        )

    def correct(self, **overrides):
        args = {
            "circle": self.circle,
            "direction": "out",
            "amount": "400.00",
            "reason": "Pre-Sprint-28 negative payout row inflated the balance.",
            "reference": "reconcile-1",
            "actor": self.operator,
            "corrects_transaction": self.contribution,
            **overrides,
        }
        return LedgerCorrectionService.record(**args)

    def balance(self):
        return TreasuryEngine.current_balance(self.circle)


class LedgerCorrectionServiceTests(LedgerCorrectionFixture):

    def test_outgoing_correction(self):
        entry, created = self.correct()

        self.assertTrue(created)
        self.assertEqual(entry.transaction_type, TransactionType.ADJUSTMENT_OUT)
        self.assertEqual(entry.amount, Decimal("400.00"))
        self.assertEqual(entry.status, TransactionStatus.COMPLETED)
        self.assertEqual(entry.payment_reference, "correction:reconcile-1")
        self.assertEqual(entry.metadata["corrects_transaction_id"], str(self.contribution.id))
        self.assertEqual(entry.metadata["actor_id"], str(self.operator.pk))
        self.assertEqual(self.balance(), Decimal("100.00"))

    def test_incoming_correction(self):
        entry, _ = self.correct(direction="in", amount="12.34", reference="reconcile-2")
        self.assertEqual(entry.transaction_type, TransactionType.ADJUSTMENT)
        self.assertEqual(self.balance(), Decimal("512.34"))

    def test_audit_event(self):
        entry, _ = self.correct()
        log = AuditLog.objects.get(action="LEDGER_CORRECTION_RECORDED")
        self.assertEqual(log.entity_id, str(entry.id))
        self.assertEqual(log.user, self.operator)
        self.assertEqual(log.metadata["direction"], "out")
        self.assertEqual(log.metadata["amount"], "400.00")
        self.assertEqual(log.metadata["reference"], "reconcile-1")
        self.assertIn("negative payout", log.metadata["reason"])

    def test_duplicate_is_idempotent(self):
        first, _ = self.correct()
        second, created = self.correct()
        self.assertFalse(created)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(
            LedgerTransaction.objects.filter(transaction_type=TransactionType.ADJUSTMENT_OUT).count(), 1
        )
        self.assertEqual(self.balance(), Decimal("100.00"))
        self.assertEqual(AuditLog.objects.filter(action="LEDGER_CORRECTION_RECORDED").count(), 1)

    def test_reference_reuse_for_a_different_correction_is_refused(self):
        self.correct()
        for change in ({"amount": "1.00"}, {"direction": "in"}, {"corrects_transaction": None, "incident": "INC-9"}):
            with self.subTest(change):
                with self.assertRaisesMessage(CorrectionInvalid, "already used"):
                    self.correct(**change)
        self.assertEqual(self.balance(), Decimal("100.00"))

    def test_invalid_amounts(self):
        for amount in ("0", "-5.00", "1.005", "abc", "NaN", "Infinity", "99999999999.00", None):
            with self.subTest(amount=amount):
                with self.assertRaises(CorrectionInvalid):
                    self.correct(amount=amount, reference=f"bad-{amount}")
        self.assertFalse(LedgerTransaction.objects.filter(
            transaction_type=TransactionType.ADJUSTMENT_OUT).exists())

    def test_requires_reason_reference_and_traceability(self):
        cases = {
            "no reason": {"reason": "  "},
            "bad reference": {"reference": "x"},
            "untraceable": {"corrects_transaction": None, "incident": ""},
            "bad direction": {"direction": "sideways"},
        }
        for label, change in cases.items():
            with self.subTest(label):
                with self.assertRaises(CorrectionInvalid):
                    self.correct(**change)

    def test_incident_alone_is_traceable(self):
        entry, _ = self.correct(corrects_transaction=None, incident="INC-2026-14", reference="inc-14")
        self.assertEqual(entry.metadata["incident"], "INC-2026-14")
        self.assertEqual(entry.period_number, 0)

    def test_corrected_entry_must_be_same_circle_and_completed(self):
        other = LedgerService.record_transaction(
            circle=self.other_circle, member=None,
            transaction_type=TransactionType.CONTRIBUTION,
            amount=Decimal("1.00"), period_number=1,
        )
        with self.assertRaisesMessage(CorrectionInvalid, "different circle"):
            self.correct(corrects_transaction=other)

        pending = LedgerTransaction.objects.create(
            circle=self.circle, transaction_type=TransactionType.CONTRIBUTION,
            amount=Decimal("1.00"), period_number=1, status=TransactionStatus.PENDING,
        )
        with self.assertRaisesMessage(CorrectionInvalid, "completed"):
            self.correct(corrects_transaction=pending)

    def test_authorization(self):
        inactive = self.make_user("inactive-op")
        inactive.user_permissions.add(Permission.objects.get(codename="record_ledger_correction"))
        inactive.is_active = False
        inactive.save()
        for label, actor in {
            "circle creator": self.creator,
            "no permission": self.member,
            "inactive operator": inactive,
            "nobody": None,
        }.items():
            with self.subTest(label):
                with self.assertRaises(CorrectionNotAuthorized):
                    self.correct(actor=actor)
        self.assertEqual(self.balance(), Decimal("500.00"))

    def test_original_entry_is_never_modified(self):
        snapshot = LedgerTransaction.objects.filter(pk=self.contribution.pk).values().get()
        self.correct()
        self.assertEqual(LedgerTransaction.objects.filter(pk=self.contribution.pk).values().get(), snapshot)

    def test_treasury_api_reports_outgoing_corrections(self):
        self.correct()
        self.authenticate(self.member)
        body = self.client.get(f"/api/circles/{self.circle.id}/treasury/").json()
        self.assertEqual(body["balance"], "100.00")
        self.assertEqual(body["totals"]["adjustment_out"], {"total": "400.00", "count": 1})


class CorrectionCommandTests(LedgerCorrectionFixture):

    def run_command(self, *extra):
        out = StringIO()
        call_command(
            "record_ledger_correction",
            "--circle", str(self.circle.id), "--direction", "out",
            "--amount", "400.00", "--reason", "Reviewed reconciliation",
            "--reference", "reconcile-cmd", "--actor", "operator",
            "--corrects-transaction", str(self.contribution.id),
            *extra, stdout=out,
        )
        return out.getvalue()

    def test_dry_run_writes_nothing(self):
        output = self.run_command()
        self.assertIn("DRY RUN", output)
        self.assertIn("balance: 500.00 -> 100.00", output)
        self.assertFalse(LedgerTransaction.objects.filter(
            transaction_type=TransactionType.ADJUSTMENT_OUT).exists())

    def test_confirm_writes_once(self):
        self.assertIn("Recorded correction", self.run_command("--confirm"))
        self.assertIn("Already recorded", self.run_command("--confirm"))
        self.assertEqual(self.balance(), Decimal("100.00"))

    def test_unauthorized_actor(self):
        with self.assertRaisesMessage(CommandError, "may not record"):
            call_command(
                "record_ledger_correction", "--circle", str(self.circle.id),
                "--direction", "out", "--amount", "1.00", "--reason", "x",
                "--reference", "nope-1", "--actor", "creator", "--incident", "INC-1",
                "--confirm", stdout=StringIO(),
            )


class AnomalyReportTests(CircleAuthorizationFixture):

    def report(self):
        out = StringIO()
        call_command("report_ledger_anomalies", "--json", stdout=out)
        import json
        return json.loads(out.getvalue())

    def test_clean_ledger(self):
        self.assertEqual(self.report(), [])

    def test_flags_without_changing_anything(self):
        negative = LedgerTransaction.objects.create(
            circle=self.circle, member=self.member,
            transaction_type=TransactionType.PAYOUT, amount=Decimal("-200.00"),
            period_number=1, status=TransactionStatus.COMPLETED,
            metadata={"payout_id": "missing"},
        )
        Payout.objects.create(
            circle=self.circle, member=self.creator, payout_window=1,
            amount=Decimal("200.00"), status=PayoutStatus.PAID,
        )
        before = list(LedgerTransaction.objects.values())

        kinds = sorted(f["kind"] for f in self.report())

        self.assertEqual(kinds, [
            "paid_payout_without_ledger",
            "payout_negative_amount",
            "payout_without_paid_payout",
        ])
        self.assertEqual(list(LedgerTransaction.objects.values()), before)
        negative.refresh_from_db()
        self.assertEqual(negative.amount, Decimal("-200.00"))
