"""
Payout window HTTP API over the real payout services. Only the payout
provider is replaced (where a failure is needed); treasury and ledger
effects are real.
"""

import uuid
from decimal import Decimal
from unittest import mock

from django.urls import reverse

from circles.models import Circle, CircleStatus
from circles.tests import CircleAuthorizationFixture
from finance.models import (
    LedgerTransaction,
    Payout,
    PayoutStatus,
    PayoutVote,
    TransactionType,
)
from services.circles.circle_service import CircleService
from services.finance.ledger_service import LedgerService
from services.finance.treasury_engine import TreasuryEngine


class FailingProvider:
    """Connection lost mid-request: the outcome is unknown."""

    name = "failing"

    @staticmethod
    def send(**kwargs):
        raise ConnectionError("down")


class RejectingProvider:
    """The provider's definitive rejection."""

    name = "rejecting"

    @staticmethod
    def send(**kwargs):
        return {"outcome": "rejected", "provider_status": "declined"}


class PayoutApiFixture(CircleAuthorizationFixture):
    """Locked 2-member circle, payout 200.00, quorum 50% (1 vote), 250 funded."""

    def setUp(self):
        super().setUp()
        Circle.objects.filter(pk=self.circle.pk).update(status=CircleStatus.LOCKED)
        for user, ref in ((self.creator, "c"), (self.member, "m")):
            LedgerService.record_transaction(
                circle=self.circle, member=user,
                transaction_type=TransactionType.CONTRIBUTION,
                amount=Decimal("125.00"), period_number=1,
                payment_reference=f"api-{ref}",
            )

    def url(self, name, window=None, circle_id=None):
        kwargs = {"circle_id": circle_id or self.circle.id}
        if window is not None:
            kwargs["window"] = window
        return reverse(name, kwargs=kwargs)

    def open_window(self):
        self.authenticate(self.creator)
        response = self.client.post(self.url("payout-windows"), {}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()["window"]

    def candidate(self, window, user):
        return next(
            str(p.id) for p in Payout.objects.filter(circle=self.circle, payout_window=window["payout_window"])
            if p.member_id == user.pk
        )

    def vote(self, user, candidate_id, window=1):
        self.authenticate(user)
        return self.client.post(
            self.url("payout-window-vote", window), {"candidate_id": candidate_id}, format="json",
        )

    def act(self, name, user, window=1):
        self.authenticate(user)
        return self.client.post(self.url(name, window), {}, format="json")

    def payout_rows(self):
        return LedgerTransaction.objects.filter(
            circle=self.circle, transaction_type=TransactionType.PAYOUT,
        )


class PayoutApiAccessTests(PayoutApiFixture):

    def test_unauthenticated(self):
        self.assertEqual(self.client.get(self.url("payout-windows")).status_code, 401)
        for name in ("payout-window-vote", "payout-window-approve", "payout-window-execute"):
            with self.subTest(name):
                self.assertEqual(self.client.post(self.url(name, 1), {}).status_code, 401)

    def test_outsiders_cannot_learn_anything(self):
        self.open_window()
        self.authenticate(self.outsider)
        for circle_id in (self.circle.id, uuid.uuid4()):
            with self.subTest(str(circle_id)):
                self.assertEqual(
                    self.client.get(self.url("payout-windows", circle_id=circle_id)).json(),
                    {"detail": "Circle not found."},
                )
                for name in ("payout-window-vote", "payout-window-approve", "payout-window-execute"):
                    response = self.client.post(
                        self.url(name, 1, circle_id=circle_id),
                        {"candidate_id": str(uuid.uuid4())}, format="json",
                    )
                    self.assertEqual(response.status_code, 404)

    def test_inactive_members_are_forbidden(self):
        self.open_window()
        for label, user in self.inactive_users.items():
            with self.subTest(label):
                self.authenticate(user)
                self.assertEqual(self.client.get(self.url("payout-windows")).status_code, 403)
                self.assertEqual(
                    self.client.post(self.url("payout-window-vote", 1), {"candidate_id": str(uuid.uuid4())},
                                     format="json").status_code, 403,
                )

    def test_only_creator_opens_approves_and_executes(self):
        self.authenticate(self.member)
        self.assertEqual(self.client.post(self.url("payout-windows"), {}).status_code, 403)
        window = self.open_window()
        self.vote(self.creator, self.candidate(window, self.member))
        self.assertEqual(self.act("payout-window-approve", self.member).status_code, 403)
        self.assertEqual(self.act("payout-window-approve", self.creator).status_code, 200)
        self.assertEqual(self.act("payout-window-execute", self.member).status_code, 403)
        self.assertFalse(self.payout_rows().exists())


class PayoutWindowLifecycleApiTests(PayoutApiFixture):

    def test_no_window_yet(self):
        self.authenticate(self.creator)
        self.assertEqual(
            self.client.get(self.url("payout-windows")).json(),
            {"window": None, "can_open_window": True},
        )
        self.authenticate(self.member)
        self.assertFalse(self.client.get(self.url("payout-windows")).json()["can_open_window"])

    def test_cannot_open_before_lock(self):
        Circle.objects.filter(pk=self.circle.pk).update(status=CircleStatus.READY)
        self.authenticate(self.creator)
        response = self.client.post(self.url("payout-windows"), {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("after the financial lock", response.json()["error"])
        self.assertFalse(Payout.objects.exists())

    def test_open_window_shows_candidates_without_votes(self):
        window = self.open_window()

        self.assertEqual(window["payout_window"], 1)
        self.assertEqual(window["state"], "open")
        self.assertEqual(
            sorted(c["display_name"] for c in window["candidates"]), ["creator", "member"]
        )
        self.assertEqual((window["votes_cast"], window["votes_required"]), (0, 1))
        self.assertTrue(window["can_vote"])
        self.assertTrue(window["can_approve"])
        self.assertFalse(window["can_execute"])
        self.assertIsNone(window["payout"])

    def test_second_window_cannot_open_while_first_unresolved(self):
        self.open_window()
        response = self.client.post(self.url("payout-windows"), {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("still unresolved", response.json()["error"])

    def test_full_journey_with_quorum_and_idempotent_execution(self):
        constitution = self.circle.constitution
        constitution.quorum_percentage = 100  # both eligible members must vote
        constitution.save()
        window = self.open_window()
        target = self.candidate(window, self.member)

        voted = self.vote(self.creator, target)
        self.assertEqual(voted.status_code, 200)
        body = voted.json()["window"]
        self.assertEqual(body["your_vote"], target)
        self.assertFalse(body["can_vote"])
        self.assertEqual((body["votes_cast"], body["votes_required"]), (1, 2))

        early = self.act("payout-window-approve", self.creator)
        self.assertEqual(early.status_code, 400)
        self.assertEqual(early.json()["error"], "Quorum not reached: 1 of 2 required votes.")
        self.assertEqual(early.json()["window"]["state"], "open")

        self.assertEqual(self.vote(self.member, target).status_code, 200)
        approved = self.act("payout-window-approve", self.creator)
        self.assertEqual(approved.status_code, 200)
        body = approved.json()["window"]
        self.assertEqual(body["state"], "approved")
        self.assertEqual(body["payout"]["recipient"], "member")
        self.assertTrue(body["can_execute"])
        self.assertEqual(
            sorted(c["status"] for c in body["candidates"]), ["approved", "cancelled"]
        )

        executed = self.act("payout-window-execute", self.creator)
        self.assertEqual(executed.status_code, 200)
        self.assertEqual(executed.json()["result"], "paid")
        self.assertEqual(executed.json()["window"]["state"], "paid")
        self.assertIsNotNone(executed.json()["window"]["payout"]["paid_at"])

        for _ in range(3):
            again = self.act("payout-window-execute", self.creator)
            self.assertEqual(again.status_code, 200)
            self.assertEqual(again.json()["result"], "already_paid")

        self.assertEqual(self.payout_rows().count(), 1)
        self.assertEqual(self.payout_rows().get().amount, Decimal("200.00"))
        self.assertEqual(TreasuryEngine.current_balance(self.circle), Decimal("50.00"))
        treasury = self.client.get(self.url("circle-treasury")).json()
        self.assertEqual(treasury["balance"], "50.00")

        self.authenticate(self.creator)
        after = self.client.get(self.url("payout-windows")).json()
        self.assertEqual(after["window"]["state"], "paid")
        self.assertTrue(after["can_open_window"])

    def test_repeated_approval_is_idempotent(self):
        window = self.open_window()
        self.vote(self.creator, self.candidate(window, self.member))
        first = self.act("payout-window-approve", self.creator).json()["window"]["payout"]["id"]
        second = self.act("payout-window-approve", self.creator)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["window"]["payout"]["id"], first)

    def test_unknown_outcome_is_202_and_not_retried(self):
        window = self.open_window()
        self.vote(self.creator, self.candidate(window, self.member))
        self.act("payout-window-approve", self.creator)

        with mock.patch(
            "services.payouts.execute_payout_service.get_payout_provider",
            return_value=FailingProvider,
        ):
            unknown = self.act("payout-window-execute", self.creator)

        self.assertEqual(unknown.status_code, 202)
        self.assertEqual(unknown.json()["result"], "unknown")
        body = unknown.json()["window"]
        self.assertEqual(body["state"], "processing")
        self.assertEqual(body["payout"]["attempt_state"], "unknown")
        self.assertFalse(body["can_execute"])
        self.assertFalse(self.payout_rows().exists())

        again = self.act("payout-window-execute", self.creator)
        self.assertEqual(again.status_code, 409)
        self.assertEqual(again.json()["result"], "in_progress")
        self.assertEqual(Payout.objects.get(circle=self.circle, status=PayoutStatus.PROCESSING)
                         .attempts.count(), 1)

        self.authenticate(self.creator)
        treasury = self.client.get(self.url("circle-treasury")).json()
        self.assertEqual(treasury["balance"], "250.00")
        self.assertEqual(treasury["reserved_for_payouts"], "200.00")
        self.assertEqual(treasury["available_balance"], "50.00")

    def test_confirmed_failure_is_502_and_can_be_executed_again(self):
        window = self.open_window()
        self.vote(self.creator, self.candidate(window, self.member))
        self.act("payout-window-approve", self.creator)

        with mock.patch(
            "services.payouts.execute_payout_service.get_payout_provider",
            return_value=RejectingProvider,
        ):
            failed = self.act("payout-window-execute", self.creator)

        self.assertEqual(failed.status_code, 502)
        self.assertEqual(failed.json()["result"], "failed")
        self.assertEqual(failed.json()["window"]["state"], "failed")
        self.assertIsNone(failed.json()["window"]["payout"]["paid_at"])
        self.assertFalse(self.payout_rows().exists())
        self.assertEqual(TreasuryEngine.current_balance(self.circle), Decimal("250.00"))

        retried = self.act("payout-window-execute", self.creator)
        self.assertEqual(retried.status_code, 200)
        self.assertEqual(retried.json()["result"], "paid")
        self.assertEqual(self.payout_rows().count(), 1)

    def test_insufficient_funds(self):
        LedgerService.record_transaction(
            circle=self.circle, member=None, transaction_type=TransactionType.REFUND,
            amount=Decimal("100.00"), period_number=1, payment_reference="api-refund",
        )
        Payout.objects.create(
            circle=self.circle, member=self.member, payout_window=1,
            amount=Decimal("200.00"), status=PayoutStatus.APPROVED,
        )
        response = self.act("payout-window-execute", self.creator)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Treasury cannot fund this payout.")
        self.assertFalse(self.payout_rows().exists())

    def test_execute_without_approval(self):
        self.open_window()
        response = self.act("payout-window-execute", self.creator)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "This payout window has no approved payout.")


class PayoutVoteApiTests(PayoutApiFixture):

    def test_one_vote_per_window(self):
        window = self.open_window()
        self.assertEqual(self.vote(self.creator, self.candidate(window, self.member)).status_code, 200)
        again = self.vote(self.creator, self.candidate(window, self.creator))
        self.assertEqual(again.status_code, 400)
        self.assertEqual(again.json()["error"], "You have already voted in this payout window.")
        self.assertEqual(PayoutVote.objects.count(), 1)

    def test_candidate_outside_window_is_refused(self):
        self.open_window()
        other = CircleService.create_circle(creator=self.outsider, name="Elsewhere")
        foreign = Payout.objects.create(
            circle=other, member=self.outsider, payout_window=1, amount=Decimal("1.00"),
        )
        for candidate_id in (str(foreign.id), str(uuid.uuid4())):
            with self.subTest(candidate_id):
                response = self.vote(self.creator, candidate_id)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"], "Candidate is not in this payout window.")
        self.assertEqual(self.vote(self.creator, str(uuid.uuid4()), window=9).status_code, 400)
        self.assertFalse(PayoutVote.objects.exists())

    def test_invalid_payload(self):
        self.open_window()
        self.authenticate(self.creator)
        for payload in ({}, {"candidate_id": "not-a-uuid"}):
            with self.subTest(payload):
                response = self.client.post(self.url("payout-window-vote", 1), payload, format="json")
                self.assertEqual(response.status_code, 400)
                self.assertIn("candidate_id", response.json())

    def test_voting_after_decision_is_refused(self):
        window = self.open_window()
        self.vote(self.creator, self.candidate(window, self.member))
        self.act("payout-window-approve", self.creator)
        response = self.vote(self.member, self.candidate(window, self.creator))
        self.assertEqual(response.status_code, 400)
        self.assertIn("closed", response.json()["error"])

    def test_no_voter_identities_are_exposed(self):
        window = self.open_window()
        self.vote(self.creator, self.candidate(window, self.member))

        self.authenticate(self.member)
        body = self.client.get(self.url("payout-window", 1)).json()
        text = str(body)

        self.assertIsNone(body["window"]["your_vote"])
        self.assertEqual(body["window"]["votes_cast"], 1)
        self.assertNotIn("voter", text)
        self.assertNotIn("@example.com", text)
        self.assertNotIn(str(self.creator.id), text)
        for candidate in body["window"]["candidates"]:
            self.assertEqual(set(candidate), {"id", "display_name", "is_you", "status"})

    def test_unknown_window_detail_is_404(self):
        self.authenticate(self.member)
        self.assertEqual(self.client.get(self.url("payout-window", 5)).status_code, 404)
        self.authenticate(self.creator)
        self.assertEqual(self.act("payout-window-approve", self.creator, window=5).status_code, 404)
