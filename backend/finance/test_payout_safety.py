"""
Payout provider safety boundary (Sprint 31).

"Production mode" below is OSUSU_PAYOUT_MOCK_ALLOWED=False, which settings
derive from DJANGO_DEBUG at startup (config/test_production_settings.py
checks that derivation in a fresh process). The ledger, treasury and
payout services are real; only the provider is a test double.
"""

import threading
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase, override_settings

from audit.models import AuditLog
from circles.models import Circle, CircleStatus
from circles.test_payout_api import PayoutApiFixture
from finance.models import LedgerTransaction, Payout, PayoutStatus, TransactionType
from finance.tests import PayoutLifecycleFixture
from services.circles.circle_service import CircleService
from services.finance.ledger_service import LedgerService
from services.finance.treasury_engine import TreasuryEngine
from services.payouts.execute_payout_service import (
    ExecutePayoutService,
    PayoutProviderUnavailable,
    get_payout_provider,
    idempotency_key,
)
from services.payouts.mock_payout_provider import MockPayoutProvider
from services.payouts.payout_completion_service import PayoutCompletionService


PRODUCTION = override_settings(
    OSUSU_PAYOUT_PROVIDER="disabled", OSUSU_PAYOUT_MOCK_ALLOWED=False,
)


class RecordingProvider:
    """
    Stands in for a future, independently verified live provider: declares
    production_ready and answers idempotently per key. Not a real provider.
    Like most real providers it only ACCEPTS a transfer synchronously;
    settlement needs separate evidence.
    """

    name = "recording"
    production_ready = True

    def __init__(self, result="sent", raises=False):
        self.result = result
        self.raises = raises
        self.calls = 0
        self.lock = threading.Lock()

    def send(self, *, member, amount, idempotency_key):
        with self.lock:
            self.calls += 1
        if self.raises:
            raise TimeoutError("provider timed out")
        if self.result == "rejected":
            return {"outcome": "rejected", "provider_status": "declined"}
        if self.result != "sent":
            return {"status": self.result}
        return {
            "outcome": self.outcome,
            "provider_reference": f"verified-{idempotency_key}",
        }

    outcome = "accepted"


class SettlingProvider(RecordingProvider):
    """A double whose contract confirms settlement on the send response."""

    name = "settling"
    confirms_settlement_on_send = True
    outcome = "settled"


class UnmarkedProvider(RecordingProvider):
    """Same behaviour, but never declared production-ready."""

    production_ready = False


class PayoutProviderResolutionTests(SimpleTestCase):

    @override_settings(OSUSU_PAYOUT_PROVIDER="mock", OSUSU_PAYOUT_MOCK_ALLOWED=True)
    def test_development_resolves_the_mock(self):
        self.assertIs(get_payout_provider(), MockPayoutProvider)

    @override_settings(OSUSU_PAYOUT_PROVIDER="disabled", OSUSU_PAYOUT_MOCK_ALLOWED=True)
    def test_disabled_is_unavailable(self):
        with self.assertRaisesMessage(PayoutProviderUnavailable, "Payouts are disabled"):
            get_payout_provider()

    @override_settings(OSUSU_PAYOUT_PROVIDER="mock", OSUSU_PAYOUT_MOCK_ALLOWED=False)
    def test_mock_is_unavailable_outside_development(self):
        with self.assertRaises(PayoutProviderUnavailable):
            get_payout_provider()

    @override_settings(OSUSU_PAYOUT_PROVIDER="stripe", OSUSU_PAYOUT_MOCK_ALLOWED=True)
    def test_unknown_provider_is_unavailable(self):
        with self.assertRaises(PayoutProviderUnavailable):
            get_payout_provider()

    def test_mock_declares_itself_and_is_never_production_ready(self):
        self.assertIs(MockPayoutProvider.is_mock, True)
        self.assertIs(MockPayoutProvider.production_ready, False)


