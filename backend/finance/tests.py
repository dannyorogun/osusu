"""
Payout lifecycle through the real services (PayoutEngine ->
PayoutVoteService -> PayoutApprovalService -> ExecutePayoutService ->
PayoutCompletionService -> LedgerService), with TreasuryEngine as the
authority for balances. Providers are test doubles of the payout provider
only; treasury arithmetic is never mocked.
"""

import importlib
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from audit.models import AuditLog
from circles.models import MembershipStatus
from circles.tests import CircleAuthorizationFixture
from finance.models import (
    ContributionObligation,
    LedgerTransaction,
    ObligationStatus,
    Payout,
    PayoutStatus,
    PayoutVote,
    TransactionType,
)
from services.finance.ledger_service import LedgerService
from services.finance.treasury_engine import TreasuryEngine
from services.payouts.execute_payout_service import (
    ExecutePayoutService,
    idempotency_key,
)
from services.payouts.mock_payout_provider import MockPayoutProvider
from services.payouts.payout_approval_service import PayoutApprovalService
from services.payouts.payout_completion_service import PayoutCompletionService
from services.payouts.payout_engine import PayoutEngine
from services.payouts.payout_vote_service import PayoutVoteService
from services.payouts.provider import PayoutNotSent


class CountingProvider:
    """The mock provider (settles synchronously), counting calls."""

    name = "counting"
    confirms_settlement_on_send = True

    def __init__(self):
        self.calls = 0

    def send(self, **kwargs):
        self.calls += 1
        return MockPayoutProvider.send(**kwargs)


class FailingProvider:
    """
    Does not pay. `raises` is an exception (instance or class) to raise,
    or True for an ambiguous ConnectionError; otherwise returns `result`.
    """

    name = "failing"

    def __init__(self, result=None, raises=False):
        self.result = result
        self.raises = raises
        self.calls = 0

    def send(self, **kwargs):
        self.calls += 1
        if self.raises is True:
            raise ConnectionError("provider unreachable")
        if self.raises:
            raise self.raises
        return self.result


REJECTED = {"outcome": "rejected", "provider_status": "declined"}


class ExecutePayoutImportTests(TestCase):

    def test_execute_payout_service_module_imports(self):
        # Regression: it imported services.payments.mock_payout_provider,
        # which does not exist.
        module = importlib.import_module("services.payouts.execute_payout_service")
        self.assertIs(module.MockPayoutProvider, MockPayoutProvider)

    def test_mock_provider_reference_is_stable_per_key(self):
        a = MockPayoutProvider.send(member=None, amount=Decimal("1"), idempotency_key="k1")
        b = MockPayoutProvider.send(member=None, amount=Decimal("1"), idempotency_key="k1")
        c = MockPayoutProvider.send(member=None, amount=Decimal("1"), idempotency_key="k2")
        self.assertEqual(a["provider_reference"], b["provider_reference"])
        self.assertNotEqual(a["provider_reference"], c["provider_reference"])
        self.assertNotIn("recipient", a)


class PayoutLifecycleFixture(CircleAuthorizationFixture):
    """
    Two eligible members (creator, member), payout 200.00, quorum 50%
    (1 of 2 votes). Treasury funded with 250.00 of completed contributions.
    """

    def setUp(self):
        super().setUp()
        for user, ref in ((self.creator, "c1"), (self.member, "m1")):
            LedgerService.record_transaction(
                circle=self.circle,
                member=user,
                transaction_type=TransactionType.CONTRIBUTION,
                amount=Decimal("125.00"),
                period_number=1,
                payment_reference=f"contrib-{ref}",
            )

    def balance(self):
        return TreasuryEngine.current_balance(self.circle)

    def payout_rows(self):
        return LedgerTransaction.objects.filter(
            circle=self.circle, transaction_type=TransactionType.PAYOUT,
        )

    def open_window(self, window=1):
        return {p.member_id: p for p in PayoutEngine.create_payout_window(
            circle=self.circle, payout_window=window,
        )}

    def decide(self, window=1, recipient=None):
        candidates = self.open_window(window)
        recipient = recipient or self.member
        PayoutVoteService.cast_vote(payout=candidates[recipient.pk], voter=self.creator)
        winner = PayoutApprovalService.approve(self.circle, window)
        return winner, candidates


