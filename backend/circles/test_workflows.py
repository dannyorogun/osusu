"""
Sprint 29: the creation-to-lock journey through the existing endpoints,
the trust read, and the cross-circle obligations read.
"""

import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from audit.models import AuditLog
from circles.models import (
    Circle,
    CircleInvitation,
    CircleMembership,
    CircleStatus,
    InvitationStatus,
    MembershipStatus,
)
from circles.tests import CircleAuthorizationFixture
from finance.models import ContributionObligation, ObligationStatus
from services.circles.circle_service import CircleService
from trust.models import TrustEdge


User = get_user_model()


class CircleJourneyTests(TestCase):
    """create -> invite -> accept invitation -> accept constitution ->
    evaluate -> lock, all over HTTP with the real services."""

    def setUp(self):
        self.client = APIClient()
        self.creator = self.user("creator")
        self.joiner = self.user("joiner")
        self.stranger = self.user("stranger")

    def user(self, name):
        return User.objects.create_user(
            username=name, email=f"{name}@example.com", password="Harbour-Lantern-42",
        )

    def as_user(self, user):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}"
        )

    def post(self, name, circle_id=None, data=None, **kwargs):
        kw = {"circle_id": circle_id} if circle_id else kwargs
        return self.client.post(reverse(name, kwargs=kw), data or {}, format="json")

    def create_circle(self, **overrides):
        self.as_user(self.creator)
        response = self.client.post(reverse("create-circle"), {
            "name": "Journey", "member_limit": 2, "contribution_amount": "50.00",
            "payout_amount": "200.00", "contribution_frequency": "weekly",
            "payout_frequency": "biweekly", "cycle_length": 4,
            "quorum_percentage": 50, "grace_period_days": 3,
            "reserve_amount": "0.00", **overrides,
        }, format="json")
        self.assertEqual(response.status_code, 201)
        return response.json()["id"]

    def status_of(self, circle_id):
        return Circle.objects.get(pk=circle_id).status

    def test_full_journey_reaches_locked(self):
        cid = self.create_circle()

        invite = self.post("create-invitation", cid, {"email": "joiner@example.com"})
        self.assertEqual(invite.status_code, 201)
        token = invite.json()["token"]

        self.as_user(self.joiner)
        accepted = self.post("accept-invitation", token=token)
        self.assertEqual(accepted.status_code, 200)

        # Not everyone has accepted the constitution yet.
        self.as_user(self.creator)
        early = self.post("circle-evaluate", cid)
        self.assertEqual(early.status_code, 200)
        self.assertFalse(early.json()["ready"])
        self.assertFalse(early.json()["formation_checks"]["constitution_accepted"])
        self.assertEqual(self.status_of(cid), CircleStatus.RECRUITING)

        early_lock = self.post("circle-lock", cid)
        self.assertEqual(early_lock.status_code, 400)
        self.assertFalse(early_lock.json()["checks"]["circle_ready"])

        for user in (self.creator, self.joiner):
            self.as_user(user)
            self.assertEqual(self.post("accept-constitution", cid).status_code, 200)

        self.as_user(self.creator)
        ready = self.post("circle-evaluate", cid)
        self.assertTrue(ready.json()["ready"])
        self.assertEqual(self.status_of(cid), CircleStatus.READY)

        locked = self.post("circle-lock", cid)
        self.assertEqual(locked.status_code, 200)
        self.assertEqual(locked.json()["circle"]["status"], "locked")
        self.assertIsNotNone(locked.json()["circle"]["financial_locked_at"])
        self.assertEqual(self.status_of(cid), CircleStatus.LOCKED)
        self.assertEqual(
            AuditLog.objects.filter(action="CIRCLE_LOCKED", entity_id=cid).count(), 1
        )

        events = [e["event"] for e in self.client.get(
            reverse("circle-activity", kwargs={"circle_id": cid})
        ).json()]
        self.assertEqual(events[0], "circle_locked")
        self.assertIn("circle_ready", events)
        self.assertIn("member_joined", events)

    def ready_circle(self):
        cid = self.create_circle()
        CircleMembership.objects.create(
            circle_id=cid, user=self.joiner, status=MembershipStatus.ACTIVE,
            joined_at=timezone.now(), constitution_accepted=True,
        )
        CircleMembership.objects.filter(circle_id=cid).update(constitution_accepted=True)
        self.as_user(self.creator)
        self.assertTrue(self.post("circle-evaluate", cid).json()["ready"])
        return cid

    def test_evaluating_a_ready_circle_does_not_re_record(self):
        cid = self.ready_circle()
        self.post("circle-evaluate", cid)
        self.assertEqual(
            AuditLog.objects.filter(action="CIRCLE_READY", entity_id=cid).count(), 1
        )

    def test_evaluation_cannot_unlock_a_locked_circle(self):
        cid = self.ready_circle()
        self.post("circle-lock", cid)

        response = self.post("circle-evaluate", cid)

        self.assertEqual(response.status_code, 400)
        self.assertIn("before the financial lock", response.json()["error"])
        self.assertEqual(self.status_of(cid), CircleStatus.LOCKED)

    def test_second_lock_is_refused(self):
        cid = self.ready_circle()
        self.assertEqual(self.post("circle-lock", cid).status_code, 200)
        response = self.post("circle-lock", cid)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            AuditLog.objects.filter(action="CIRCLE_LOCKED").count(), 1
        )

    def test_only_creator_can_evaluate_and_lock(self):
        cid = self.ready_circle()
        self.as_user(self.joiner)
        self.assertEqual(self.post("circle-evaluate", cid).status_code, 403)
        self.assertEqual(self.post("circle-lock", cid).status_code, 403)
        self.as_user(self.stranger)
        self.assertEqual(self.post("circle-lock", cid).status_code, 404)
        self.assertEqual(self.status_of(cid), CircleStatus.READY)

    def test_unsupported_payout_frequency_fails_checks_instead_of_500(self):
        # payout_frequency is free text. Evaluation already reports it;
        # the lock used to raise KeyError in CashFlowEngine (HTTP 500).
        cid = self.create_circle(payout_frequency="fortnightly")
        CircleMembership.objects.create(
            circle_id=cid, user=self.joiner, status=MembershipStatus.ACTIVE,
            constitution_accepted=True,
        )
        CircleMembership.objects.filter(circle_id=cid).update(constitution_accepted=True)
        self.as_user(self.creator)

        evaluation = self.post("circle-evaluate", cid)
        self.assertEqual(evaluation.status_code, 200)
        self.assertFalse(evaluation.json()["ready"])
        self.assertFalse(
            evaluation.json()["financial_checks"]["checks"]["payout_frequency_supported"]
        )

        lock = self.post("circle-lock", cid)
        self.assertEqual(lock.status_code, 400)
        self.assertFalse(lock.json()["checks"]["cash_flow_valid"])
        self.assertEqual(self.status_of(cid), CircleStatus.RECRUITING)

    def test_invitations_require_active_membership_existing_rule(self):
        # Existing InvitationService rule: any ACTIVE member may invite
        # (not creator-only). Outsiders cannot.
        cid = self.ready_circle()
        Circle.objects.filter(pk=cid).update(status=CircleStatus.RECRUITING)
        self.as_user(self.stranger)
        self.assertEqual(
            self.post("create-invitation", cid, {"email": "x@example.com"}).status_code, 404
        )

    def test_constitution_acceptance_is_recorded_once(self):
        cid = self.create_circle()
        self.post("accept-constitution", cid)
        self.post("accept-constitution", cid)
        membership = CircleMembership.objects.get(circle_id=cid, user=self.creator)
        self.assertTrue(membership.constitution_accepted)
        self.assertEqual(
            AuditLog.objects.filter(action="CONSTITUTION_ACCEPTED").count(), 1
        )

    def test_constitution_cannot_be_accepted_after_lock(self):
        cid = self.ready_circle()
        self.post("circle-lock", cid)
        response = self.post("accept-constitution", cid)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["accepted"])


