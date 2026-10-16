import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from audit.models import AuditLog
from circles.models import (
    Circle,
    CircleInvitation,
    CircleMembership,
    CircleStatus,
    MembershipStatus,
)
from services.circles.circle_access_service import (
    CircleAccessForbidden,
    CircleAccessService,
    CircleMemberNotFound,
    CircleNotFound,
)
from services.circles.circle_service import CircleService
from services.ml.test_default_risk_model import WRITE_SQL


User = get_user_model()


class CircleAuthorizationFixture(TestCase):
    """
    A financially valid 2-member circle (creator + member) that passes
    formation, integrity and cash-flow checks:
    50.00/week x 2 members x 4 weeks = 400 = 2 biweekly payouts of 200.
    Plus one user in each non-active state and an unrelated outsider who
    is an active member of a different circle.
    """

    def setUp(self):
        self.client = APIClient()

        self.creator = self.make_user("creator")
        self.member = self.make_user("member")
        self.invited = self.make_user("invited")
        self.left = self.make_user("left")
        self.removed = self.make_user("removed")
        self.outsider = self.make_user("outsider")

        self.circle = CircleService.create_circle(
            creator=self.creator,
            name="Secure Circle",
            member_limit=10,
            contribution_amount=Decimal("50.00"),
        )
        constitution = self.circle.constitution
        constitution.contribution_frequency = "weekly"
        constitution.payout_amount = Decimal("200.00")
        constitution.payout_frequency = "biweekly"
        constitution.cycle_length = 4
        constitution.save()

        CircleMembership.objects.filter(
            circle=self.circle,
            user=self.creator,
        ).update(constitution_accepted=True)

        self.add_membership(self.member, MembershipStatus.ACTIVE)
        self.add_membership(self.invited, MembershipStatus.INVITED)
        self.add_membership(self.left, MembershipStatus.LEFT)
        self.add_membership(self.removed, MembershipStatus.REMOVED)

        self.other_circle = CircleService.create_circle(
            creator=self.outsider,
            name="Unrelated Circle",
        )

    def make_user(self, name):
        return User.objects.create_user(
            username=name,
            email=f"{name}@example.com",
            password="StrongPassword123!",
        )

    def add_membership(self, user, membership_status, circle=None):
        return CircleMembership.objects.create(
            circle=circle or self.circle,
            user=user,
            status=membership_status,
            constitution_accepted=True,
        )

    def authenticate(self, user):
        token = RefreshToken.for_user(user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def refresh_circle(self):
        self.circle.refresh_from_db()
        return self.circle

    @property
    def inactive_users(self):
        return {
            "invited": self.invited,
            "left": self.left,
            "removed": self.removed,
        }


class CircleDetailAccessTests(CircleAuthorizationFixture):

    def detail(self, circle_id=None):
        return self.client.get(
            reverse(
                "circle-detail",
                kwargs={"circle_id": circle_id or self.circle.id},
            )
        )

    def test_unauthenticated_request_is_rejected(self):
        response = self.detail()

        self.assertEqual(response.status_code, 401)
        self.assertNotIn("name", response.data)

    def test_active_members_can_view_their_circle(self):
        for user in (self.creator, self.member):
            with self.subTest(user=user.username):
                self.authenticate(user)

                response = self.detail()

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["id"], str(self.circle.id))

    def test_inactive_members_are_forbidden(self):
        for label, user in self.inactive_users.items():
            with self.subTest(status=label):
                self.authenticate(user)

                response = self.detail()

                self.assertEqual(response.status_code, 403)
                self.assertNotIn("name", response.data)
                self.assertNotIn("constitution", response.data)

    def test_unrelated_active_user_cannot_view_circle(self):
        self.authenticate(self.outsider)

        response = self.detail()

        self.assertEqual(response.status_code, 404)
        self.assertNotIn("name", response.data)

    def test_random_uuid_is_indistinguishable_from_private_circle(self):
        self.authenticate(self.outsider)

        private = self.detail()
        missing = self.detail(circle_id=uuid.uuid4())

        self.assertEqual(missing.status_code, 404)
        self.assertEqual(
            (private.status_code, private.data),
            (missing.status_code, missing.data),
        )