class PayoutWindowTests(PayoutLifecycleFixture):

    def test_window_creates_pending_candidates_for_eligible_members(self):
        candidates = self.open_window()
        self.assertEqual(set(candidates), {self.creator.pk, self.member.pk})
        self.assertEqual(
            {p.status for p in candidates.values()}, {PayoutStatus.PENDING}
        )
        self.assertEqual(
            {p.amount for p in candidates.values()}, {Decimal("200.00")}
        )

    def test_reopening_the_same_open_window_is_idempotent(self):
        self.open_window()
        self.open_window()
        self.assertEqual(Payout.objects.filter(circle=self.circle).count(), 2)

    def test_no_new_window_while_recipient_unpaid(self):
        self.decide()
        with self.assertRaisesMessage(ValueError, "still unresolved"):
            self.open_window(2)

    def test_no_new_window_while_another_is_open(self):
        self.open_window(1)
        with self.assertRaisesMessage(ValueError, "still unresolved"):
            self.open_window(2)

    def test_decided_window_cannot_be_reopened(self):
        winner, _ = self.decide()
        ExecutePayoutService.execute(winner)
        with self.assertRaisesMessage(ValueError, "already been decided"):
            self.open_window(1)

    def test_losing_candidate_stays_eligible_recipient_does_not(self):
        winner, _ = self.decide()
        ExecutePayoutService.execute(winner)
        # Re-fund for the next window.
        LedgerService.record_transaction(
            circle=self.circle, member=self.creator,
            transaction_type=TransactionType.CONTRIBUTION,
            amount=Decimal("200.00"), period_number=2,
            payment_reference="contrib-c2",
        )

        candidates = self.open_window(2)

        self.assertEqual(set(candidates), {self.creator.pk})


class PayoutVoteTests(PayoutLifecycleFixture):

    def test_repeat_vote_for_same_candidate_is_a_no_op(self):
        candidates = self.open_window()
        target = candidates[self.member.pk]
        PayoutVoteService.cast_vote(payout=target, voter=self.creator)
        PayoutVoteService.cast_vote(payout=target, voter=self.creator)
        self.assertEqual(PayoutVote.objects.filter(member=self.creator).count(), 1)

    def test_second_vote_in_same_window_is_refused(self):
        candidates = self.open_window()
        PayoutVoteService.cast_vote(payout=candidates[self.member.pk], voter=self.creator)
        with self.assertRaisesMessage(ValueError, "already voted in this payout window"):
            PayoutVoteService.cast_vote(
                payout=candidates[self.creator.pk], voter=self.creator,
            )
        self.assertEqual(PayoutVote.objects.filter(member=self.creator).count(), 1)

    def test_ineligible_voters_are_refused(self):
        candidates = self.open_window()
        for user in (self.outsider, self.left, self.invited):
            with self.subTest(user=user.username):
                with self.assertRaisesMessage(ValueError, "Only eligible members can vote"):
                    PayoutVoteService.cast_vote(
                        payout=candidates[self.member.pk], voter=user,
                    )

    def test_overdue_member_cannot_vote(self):
        candidates = self.open_window()
        ContributionObligation.objects.create(
            circle=self.circle, member=self.member, period_number=1,
            amount_due=Decimal("50.00"), due_date="2026-01-01T00:00:00Z",
            status=ObligationStatus.OVERDUE,
        )
        with self.assertRaisesMessage(ValueError, "Only eligible members can vote"):
            PayoutVoteService.cast_vote(payout=candidates[self.creator.pk], voter=self.member)

    def test_voting_closes_when_window_is_decided(self):
        _, candidates = self.decide()
        with self.assertRaisesMessage(ValueError, "has closed"):
            PayoutVoteService.cast_vote(payout=candidates[self.creator.pk], voter=self.member)

    def test_votes_are_audited_but_never_listed_in_activity(self):
        candidates = self.open_window()
        PayoutVoteService.cast_vote(payout=candidates[self.member.pk], voter=self.creator)
        self.assertTrue(AuditLog.objects.filter(action="PAYOUT_VOTE_CAST").exists())

        self.authenticate(self.member)
        body = self.client.get(
            reverse("circle-activity", kwargs={"circle_id": self.circle.id})
        ).json()
        self.assertNotIn("vote", str(body).lower())