class InvitationTokenTests(CircleAuthorizationFixture):

    def accept(self, token):
        return self.client.post(
            reverse("accept-invitation", kwargs={"token": token}), {}, format="json",
        )

    def invitation(self, email, **fields):
        return CircleInvitation.objects.create(
            circle=self.circle, inviter=self.creator, email=email, **fields,
        )

    def test_unknown_token_is_not_found(self):
        self.authenticate(self.outsider)
        self.assertEqual(self.accept("0" * 64).status_code, 404)

    def test_expired_token_is_refused_without_joining(self):
        invite = self.invitation(
            "outsider@example.com", expires_at=timezone.now() - timedelta(minutes=1),
        )
        self.authenticate(self.outsider)

        response = self.accept(invite.token)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"accepted": False, "error": "Invitation has expired."})
        self.assertFalse(
            CircleMembership.objects.filter(circle=self.circle, user=self.outsider).exists()
        )

    def test_used_or_revoked_token_is_refused(self):
        for status in (InvitationStatus.ACCEPTED, InvitationStatus.REVOKED):
            with self.subTest(status):
                invite = self.invitation(f"{status}@example.com", status=status)
                self.authenticate(self.outsider)
                response = self.accept(invite.token)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"], "Invitation is no longer valid.")

    def test_token_for_another_email_is_refused(self):
        invite = self.invitation("someone-else@example.com")
        self.authenticate(self.outsider)
        response = self.accept(invite.token)
        self.assertEqual(response.status_code, 400)
        self.assertIn("not sent to your email", response.json()["error"])