class FinancialLockAccessTests(CircleAuthorizationFixture):

    def setUp(self):
        super().setUp()
        Circle.objects.filter(pk=self.circle.pk).update(
            status=CircleStatus.READY,
        )

    def lock(self, circle_id=None):
        return self.client.post(
            reverse(
                "circle-lock",
                kwargs={"circle_id": circle_id or self.circle.id},
            )
        )

    def assert_not_locked(self):
        circle = self.refresh_circle()
        self.assertEqual(circle.status, CircleStatus.READY)
        self.assertIsNone(circle.financial_locked_at)

    def test_unauthenticated_cannot_lock(self):
        self.assertEqual(self.lock().status_code, 401)
        self.assert_not_locked()

    def test_creator_can_lock(self):
        self.authenticate(self.creator)

        response = self.lock()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["locked"])
        circle = self.refresh_circle()
        self.assertEqual(circle.status, CircleStatus.LOCKED)
        self.assertIsNotNone(circle.financial_locked_at)

    def test_unrelated_user_cannot_lock(self):
        self.authenticate(self.outsider)

        response = self.lock()

        self.assertEqual(response.status_code, 404)
        self.assert_not_locked()

    def test_inactive_members_cannot_lock(self):
        for label, user in self.inactive_users.items():
            with self.subTest(status=label):
                self.authenticate(user)

                self.assertEqual(self.lock().status_code, 403)
                self.assert_not_locked()

    def test_non_creator_active_member_cannot_lock(self):
        self.authenticate(self.member)

        response = self.lock()

        self.assertEqual(response.status_code, 403)
        self.assert_not_locked()

    def test_creator_who_left_cannot_lock(self):
        CircleMembership.objects.filter(
            circle=self.circle,
            user=self.creator,
        ).update(status=MembershipStatus.LEFT)
        self.authenticate(self.creator)

        self.assertEqual(self.lock().status_code, 403)
        self.assert_not_locked()


class InvitationAccessTests(CircleAuthorizationFixture):

    def invite(self, email="new@example.com", circle_id=None):
        return self.client.post(
            reverse(
                "create-invitation",
                kwargs={"circle_id": circle_id or self.circle.id},
            ),
            {"email": email},
            format="json",
        )

    def test_unauthenticated_cannot_invite(self):
        self.assertEqual(self.invite().status_code, 401)
        self.assertFalse(CircleInvitation.objects.exists())

    def test_active_members_can_invite(self):
        # Existing InvitationService rule: any active member may invite.
        for user in (self.creator, self.member):
            with self.subTest(user=user.username):
                self.authenticate(user)

                response = self.invite(email=f"guest-of-{user.username}@x.io")

                self.assertEqual(response.status_code, 201)
                self.assertTrue(response.data["invited"])

        self.assertEqual(CircleInvitation.objects.count(), 2)

    def test_unrelated_user_cannot_invite(self):
        self.authenticate(self.outsider)

        response = self.invite()

        self.assertEqual(response.status_code, 404)
        self.assertFalse(CircleInvitation.objects.exists())

    def test_unrelated_user_cannot_learn_circle_status(self):
        # Previously the service's "no longer accepting invitations"
        # error leaked existence and status to outsiders.
        Circle.objects.filter(pk=self.circle.pk).update(
            status=CircleStatus.LOCKED,
        )
        self.authenticate(self.outsider)

        locked = self.invite()
        missing = self.invite(circle_id=uuid.uuid4())

        self.assertEqual(
            (locked.status_code, locked.data),
            (missing.status_code, missing.data),
        )

    def test_inactive_members_cannot_invite(self):
        for label, user in self.inactive_users.items():
            with self.subTest(status=label):
                self.authenticate(user)

                self.assertEqual(self.invite().status_code, 403)

        self.assertFalse(CircleInvitation.objects.exists())

    def test_invitation_acceptance_still_works(self):
        guest = self.make_user("guest")
        self.authenticate(self.creator)
        token = self.invite(email=guest.email).data["token"]

        self.authenticate(guest)
        response = self.client.post(
            reverse("accept-invitation", kwargs={"token": token})
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["accepted"])
        self.assertEqual(
            self.client.get(
                reverse("circle-detail", kwargs={"circle_id": self.circle.id})
            ).status_code,
            200,
        )