class PayoutApprovalTests(PayoutLifecycleFixture):

    def test_quorum_is_required(self):
        constitution = self.circle.constitution
        constitution.quorum_percentage = 100  # both of 2 eligible voters
        constitution.save()
        candidates = self.open_window()
        PayoutVoteService.cast_vote(payout=candidates[self.member.pk], voter=self.creator)

        with self.assertRaisesMessage(ValueError, "Quorum not reached: 1 of 2"):
            PayoutApprovalService.approve(self.circle, 1)
        self.assertFalse(
            Payout.objects.exclude(status=PayoutStatus.PENDING).exists()
        )

    def test_no_votes_cannot_decide(self):
        self.open_window()
        with self.assertRaisesMessage(ValueError, "Quorum not reached: 0 of 1"):
            PayoutApprovalService.approve(self.circle, 1)

    def test_winner_approved_and_losers_finalised(self):
        winner, candidates = self.decide()

        self.assertEqual(winner.member_id, self.member.pk)
        self.assertEqual(winner.status, PayoutStatus.APPROVED)
        self.assertIsNotNone(winner.approved_at)
        loser = Payout.objects.get(pk=candidates[self.creator.pk].pk)
        self.assertEqual(loser.status, PayoutStatus.CANCELLED)
        self.assertFalse(Payout.objects.filter(status=PayoutStatus.PENDING).exists())
        # Deciding moves no money.
        self.assertFalse(self.payout_rows().exists())

    def test_approval_is_idempotent(self):
        winner, _ = self.decide()
        again = PayoutApprovalService.approve(self.circle, 1)
        self.assertEqual(again.pk, winner.pk)
        self.assertEqual(AuditLog.objects.filter(action="PAYOUT_APPROVED").count(), 1)

    def test_tie_goes_to_earliest_candidate(self):
        constitution = self.circle.constitution
        constitution.quorum_percentage = 100
        constitution.save()
        candidates = self.open_window()
        PayoutVoteService.cast_vote(payout=candidates[self.member.pk], voter=self.creator)
        PayoutVoteService.cast_vote(payout=candidates[self.creator.pk], voter=self.member)
        # Rule under test: equal votes -> earliest-created candidate.
        first, second = sorted(candidates.values(), key=lambda p: p.created_at)
        Payout.objects.filter(pk=second.pk).update(
            created_at=first.created_at + timedelta(seconds=1)
        )
        earliest = first

        winner = PayoutApprovalService.approve(self.circle, 1)

        self.assertEqual(winner.pk, earliest.pk)

    def test_unknown_window(self):
        with self.assertRaisesMessage(ValueError, "No payout candidates"):
            PayoutApprovalService.approve(self.circle, 7)


