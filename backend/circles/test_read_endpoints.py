"""
Sprint 28 member-facing read endpoints: my circles, members, obligations,
payouts, treasury and activity. Each circle-scoped endpoint must follow
CircleAccessService: ACTIVE members only, 404 for outsiders (identical to
a nonexistent circle), 403 for invited/left/removed memberships.
"""

import uuid
from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from audit.models import AuditLog
from circles.models import (
    CircleMembership,
    CircleRestructure,
    MembershipStatus,
)
from circles.tests import CircleAuthorizationFixture
from finance.models import (
    ContributionObligation,
    LedgerTransaction,
    ObligationStatus,
    Payout,
    PayoutStatus,
    TransactionStatus,
    TransactionType,
)
from services.audit.audit_service import AuditService
from services.circles.circle_service import CircleService
from services.circles.constitution_service import ConstitutionService
from services.finance.ledger_service import LedgerService
from services.payouts.execute_payout_service import ExecutePayoutService


CIRCLE_ENDPOINTS = [
    "circle-members",
    "circle-obligations",
    "circle-payouts",
    "circle-treasury",
    "circle-activity",
]


class CircleScopedAccessTests(CircleAuthorizationFixture):
    """The same access rules for every new circle-scoped endpoint."""

    def get(self, name, circle_id=None):
        return self.client.get(
            reverse(name, kwargs={"circle_id": circle_id or self.circle.id})
        )

    def test_unauthenticated_requests_are_rejected(self):
        for name in CIRCLE_ENDPOINTS:
            with self.subTest(name):
                self.assertEqual(self.get(name).status_code, 401)

    def test_active_members_are_allowed(self):
        for user in (self.creator, self.member):
            self.authenticate(user)
            for name in CIRCLE_ENDPOINTS:
                with self.subTest(user=user.username, endpoint=name):
                    self.assertEqual(self.get(name).status_code, 200)

    def test_inactive_memberships_are_forbidden(self):
        for label, user in self.inactive_users.items():
            self.authenticate(user)
            for name in CIRCLE_ENDPOINTS:
                with self.subTest(membership=label, endpoint=name):
                    self.assertEqual(self.get(name).status_code, 403)

    def test_unrelated_user_gets_not_found(self):
        self.authenticate(self.outsider)
        for name in CIRCLE_ENDPOINTS:
            with self.subTest(name):
                self.assertEqual(self.get(name).status_code, 404)

    def test_unknown_circle_is_indistinguishable_from_private_circle(self):
        self.authenticate(self.outsider)
        for name in CIRCLE_ENDPOINTS:
            with self.subTest(name):
                private = self.get(name)
                unknown = self.get(name, circle_id=uuid.uuid4())
                self.assertEqual(private.status_code, unknown.status_code)
                self.assertEqual(private.json(), unknown.json())

    def test_endpoints_are_read_only(self):
        self.authenticate(self.member)
        for name in CIRCLE_ENDPOINTS:
            with self.subTest(name):
                response = self.client.post(
                    reverse(name, kwargs={"circle_id": self.circle.id}),
                    {},
                    format="json",
                )
                self.assertEqual(response.status_code, 405)