class ProductionPayoutRefusalTests(PayoutLifecycleFixture):

    def assert_nothing_happened(self, winner):
        payout = Payout.objects.get(pk=winner.pk)
        self.assertEqual(payout.status, PayoutStatus.APPROVED)
        self.assertIsNone(payout.paid_at)
        self.assertFalse(self.payout_rows().exists())
        self.assertEqual(self.balance(), Decimal("250.00"))
        self.assertFalse(
            AuditLog.objects.filter(
                action__in=["PAYOUT_COMPLETED", "PAYOUT_EXECUTION_FAILED"]
            ).exists()
        )

    @PRODUCTION
    def test_disabled_provider_refuses_before_any_write(self):
        winner, _ = self.decide()
        with self.assertRaises(PayoutProviderUnavailable):
            ExecutePayoutService.execute(winner)
        self.assert_nothing_happened(winner)

    @PRODUCTION
    def test_configured_mock_is_refused(self):
        winner, _ = self.decide()
        with override_settings(OSUSU_PAYOUT_PROVIDER="mock"), mock.patch.object(
            MockPayoutProvider, "send", wraps=MockPayoutProvider.send,
        ) as send:
            with self.assertRaises(PayoutProviderUnavailable):
                ExecutePayoutService.execute(winner)
        send.assert_not_called()
        self.assert_nothing_happened(winner)

    @PRODUCTION
    def test_explicitly_passed_mock_is_refused(self):
        winner, _ = self.decide()
        with mock.patch.object(
            MockPayoutProvider, "send", wraps=MockPayoutProvider.send,
        ) as send:
            with self.assertRaises(PayoutProviderUnavailable):
                ExecutePayoutService.execute(winner, provider=MockPayoutProvider)
        send.assert_not_called()
        self.assert_nothing_happened(winner)

    @PRODUCTION
    def test_provider_not_marked_production_ready_is_refused(self):
        winner, _ = self.decide()
        provider = UnmarkedProvider()
        with self.assertRaises(PayoutProviderUnavailable):
            ExecutePayoutService.execute(winner, provider=provider)
        self.assertEqual(provider.calls, 0)
        self.assert_nothing_happened(winner)

    @PRODUCTION
    def test_paid_payout_is_still_reported_when_payouts_are_disabled(self):
        winner, _ = self.decide()
        ExecutePayoutService.execute(winner, provider=SettlingProvider())

        result = ExecutePayoutService.execute(winner)

        self.assertEqual(result["status"], "already_paid")
        self.assertEqual(self.payout_rows().count(), 1)

    @PRODUCTION
    def test_mock_confirmation_cannot_complete_a_payout(self):
        winner, _ = self.decide()
        reference = MockPayoutProvider.send(
            member=self.member, amount=winner.amount,
            idempotency_key=idempotency_key(winner, 1),
        )["provider_reference"]

        with self.assertRaisesMessage(ValueError, "mock payout confirmation"):
            PayoutCompletionService.complete(payout=winner, provider_reference=reference)

        self.assert_nothing_happened(winner)

    def test_mock_still_pays_in_development(self):
        winner, _ = self.decide()
        result = ExecutePayoutService.execute(winner)
        self.assertEqual(result["status"], "paid")
        self.assertEqual(self.payout_rows().count(), 1)
        self.assertEqual(self.balance(), Decimal("50.00"))


class ProductionReadyProviderTests(PayoutLifecycleFixture):
    """The existing financial rules hold for a provider allowed to send."""

    @PRODUCTION
    def test_acceptance_is_not_settlement(self):
        winner, _ = self.decide()
        provider = RecordingProvider()

        first = ExecutePayoutService.execute(winner, provider=provider)
        second = ExecutePayoutService.execute(winner, provider=provider)

        self.assertEqual((first["status"], second["status"]), ("submitted", "in_progress"))
        self.assertEqual(provider.calls, 1)
        self.assertFalse(self.payout_rows().exists())
        self.assertEqual(Payout.objects.get(pk=winner.pk).status, PayoutStatus.PROCESSING)
        self.assertEqual(
            first["attempt"].provider_reference, f"verified-{idempotency_key(winner, 1)}"
        )

    @PRODUCTION
    def test_settling_provider_pays_once_with_the_provider_reference(self):
        winner, _ = self.decide()
        provider = SettlingProvider()

        first = ExecutePayoutService.execute(winner, provider=provider)
        second = ExecutePayoutService.execute(winner, provider=provider)

        self.assertEqual((first["status"], second["status"]), ("paid", "already_paid"))
        self.assertEqual(provider.calls, 1)
        row = self.payout_rows().get()
        self.assertEqual(row.amount, Decimal("200.00"))
        self.assertEqual(row.payment_reference, f"verified-{idempotency_key(winner, 1)}")
        self.assertEqual(self.balance(), Decimal("50.00"))

    @PRODUCTION
    def test_timeout_is_unknown_and_declined_is_failed(self):
        winner, _ = self.decide()

        timeout = ExecutePayoutService.execute(winner, provider=RecordingProvider(raises=True))
        self.assertEqual(timeout["status"], "unknown")
        self.assertEqual(Payout.objects.get(pk=winner.pk).status, PayoutStatus.PROCESSING)
        self.assertEqual(timeout["attempt"].error_class, "TimeoutError")

        other = Payout.objects.create(
            circle=self.circle, member=self.creator, payout_window=2,
            amount=Decimal("10.00"), status=PayoutStatus.APPROVED,
        )
        declined = ExecutePayoutService.execute(other, provider=RecordingProvider(result="rejected"))
        self.assertEqual(declined["status"], "failed")
        self.assertEqual(Payout.objects.get(pk=other.pk).status, PayoutStatus.FAILED)

        self.assertFalse(self.payout_rows().exists())
        self.assertEqual(self.balance(), Decimal("250.00"))
        retried = ExecutePayoutService.execute(other, provider=SettlingProvider())
        self.assertEqual(retried["status"], "paid")
        self.assertEqual(self.payout_rows().count(), 1)

    @PRODUCTION
    def test_quorum_and_approval_are_still_required(self):
        candidates = self.open_window()
        provider = RecordingProvider()
        with self.assertRaisesMessage(ValueError, "Only approved payouts"):
            ExecutePayoutService.execute(candidates[self.member.pk], provider=provider)
        self.assertEqual(provider.calls, 0)