class TrustSummaryTests(CircleAuthorizationFixture):

    def trust(self, circle_id=None):
        return self.client.get(
            reverse("circle-trust", kwargs={"circle_id": circle_id or self.circle.id})
        )

    def obligation(self, member, period, status, circle=None):
        return ContributionObligation.objects.create(
            circle=circle or self.circle, member=member, period_number=period,
            amount_due=Decimal("50.00"), due_date=timezone.now(), status=status,
        )

    def test_access_rules(self):
        self.assertEqual(self.trust().status_code, 401)
        for label, user in self.inactive_users.items():
            with self.subTest(label):
                self.authenticate(user)
                self.assertEqual(self.trust().status_code, 403)
        self.authenticate(self.outsider)
        self.assertEqual(self.trust().status_code, 404)
        self.assertEqual(self.trust(uuid.uuid4()).status_code, 404)

    def test_no_outcomes_is_insufficient_data_not_low_trust(self):
        self.obligation(self.member, 1, ObligationStatus.PENDING)
        self.authenticate(self.member)

        body = self.trust().json()

        self.assertEqual(body["data_status"], "insufficient_data")
        self.assertIsNone(body["score"])
        self.assertEqual(len(body["score_unavailable_reasons"]), 3)
        self.assertEqual(body["your_record_in_circle"]["pending"], 1)
        self.assertEqual(body["your_record_in_circle"]["total"], 1)

    def test_own_record_only(self):
        self.obligation(self.member, 1, ObligationStatus.PAID)
        self.obligation(self.member, 2, ObligationStatus.OVERDUE)
        self.obligation(self.creator, 1, ObligationStatus.OVERDUE)
        self.obligation(self.creator, 2, ObligationStatus.OVERDUE)
        self.authenticate(self.member)

        body = self.trust().json()

        self.assertEqual(body["data_status"], "available")
        self.assertEqual(
            body["your_record_in_circle"],
            {"total": 2, "pending": 0, "paid": 1, "overdue": 1, "waived": 0},
        )
        self.assertEqual(
            body["your_history"],
            {"completed_circles": 0, "paid_contributions": 1, "overdue_contributions": 1},
        )

    def test_no_identities_scores_or_network_are_exposed(self):
        TrustEdge.objects.create(inviter=self.creator, invited=self.member)
        self.authenticate(self.member)

        body = self.trust().json()

        self.assertEqual(body["circle"], {"active_members": 2, "invitation_connections": 1})
        self.assertEqual(
            set(body),
            {"data_status", "your_record_in_circle", "your_history", "circle",
             "score", "score_unavailable_reasons"},
        )
        text = str(body)
        for secret in ("creator", "@example.com", str(self.creator.id)):
            self.assertNotIn(secret, text)

    def test_reading_trust_writes_nothing(self):
        from trust.models import TrustProfile

        self.authenticate(self.member)
        self.trust()
        self.assertFalse(TrustProfile.objects.exists())