class MyCirclesTests(CircleAuthorizationFixture):

    def list_circles(self):
        return self.client.get(reverse("create-circle"))

    def test_unauthenticated_request_is_rejected(self):
        self.assertEqual(self.list_circles().status_code, 401)

    def test_lists_only_circles_with_active_membership(self):
        self.authenticate(self.member)
        response = self.list_circles()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.json()],
            [str(self.circle.id)],
        )

    def test_other_users_circles_are_not_listed(self):
        self.authenticate(self.outsider)
        ids = [item["id"] for item in self.list_circles().json()]

        self.assertEqual(ids, [str(self.other_circle.id)])
        self.assertNotIn(str(self.circle.id), ids)

    def test_invited_left_and_removed_memberships_are_not_listed(self):
        for label, user in self.inactive_users.items():
            with self.subTest(label):
                self.authenticate(user)
                self.assertEqual(self.list_circles().json(), [])

    def test_user_with_no_circles_gets_empty_list(self):
        loner = self.make_user("loner")
        self.authenticate(loner)

        response = self.list_circles()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_member_count_counts_active_members_only(self):
        # creator + member are ACTIVE; invited/left/removed are not.
        self.authenticate(self.creator)
        item = self.list_circles().json()[0]

        self.assertEqual(item["member_count"], 2)

    def test_response_fields_and_decimal_strings(self):
        self.authenticate(self.creator)
        item = self.list_circles().json()[0]

        self.assertEqual(
            set(item),
            {"id", "name", "description", "status", "created_at",
             "member_count", "constitution"},
        )
        self.assertEqual(item["constitution"]["contribution_amount"], "50.00")
        self.assertEqual(item["constitution"]["payout_amount"], "200.00")

    def test_newest_circle_first(self):
        second = CircleService.create_circle(
            creator=self.member,
            name="Second",
        )
        self.authenticate(self.member)

        ids = [item["id"] for item in self.list_circles().json()]

        self.assertEqual(ids, [str(second.id), str(self.circle.id)])

    def test_post_still_creates_circle(self):
        self.authenticate(self.member)
        response = self.client.post(
            reverse("create-circle"),
            {
                "name": "Posted",
                "member_limit": 4,
                "contribution_amount": "10.00",
                "payout_amount": "40.00",
                "cycle_length": 4,
                "quorum_percentage": 50,
                "grace_period_days": 3,
                "reserve_amount": "0.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)


class CircleMembersTests(CircleAuthorizationFixture):

    def members(self):
        return self.client.get(
            reverse("circle-members", kwargs={"circle_id": self.circle.id})
        )

    def test_lists_active_and_invited_members_only(self):
        self.authenticate(self.member)
        response = self.members()

        statuses = {item["username"]: item["status"] for item in response.json()}
        self.assertEqual(
            statuses,
            {"creator": "active", "member": "active", "invited": "invited"},
        )

    def test_private_fields_are_not_exposed(self):
        self.authenticate(self.member)
        body = self.members().json()

        for item in body:
            self.assertEqual(
                set(item),
                {"id", "display_name", "username", "status", "joined_at",
                 "constitution_accepted", "constitution_accepted_at",
                 "is_creator", "is_you"},
            )
        self.assertNotIn("@example.com", str(body))

    def test_display_name_prefers_full_name(self):
        self.member.first_name = "Ada"
        self.member.last_name = "Obi"
        self.member.save()
        self.authenticate(self.creator)

        names = {item["username"]: item for item in self.members().json()}

        self.assertEqual(names["member"]["display_name"], "Ada Obi")
        self.assertEqual(names["creator"]["display_name"], "creator")
        self.assertTrue(names["creator"]["is_creator"])
        self.assertFalse(names["member"]["is_creator"])

    def test_is_you_marks_the_requester(self):
        self.authenticate(self.member)
        you = [item["username"] for item in self.members().json() if item["is_you"]]
        self.assertEqual(you, ["member"])

    def test_other_circles_members_are_not_listed(self):
        self.authenticate(self.member)
        usernames = {item["username"] for item in self.members().json()}
        self.assertNotIn("outsider", usernames)


class MyObligationsTests(CircleAuthorizationFixture):

    def setUp(self):
        super().setUp()
        due = timezone.now() + timedelta(days=7)
        self.mine = [
            ContributionObligation.objects.create(
                circle=self.circle,
                member=self.member,
                period_number=period,
                amount_due=Decimal("50.00"),
                due_date=due,
            )
            for period in (2, 1)
        ]
        self.mine[1].status = ObligationStatus.PAID
        self.mine[1].paid_at = timezone.now()
        self.mine[1].save()

        self.theirs = ContributionObligation.objects.create(
            circle=self.circle,
            member=self.creator,
            period_number=1,
            amount_due=Decimal("50.00"),
            due_date=due,
        )
        # The member's obligation in a different circle.
        other = CircleService.create_circle(creator=self.outsider, name="Other")
        self.add_membership(self.member, MembershipStatus.ACTIVE, circle=other)
        self.elsewhere = ContributionObligation.objects.create(
            circle=other,
            member=self.member,
            period_number=1,
            amount_due=Decimal("9.99"),
            due_date=due,
        )

    def obligations(self):
        return self.client.get(
            reverse("circle-obligations", kwargs={"circle_id": self.circle.id})
        )

    def test_returns_only_own_obligations_in_this_circle(self):
        self.authenticate(self.member)
        ids = [item["id"] for item in self.obligations().json()]

        self.assertCountEqual(ids, [str(o.id) for o in self.mine])
        self.assertNotIn(str(self.theirs.id), ids)
        self.assertNotIn(str(self.elsewhere.id), ids)

    def test_creator_does_not_see_other_members_obligations(self):
        self.authenticate(self.creator)
        ids = [item["id"] for item in self.obligations().json()]
        self.assertEqual(ids, [str(self.theirs.id)])

    def test_ordered_by_period_with_decimal_strings(self):
        self.authenticate(self.member)
        body = self.obligations().json()

        self.assertEqual([item["period_number"] for item in body], [1, 2])
        self.assertEqual(body[0]["amount_due"], "50.00")
        self.assertEqual(body[0]["status"], "paid")
        self.assertIsNotNone(body[0]["paid_at"])
        self.assertIsNone(body[1]["paid_at"])
        self.assertEqual(
            set(body[0]),
            {"id", "period_number", "amount_due", "due_date", "status", "paid_at"},
        )

    def test_no_obligations_returns_empty_list(self):
        loner = self.make_user("loner2")
        self.add_membership(loner, MembershipStatus.ACTIVE)
        self.authenticate(loner)
        self.assertEqual(self.obligations().json(), [])

    def test_reading_does_not_change_obligations(self):
        self.authenticate(self.member)
        self.obligations()
        statuses = set(
            ContributionObligation.objects
            .filter(member=self.member, circle=self.circle)
            .values_list("status", flat=True)
        )
        self.assertEqual(statuses, {"pending", "paid"})


class PayoutHistoryTests(CircleAuthorizationFixture):

    def payouts(self):
        return self.client.get(
            reverse("circle-payouts", kwargs={"circle_id": self.circle.id})
        )

    def make_payout(self, member, window, status, amount="200.00"):
        return Payout.objects.create(
            circle=self.circle,
            member=member,
            payout_window=window,
            amount=Decimal(amount),
            status=status,
        )

    def test_no_payouts(self):
        self.authenticate(self.member)
        self.assertEqual(
            self.payouts().json(),
            {"payouts": [], "open_windows": []},
        )

    def test_pending_candidates_are_not_listed_as_payouts(self):
        self.make_payout(self.creator, 1, PayoutStatus.PENDING)
        self.make_payout(self.member, 1, PayoutStatus.PENDING)
        self.authenticate(self.member)

        body = self.payouts().json()

        self.assertEqual(body["payouts"], [])
        self.assertEqual(
            body["open_windows"],
            [{"payout_window": 1, "candidate_count": 2}],
        )
        # Candidate identities are not returned.
        self.assertNotIn("creator", str(body))

    def test_decided_payouts_with_recipient_and_status(self):
        paid = self.make_payout(self.creator, 1, PayoutStatus.PAID)
        paid.paid_at = timezone.now()
        paid.save()
        self.make_payout(self.member, 1, PayoutStatus.PENDING)  # losing candidate
        self.make_payout(self.member, 2, PayoutStatus.APPROVED)
        self.authenticate(self.member)

        body = self.payouts().json()

        self.assertEqual(
            [(p["payout_window"], p["status"], p["recipient"], p["is_you"])
             for p in body["payouts"]],
            [(2, "approved", "member", True), (1, "paid", "creator", False)],
        )
        self.assertEqual(body["payouts"][0]["amount"], "200.00")
        self.assertIsNone(body["payouts"][0]["paid_at"])
        # Window 1 is decided, so it is not an open window.
        self.assertEqual(body["open_windows"], [])

    def test_votes_and_voters_are_not_exposed(self):
        payout = self.make_payout(self.member, 1, PayoutStatus.APPROVED)
        payout.votes.create(member=self.creator)
        self.authenticate(self.member)

        body = self.payouts().json()

        self.assertNotIn("vote", str(body).lower())
        self.assertNotIn("@example.com", str(body))

    def test_other_circles_payouts_are_not_listed(self):
        Payout.objects.create(
            circle=self.other_circle,
            member=self.outsider,
            payout_window=1,
            amount=Decimal("1.00"),
            status=PayoutStatus.PAID,
        )
        self.authenticate(self.member)
        self.assertEqual(self.payouts().json()["payouts"], [])


class TreasurySummaryTests(CircleAuthorizationFixture):

    def treasury(self):
        return self.client.get(
            reverse("circle-treasury", kwargs={"circle_id": self.circle.id})
        )

    def ledger(self, kind, amount, status=TransactionStatus.COMPLETED, circle=None):
        return LedgerTransaction.objects.create(
            circle=circle or self.circle,
            member=self.member,
            transaction_type=kind,
            amount=Decimal(amount),
            period_number=1,
            status=status,
        )

    def test_empty_treasury(self):
        self.authenticate(self.member)
        body = self.treasury().json()

        self.assertEqual(body["balance"], "0.00")
        self.assertEqual(body["completed_transaction_count"], 0)
        self.assertEqual(body["pending_transaction_count"], 0)
        self.assertEqual(body["failed_transaction_count"], 0)
        self.assertEqual(body["reserved_for_payouts"], "0.00")
        self.assertEqual(body["available_balance"], "0.00")
        self.assertEqual(
            set(body["totals"]),
            {"contribution", "payout", "refund", "reserve", "adjustment",
             "adjustment_out", "payout_return"},
        )
        self.assertEqual(body["totals"]["payout"], {"total": "0.00", "count": 0})

    def test_completed_ledger_is_the_only_source_of_balance(self):
        self.ledger(TransactionType.CONTRIBUTION, "50.00")
        self.ledger(TransactionType.CONTRIBUTION, "50.10")
        self.ledger(TransactionType.PAYOUT, "60.00")
        self.ledger(TransactionType.REFUND, "10.05")
        self.ledger(TransactionType.CONTRIBUTION, "999.00", TransactionStatus.PENDING)
        self.ledger(TransactionType.CONTRIBUTION, "500.00", TransactionStatus.FAILED)
        self.ledger(TransactionType.PAYOUT, "300.00", TransactionStatus.PENDING)
        self.ledger(TransactionType.CONTRIBUTION, "7.00", circle=self.other_circle)
        self.authenticate(self.member)

        body = self.treasury().json()

        # 50.00 + 50.10 - 60.00 - 10.05 = 30.05 exactly (Decimal).
        self.assertEqual(body["balance"], "30.05")
        self.assertEqual(body["completed_transaction_count"], 4)
        self.assertEqual(body["pending_transaction_count"], 2)
        self.assertEqual(body["failed_transaction_count"], 1)
        self.assertEqual(
            body["totals"]["contribution"], {"total": "100.10", "count": 2}
        )
        self.assertEqual(body["totals"]["payout"], {"total": "60.00", "count": 1})
        self.assertEqual(body["totals"]["refund"], {"total": "10.05", "count": 1})

    def test_no_ledger_entries_are_exposed(self):
        tx = self.ledger(TransactionType.CONTRIBUTION, "50.00")
        self.authenticate(self.member)
        body = self.treasury().json()
        self.assertNotIn(str(tx.id), str(body))
        self.assertNotIn("member", body)

    def test_completed_payout_reduces_balance(self):
        """
        End to end through ExecutePayoutService (development mock, which
        settles synchronously) and PayoutCompletionService: the ledger row
        must reduce the balance (regression: it used to write a negative
        amount, which TreasuryEngine then added back).
        """
        LedgerService.record_transaction(
            circle=self.circle,
            member=self.member,
            transaction_type=TransactionType.CONTRIBUTION,
            amount=Decimal("250.00"),
            period_number=1,
        )
        payout = Payout.objects.create(
            circle=self.circle,
            member=self.member,
            payout_window=1,
            amount=Decimal("200.00"),
            status=PayoutStatus.APPROVED,
        )
        ExecutePayoutService.execute(payout)
        self.authenticate(self.member)

        body = self.treasury().json()

        self.assertEqual(body["balance"], "50.00")
        self.assertEqual(body["totals"]["payout"], {"total": "200.00", "count": 1})


class ActivityFeedTests(CircleAuthorizationFixture):

    def activity(self):
        return self.client.get(
            reverse("circle-activity", kwargs={"circle_id": self.circle.id})
        )

    def events(self):
        return [item["event"] for item in self.activity().json()]

    def test_circle_creation_is_listed(self):
        self.authenticate(self.member)
        body = self.activity().json()

        self.assertEqual([item["event"] for item in body], ["circle_created"])
        self.assertEqual(body[0]["member"], "creator")
        self.assertEqual(
            set(body[0]),
            {"id", "event", "occurred_at", "member", "payout_window"},
        )

    def test_other_circles_events_are_excluded(self):
        CircleService.create_circle(creator=self.outsider, name="Noise")
        AuditService.record(
            action="CONSTITUTION_ACCEPTED",
            entity_type="CircleMembership",
            entity_id=uuid.uuid4(),
            user=self.outsider,
            metadata={"circle_id": str(self.other_circle.id)},
        )
        self.authenticate(self.member)
        self.assertEqual(self.events(), ["circle_created"])

    def test_supported_events_are_mapped(self):
        CircleMembership.objects.filter(
            circle=self.circle, user=self.member
        ).update(constitution_accepted=False)
        ConstitutionService.accept(circle=self.circle, user=self.member)
        AuditService.record(
            action="INVITATION_CREATED",
            entity_type="CircleInvitation",
            entity_id=uuid.uuid4(),
            user=self.creator,
            metadata={"circle_id": str(self.circle.id), "email": "secret@example.com"},
        )
        AuditService.record(
            action="PAYOUT_WINDOW_CREATED",
            entity_type="Circle",
            entity_id=self.circle.id,
            user=self.creator,
            metadata={"window": 3, "candidates": 2},
        )
        payout = Payout.objects.create(
            circle=self.circle,
            member=self.member,
            payout_window=3,
            amount=Decimal("200.00"),
            status=PayoutStatus.PAID,
        )
        AuditService.record(
            action="PAYOUT_COMPLETED",
            entity_type="Payout",
            entity_id=payout.id,
            user=self.member,
            metadata={"amount": "200.00", "provider_reference": "prov-secret-ref"},
        )
        restructure = CircleRestructure.objects.create(
            circle=self.circle,
            proposed_by=self.creator,
            removed_members=0,
            remaining_members=2,
            new_payout_amount=Decimal("200.00"),
            remaining_periods=2,
        )
        AuditService.record(
            action="RESTRUCTURE_PROPOSED",
            entity_type="CircleRestructure",
            entity_id=restructure.id,
            user=self.creator,
        )
        self.authenticate(self.member)

        body = self.activity().json()
        by_event = {item["event"]: item for item in body}

        self.assertEqual(
            set(by_event),
            {"circle_created", "constitution_accepted", "invitation_sent",
             "payout_window_opened", "payout_completed", "restructure_proposed"},
        )
        self.assertEqual(by_event["payout_window_opened"]["payout_window"], 3)
        self.assertEqual(by_event["payout_completed"]["payout_window"], 3)
        self.assertEqual(by_event["payout_completed"]["member"], "member")
        # Metadata is never passed through.
        self.assertNotIn("secret@example.com", str(body))
        self.assertNotIn("prov-secret-ref", str(body))
        self.assertNotIn("200.00", str(body))

    def test_ledger_and_unknown_events_are_excluded(self):
        LedgerService.record_transaction(
            circle=self.circle,
            member=self.member,
            transaction_type=TransactionType.CONTRIBUTION,
            amount=Decimal("50.00"),
            period_number=1,
            payment_reference="pay-ref-123",
        )
        AuditService.record(
            action="SOMETHING_INTERNAL",
            entity_type="Circle",
            entity_id=self.circle.id,
            metadata={"circle_id": str(self.circle.id)},
        )
        self.assertTrue(
            AuditLog.objects.filter(action="LEDGER_TRANSACTION_CREATED").exists()
        )
        self.authenticate(self.member)

        self.assertEqual(self.events(), ["circle_created"])

    def test_newest_first_and_limited(self):
        for _ in range(55):
            AuditService.record(
                action="CIRCLE_READY",
                entity_type="Circle",
                entity_id=self.circle.id,
                user=self.creator,
            )
        self.authenticate(self.member)

        body = self.activity().json()

        self.assertEqual(len(body), 50)
        times = [item["occurred_at"] for item in body]
        self.assertEqual(times, sorted(times, reverse=True))

    def test_deleted_actor_is_null(self):
        AuditService.record(
            action="CIRCLE_READY",
            entity_type="Circle",
            entity_id=self.circle.id,
            user=None,
        )
        self.authenticate(self.member)
        ready = [item for item in self.activity().json() if item["event"] == "circle_ready"]
        self.assertIsNone(ready[0]["member"])


class CircleReadQueryCountTests(CircleAuthorizationFixture):

    def test_members_query_count_does_not_grow_per_member(self):
        for index in range(5):
            self.add_membership(self.make_user(f"extra{index}"), MembershipStatus.ACTIVE)
        self.authenticate(self.member)
        url = reverse("circle-members", kwargs={"circle_id": self.circle.id})

        # auth user + access check + members (user, circle joined)
        with self.assertNumQueries(3):
            response = self.client.get(url)
        self.assertEqual(len(response.json()), 8)

    def test_my_circles_query_count(self):
        for index in range(3):
            circle = CircleService.create_circle(creator=self.outsider, name=f"C{index}")
            CircleMembership.objects.create(
                circle=circle, user=self.member, status=MembershipStatus.ACTIVE
            )
        self.authenticate(self.member)

        # auth user + one annotated circles query (constitution joined)
        with self.assertNumQueries(2):
            response = self.client.get(reverse("create-circle"))
        self.assertEqual(len(response.json()), 4)