class PayoutExecuteApiSafetyTests(PayoutApiFixture):

    def approve(self):
        window = self.open_window()
        self.vote(self.creator, self.candidate(window, self.member))
        self.assertEqual(self.act("payout-window-approve", self.creator).status_code, 200)

    @PRODUCTION
    def test_disabled_payouts_answer_503_and_change_nothing(self):
        self.approve()

        response = self.act("payout-window-execute", self.creator)

        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual(body["result"], "unavailable")
        self.assertIn("Payouts are disabled", body["error"])
        self.assertEqual(body["window"]["state"], "approved")
        self.assertIsNone(body["window"]["payout"]["paid_at"])
        self.assertFalse(self.payout_rows().exists())
        self.assertEqual(TreasuryEngine.current_balance(self.circle), Decimal("250.00"))

    @PRODUCTION
    def test_member_still_gets_403_not_503(self):
        self.approve()
        self.assertEqual(self.act("payout-window-execute", self.member).status_code, 403)


class ConcurrentExecutionTests(TransactionTestCase):
    """
    Real concurrent transactions (one connection per thread): the payout
    row lock must let exactly one execution pay.
    """

    THREADS = 8

    def setUp(self):
        User = get_user_model()
        self.creator = User.objects.create_user(
            username="creator", email="creator@example.com", password="StrongPassword123!",
        )
        self.member = User.objects.create_user(
            username="member", email="member@example.com", password="StrongPassword123!",
        )
        circle = CircleService.create_circle(
            creator=self.creator, name="Concurrent Circle", member_limit=2,
            contribution_amount=Decimal("50.00"),
        )
        Circle.objects.filter(pk=circle.pk).update(status=CircleStatus.LOCKED)
        self.circle = Circle.objects.get(pk=circle.pk)
        LedgerService.record_transaction(
            circle=self.circle, member=self.creator,
            transaction_type=TransactionType.CONTRIBUTION,
            amount=Decimal("250.00"), period_number=1, payment_reference="fund",
        )
        self.payout = Payout.objects.create(
            circle=self.circle, member=self.member, payout_window=1,
            amount=Decimal("200.00"), status=PayoutStatus.APPROVED,
        )

    def run_concurrently(self, provider):
        barrier = threading.Barrier(self.THREADS)
        results, errors = [], []

        def worker():
            try:
                barrier.wait()
                results.append(ExecutePayoutService.execute(self.payout, provider=provider)["status"])
            except Exception as error:  # surfaced below
                errors.append(error)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(self.THREADS)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        self.assertEqual(errors, [])
        return sorted(results)

    def assert_paid_once(self, results):
        # Losers see the payout either mid-attempt or already paid; none
        # of them calls the provider.
        self.assertEqual(results.count("paid"), 1)
        self.assertTrue(set(results) <= {"paid", "in_progress", "already_paid"})
        rows = LedgerTransaction.objects.filter(
            circle=self.circle, transaction_type=TransactionType.PAYOUT,
        )
        self.assertEqual(rows.count(), 1)
        self.assertEqual(Payout.objects.get(pk=self.payout.pk).status, PayoutStatus.PAID)
        self.assertEqual(TreasuryEngine.current_balance(self.circle), Decimal("50.00"))
        self.assertEqual(AuditLog.objects.filter(action="PAYOUT_COMPLETED").count(), 1)

    @PRODUCTION
    def test_concurrent_executions_pay_once(self):
        provider = SettlingProvider()
        self.assert_paid_once(self.run_concurrently(provider))
        self.assertEqual(provider.calls, 1)

    @PRODUCTION
    def test_concurrent_executions_create_one_attempt(self):
        provider = RecordingProvider()
        results = self.run_concurrently(provider)
        self.assertEqual(results, ["in_progress"] * (self.THREADS - 1) + ["submitted"])
        self.assertEqual(provider.calls, 1)
        self.assertEqual(self.payout.attempts.count(), 1)
        self.assertFalse(
            LedgerTransaction.objects.filter(transaction_type=TransactionType.PAYOUT).exists()
        )

    def test_concurrent_executions_pay_once_with_development_mock(self):
        self.assert_paid_once(self.run_concurrently(None))

    @PRODUCTION
    def test_concurrent_executions_with_disabled_payouts_change_nothing(self):
        barrier = threading.Barrier(self.THREADS)
        outcomes = []

        def worker():
            try:
                barrier.wait()
                ExecutePayoutService.execute(self.payout)
                outcomes.append("ran")
            except PayoutProviderUnavailable:
                outcomes.append("unavailable")
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(self.THREADS)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        self.assertEqual(outcomes, ["unavailable"] * self.THREADS)
        self.assertEqual(Payout.objects.get(pk=self.payout.pk).status, PayoutStatus.APPROVED)
        self.assertFalse(
            LedgerTransaction.objects.filter(transaction_type=TransactionType.PAYOUT).exists()
        )