class MyObligationsAcrossCirclesTests(CircleAuthorizationFixture):

    def mine(self, **params):
        return self.client.get(reverse("my-obligations"), params)

    def obligation(self, member, circle, period, due_days):
        return ContributionObligation.objects.create(
            circle=circle, member=member, period_number=period,
            amount_due=Decimal("50.10"),
            due_date=timezone.now() + timedelta(days=due_days),
        )

    def test_unauthenticated(self):
        self.assertEqual(self.mine().status_code, 401)

    def test_only_own_obligations_in_active_circles_soonest_first(self):
        second = CircleService.create_circle(creator=self.member, name="Second")
        later = self.obligation(self.member, self.circle, 1, due_days=10)
        sooner = self.obligation(self.member, second, 1, due_days=2)
        self.obligation(self.creator, self.circle, 1, due_days=1)

        left_circle = CircleService.create_circle(creator=self.outsider, name="Left")
        self.add_membership(self.member, MembershipStatus.LEFT, circle=left_circle)
        self.obligation(self.member, left_circle, 1, due_days=1)

        self.authenticate(self.member)
        body = self.mine().json()

        self.assertEqual([o["id"] for o in body], [str(sooner.id), str(later.id)])
        self.assertEqual(body[0]["circle"], {"id": str(second.id), "name": "Second"})
        self.assertEqual(body[0]["amount_due"], "50.10")
        self.assertEqual(
            set(body[0]),
            {"id", "period_number", "amount_due", "due_date", "status", "paid_at", "circle"},
        )

    def test_user_parameters_are_ignored(self):
        self.obligation(self.creator, self.circle, 1, due_days=1)
        self.authenticate(self.member)
        for key in ("member", "user", "member_id", "user_id"):
            with self.subTest(key):
                self.assertEqual(self.mine(**{key: str(self.creator.id)}).json(), [])

    def test_empty(self):
        self.authenticate(self.outsider)
        self.assertEqual(self.mine().json(), [])


class RefreshTokenMaintenanceTests(TestCase):

    def test_flushexpiredtokens_removes_only_expired_tokens(self):
        user = User.objects.create_user(
            username="ada", email="ada@example.com", password="Harbour-Lantern-42",
        )
        live = RefreshToken.for_user(user)
        expired = RefreshToken.for_user(user)
        OutstandingToken.objects.filter(jti=expired["jti"]).update(
            expires_at=timezone.now() - timedelta(days=1)
        )

        call_command("flushexpiredtokens")

        remaining = set(OutstandingToken.objects.values_list("jti", flat=True))
        self.assertEqual(remaining, {live["jti"]})

    def test_rotation_is_not_enabled(self):
        # Deliberately off (see backend/OPERATIONS.md): rotation with
        # blacklist-after-rotation lets two concurrent refreshes log the
        # user out. A refresh returns no new refresh token.
        user = User.objects.create_user(
            username="bo", email="bo@example.com", password="Harbour-Lantern-42",
        )
        refresh = str(RefreshToken.for_user(user))
        client = APIClient()
        first = client.post(reverse("token_refresh"), {"refresh": refresh}, format="json")
        second = client.post(reverse("token_refresh"), {"refresh": refresh}, format="json")
        self.assertEqual((first.status_code, second.status_code), (200, 200))
        self.assertNotIn("refresh", first.json())