class PayoutExecutionTests(PayoutLifecycleFixture):

    def test_execution_pays_once_with_one_ledger_effect(self):
        winner, _ = self.decide()
        before = self.balance()

        result = ExecutePayoutService.execute(winner)

        self.assertEqual(result["status"], "paid")
        payout = Payout.objects.get(pk=winner.pk)
        self.assertEqual(payout.status, PayoutStatus.PAID)
        self.assertIsNotNone(payout.paid_at)
        rows = list(self.payout_rows())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].amount, Decimal("200.00"))  # positive magnitude
        self.assertEqual(rows[0].member_id, self.member.pk)
        self.assertEqual(rows[0].metadata, {"payout_id": str(payout.id)})
        self.assertEqual(before, Decimal("250.00"))
        self.assertEqual(self.balance(), Decimal("50.00"))
        self.assertEqual(AuditLog.objects.filter(action="PAYOUT_COMPLETED").count(), 1)

    def test_second_execution_does_not_call_provider_or_debit_again(self):
        winner, _ = self.decide()
        provider = CountingProvider()
        ExecutePayoutService.execute(winner, provider=provider)

        result = ExecutePayoutService.execute(winner, provider=provider)

        self.assertEqual(result["status"], "already_paid")
        self.assertEqual(provider.calls, 1)
        self.assertEqual(self.payout_rows().count(), 1)
        self.assertEqual(self.balance(), Decimal("50.00"))

    def test_completion_replay_is_deduplicated_by_reference(self):
        winner, _ = self.decide()
        ref = MockPayoutProvider.send(
            member=self.member, amount=winner.amount,
            idempotency_key=idempotency_key(winner, 1),
        )["provider_reference"]
        ExecutePayoutService.execute(winner)

        # Replaying completion with the same reference changes nothing.
        PayoutCompletionService.complete(payout=winner, provider_reference=ref)

        self.assertEqual(self.payout_rows().count(), 1)
        self.assertEqual(self.payout_rows().get().payment_reference, ref)

    def test_non_approved_payouts_cannot_be_executed(self):
        candidates = self.open_window()
        provider = CountingProvider()
        with self.assertRaisesMessage(ValueError, "Only approved payouts"):
            ExecutePayoutService.execute(candidates[self.member.pk], provider=provider)

        winner, _ = self.decide()
        loser = Payout.objects.get(status=PayoutStatus.CANCELLED)
        with self.assertRaisesMessage(ValueError, "Only approved payouts"):
            ExecutePayoutService.execute(loser, provider=provider)

        self.assertEqual(provider.calls, 0)
        self.assertFalse(self.payout_rows().exists())

    def test_insufficient_treasury_refuses_before_provider_call(self):
        winner, _ = self.decide()
        LedgerService.record_transaction(
            circle=self.circle, member=self.creator,
            transaction_type=TransactionType.REFUND,
            amount=Decimal("100.00"), period_number=1,
            payment_reference="refund-1",
        )  # balance 150.00 < 200.00
        provider = CountingProvider()

        with self.assertRaisesMessage(ValueError, "Treasury cannot fund"):
            ExecutePayoutService.execute(winner, provider=provider)

        self.assertEqual(provider.calls, 0)
        self.assertEqual(Payout.objects.get(pk=winner.pk).status, PayoutStatus.APPROVED)
        self.assertFalse(self.payout_rows().exists())

    def test_ambiguous_responses_are_unknown_never_failed(self):
        # Sprint 33: none of these proves that no money moved.
        cases = {
            "provider error": FailingProvider(raises=True),
            "legacy failed status": FailingProvider(result={"status": "failed"}),
            "no reference": FailingProvider(result={"status": "sent"}),
            "no result": FailingProvider(result=None),
        }
        for window, (label, provider) in enumerate(cases.items(), start=1):
            with self.subTest(label):
                payout = Payout.objects.create(
                    circle=self.circle, member=self.member, payout_window=window,
                    amount=Decimal("1.00"), status=PayoutStatus.APPROVED,
                )
                result = ExecutePayoutService.execute(payout, provider=provider)

                self.assertEqual(result["status"], "unknown")
                payout.refresh_from_db()
                self.assertEqual(payout.status, PayoutStatus.PROCESSING)
                self.assertIsNone(payout.paid_at)
                self.assertFalse(self.payout_rows().exists())
                self.assertEqual(self.balance(), Decimal("250.00"))
        self.assertFalse(AuditLog.objects.filter(action="PAYOUT_EXECUTION_FAILED").exists())
        self.assertEqual(AuditLog.objects.filter(action="PAYOUT_OUTCOME_UNKNOWN").count(), 4)
        self.assertFalse(AuditLog.objects.filter(action="PAYOUT_COMPLETED").exists())

    def test_confirmed_failure_is_failed_and_records_nothing(self):
        for window, provider in enumerate(
            (FailingProvider(result=REJECTED), FailingProvider(raises=PayoutNotSent())),
            start=1,
        ):
            with self.subTest(window=window):
                payout = Payout.objects.create(
                    circle=self.circle, member=self.member, payout_window=window,
                    amount=Decimal("1.00"), status=PayoutStatus.APPROVED,
                )
                result = ExecutePayoutService.execute(payout, provider=provider)

                self.assertEqual(result["status"], "failed")
                payout.refresh_from_db()
                self.assertEqual(payout.status, PayoutStatus.FAILED)
                self.assertFalse(self.payout_rows().exists())
                self.assertEqual(self.balance(), Decimal("250.00"))
        self.assertEqual(AuditLog.objects.filter(action="PAYOUT_EXECUTION_FAILED").count(), 2)

    def test_confirmed_failed_payout_can_be_executed_again_exactly_once(self):
        winner, _ = self.decide()
        ExecutePayoutService.execute(winner, provider=FailingProvider(result=REJECTED))

        result = ExecutePayoutService.execute(winner)
        again = ExecutePayoutService.execute(winner)

        self.assertEqual(result["status"], "paid")
        self.assertEqual(again["status"], "already_paid")
        self.assertEqual(self.payout_rows().count(), 1)
        self.assertEqual(self.balance(), Decimal("50.00"))
        attempts = list(winner.attempts.order_by("attempt_number"))
        self.assertEqual(
            [(a.attempt_number, a.state) for a in attempts],
            [(1, "failed"), (2, "succeeded")],
        )
        self.assertNotEqual(attempts[0].idempotency_key, attempts[1].idempotency_key)

    def test_unknown_outcome_is_never_retried(self):
        winner, _ = self.decide()
        ExecutePayoutService.execute(winner, provider=FailingProvider(raises=True))
        provider = CountingProvider()

        again = ExecutePayoutService.execute(winner, provider=provider)

        self.assertEqual(again["status"], "in_progress")
        self.assertEqual(provider.calls, 0)
        self.assertEqual(winner.attempts.count(), 1)
        self.assertFalse(self.payout_rows().exists())

    def test_failed_recipient_blocks_new_windows_until_resolved(self):
        winner, _ = self.decide()
        ExecutePayoutService.execute(winner, provider=FailingProvider(raises=True))
        with self.assertRaisesMessage(ValueError, "still unresolved"):
            self.open_window(2)

    def test_paid_records_are_not_altered_by_later_calls(self):
        winner, _ = self.decide()
        ExecutePayoutService.execute(winner)
        row = self.payout_rows().get()
        snapshot = (row.amount, row.status, row.completed_at, row.payment_reference)
        paid_at = Payout.objects.get(pk=winner.pk).paid_at

        ExecutePayoutService.execute(winner)
        PayoutApprovalService.approve(self.circle, 1)
        with self.assertRaises(ValueError):
            ExecutePayoutService.execute(Payout.objects.get(status=PayoutStatus.CANCELLED))

        row.refresh_from_db()
        self.assertEqual(
            (row.amount, row.status, row.completed_at, row.payment_reference), snapshot
        )
        self.assertEqual(Payout.objects.get(pk=winner.pk).paid_at, paid_at)

    def test_decimal_amounts_are_exact(self):
        constitution = self.circle.constitution
        constitution.payout_amount = Decimal("123.45")
        constitution.save()
        winner, _ = self.decide()

        ExecutePayoutService.execute(winner)

        self.assertEqual(self.payout_rows().get().amount, Decimal("123.45"))
        self.assertEqual(self.balance(), Decimal("126.55"))