class FormationEvaluationAccessTests(CircleAuthorizationFixture):

    def evaluate(self, circle_id=None):
        return self.client.post(
            reverse(
                "circle-evaluate",
                kwargs={"circle_id": circle_id or self.circle.id},
            )
        )

    def assert_unchanged(self, audit_count):
        self.assertEqual(self.refresh_circle().status, CircleStatus.RECRUITING)
        self.assertEqual(AuditLog.objects.count(), audit_count)

    def test_unauthenticated_cannot_evaluate(self):
        audit_count = AuditLog.objects.count()

        self.assertEqual(self.evaluate().status_code, 401)
        self.assert_unchanged(audit_count)

    def test_creator_can_evaluate(self):
        self.authenticate(self.creator)

        response = self.evaluate()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ready"])
        self.assertEqual(self.refresh_circle().status, CircleStatus.READY)

    def test_unrelated_user_cannot_evaluate(self):
        audit_count = AuditLog.objects.count()
        self.authenticate(self.outsider)

        response = self.evaluate()

        self.assertEqual(response.status_code, 404)
        self.assertNotIn("formation_checks", response.data)
        self.assert_unchanged(audit_count)

    def test_non_creator_member_cannot_evaluate(self):
        # A passing evaluation changes status and is audited as the
        # creator's action, so it is creator-only.
        audit_count = AuditLog.objects.count()
        self.authenticate(self.member)

        self.assertEqual(self.evaluate().status_code, 403)
        self.assert_unchanged(audit_count)

    def test_inactive_members_cannot_evaluate(self):
        audit_count = AuditLog.objects.count()

        for label, user in self.inactive_users.items():
            with self.subTest(status=label):
                self.authenticate(user)
                self.assertEqual(self.evaluate().status_code, 403)

        self.assert_unchanged(audit_count)


class ConstitutionAcceptanceAccessTests(CircleAuthorizationFixture):

    def accept(self):
        return self.client.post(
            reverse(
                "accept-constitution",
                kwargs={"circle_id": self.circle.id},
            )
        )

    def test_active_member_can_accept(self):
        self.authenticate(self.member)

        response = self.accept()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["accepted"])

    def test_unrelated_user_gets_not_found(self):
        self.authenticate(self.outsider)

        self.assertEqual(self.accept().status_code, 404)

    def test_inactive_member_is_forbidden(self):
        self.authenticate(self.left)

        self.assertEqual(self.accept().status_code, 403)


class CircleCreationStillWorksTests(CircleAuthorizationFixture):

    def test_creator_of_new_circle_can_access_it(self):
        founder = self.make_user("founder")
        self.authenticate(founder)

        response = self.client.post(
            reverse("create-circle"),
            {
                "name": "Brand New",
                "member_limit": 5,
                "contribution_amount": "25.00",
                "payout_amount": "125.00",
                "cycle_length": 5,
                "quorum_percentage": 50,
                "grace_period_days": 3,
                "reserve_amount": "0.00",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        detail = self.client.get(
            reverse(
                "circle-detail",
                kwargs={"circle_id": response.data["id"]},
            )
        )
        self.assertEqual(detail.status_code, 200)


class CircleAccessServiceTests(CircleAuthorizationFixture):

    def test_membership_states(self):
        self.assertEqual(
            CircleAccessService.require_active_member(
                circle_id=self.circle.id,
                user=self.member,
            ).user,
            self.member,
        )

        for user in self.inactive_users.values():
            with self.assertRaises(CircleAccessForbidden):
                CircleAccessService.require_active_member(
                    circle_id=self.circle.id,
                    user=user,
                )

        for circle_id in (self.circle.id, uuid.uuid4()):
            with self.assertRaises(CircleNotFound):
                CircleAccessService.require_active_member(
                    circle_id=circle_id,
                    user=self.outsider,
                )

    def test_creator_rule(self):
        self.assertEqual(
            CircleAccessService.require_creator(
                circle_id=self.circle.id,
                user=self.creator,
            ).circle,
            self.circle,
        )

        with self.assertRaises(CircleAccessForbidden):
            CircleAccessService.require_creator(
                circle_id=self.circle.id,
                user=self.member,
            )

    def test_target_member_rule(self):
        for member_id in (
            self.left.id,
            self.outsider.id,
            uuid.uuid4(),
        ):
            with self.assertRaises(CircleMemberNotFound):
                CircleAccessService.require_active_target_member(
                    circle_id=self.circle.id,
                    member_id=member_id,
                )

    def test_authorization_checks_are_read_only(self):
        with CaptureQueriesContext(connection) as queries:
            CircleAccessService.require_creator(
                circle_id=self.circle.id,
                user=self.creator,
            )
            CircleAccessService.require_active_target_member(
                circle_id=self.circle.id,
                member_id=self.member.id,
            )
            for user in (self.outsider, self.left):
                try:
                    CircleAccessService.require_active_member(
                        circle_id=self.circle.id,
                        user=user,
                    )
                except (CircleNotFound, CircleAccessForbidden):
                    pass

        writes = [q["sql"] for q in queries if WRITE_SQL.match(q["sql"])]
        self.assertEqual(writes, [])