class PayoutReadAfterLifecycleTests(PayoutLifecycleFixture):

    def payouts(self):
        self.authenticate(self.creator)
        return self.client.get(
            reverse("circle-payouts", kwargs={"circle_id": self.circle.id})
        ).json()

    def test_failed_payout_is_listed_as_failed_not_paid(self):
        winner, _ = self.decide()
        ExecutePayoutService.execute(winner, provider=FailingProvider(result=REJECTED))

        body = self.payouts()

        self.assertEqual(
            [(p["status"], p["paid_at"]) for p in body["payouts"]], [("failed", None)]
        )
        self.assertEqual(body["open_windows"], [])

    def test_cancelled_candidates_are_not_listed(self):
        winner, _ = self.decide()
        ExecutePayoutService.execute(winner)

        body = self.payouts()

        self.assertEqual([p["status"] for p in body["payouts"]], ["paid"])
        self.assertEqual(body["open_windows"], [])

    def test_activity_shows_approval_and_completion(self):
        winner, _ = self.decide()
        ExecutePayoutService.execute(winner)
        self.authenticate(self.creator)

        events = [
            (e["event"], e["payout_window"])
            for e in self.client.get(
                reverse("circle-activity", kwargs={"circle_id": self.circle.id})
            ).json()
        ]

        self.assertIn(("payout_approved", 1), events)
        self.assertIn(("payout_completed", 1), events)


class InactiveMemberPayoutTests(PayoutLifecycleFixture):

    def test_inactive_members_are_never_candidates(self):
        candidates = self.open_window()
        inactive = {self.invited.pk, self.left.pk, self.removed.pk}
        self.assertFalse(inactive & set(candidates))
        self.assertEqual(
            MembershipStatus.ACTIVE,
            self.circle.memberships.get(user=self.member).status,
        )
