import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from circles.models import (
    Circle,
    CircleConstitution,
    CircleMembership,
    MembershipStatus,
    CircleStatus,
)

from finance.models import (
    ContributionObligation,
    LedgerTransaction,
    ObligationStatus,
)

from payments.models import (
    Payment,
    PaymentStatus,
    WebhookEvent,
)


from services.payments.mock_provider import MockPaymentProvider


User = get_user_model()

# Test-only secret; never used outside the test process.
TEST_WEBHOOK_SECRET = "test-only-mock-webhook-secret-0123456789abcdef"


@override_settings(
    OSUSU_MOCK_PAYMENTS_ENABLED=True,
    OSUSU_MOCK_WEBHOOK_SECRET=TEST_WEBHOOK_SECRET,
)
class PaymentLifecycleTests(APITestCase):

    def post_signed_webhook(self, data):
        """POST a webhook signed exactly as the mock provider would."""
        body = json.dumps(data).encode()

        return self.client.post(
            reverse("mock-payment-webhook"),
            data=body,
            content_type="application/json",
            HTTP_X_OSUSU_MOCK_SIGNATURE=MockPaymentProvider(
                webhook_secret=TEST_WEBHOOK_SECRET,
            ).sign(body),
        )

    def setUp(self):

        # --------------------------------------------------
        # USERS
        # --------------------------------------------------

        self.user = User.objects.create_user(
            username="daniel",
            email="daniel@example.com",
            password="StrongPassword123!",
        )

        self.other_user = User.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password="StrongPassword123!",
        )

        # --------------------------------------------------
        # CIRCLE
        # --------------------------------------------------

        self.circle = Circle.objects.create(
            creator=self.user,
            name="Test Circle",
            description="Payment lifecycle test",
            status=CircleStatus.ACTIVE,
        )

        # --------------------------------------------------
        # CONSTITUTION
        # --------------------------------------------------

        self.constitution = CircleConstitution.objects.create(
            circle=self.circle,
            member_limit=2,
            contribution_amount=Decimal("50.00"),
            contribution_frequency="weekly",
            payout_amount=Decimal("100.00"),
            payout_frequency="biweekly",
            cycle_length=2,
            quorum_percentage=50,
            grace_period_days=7,
            reserve_enabled=False,
            reserve_amount=Decimal("0.00"),
            allow_replacement_before_lock=True,
        )

        # --------------------------------------------------
        # MEMBERSHIP
        # --------------------------------------------------

        CircleMembership.objects.create(
            circle=self.circle,
            user=self.user,
            status=MembershipStatus.ACTIVE,
        )

        # --------------------------------------------------
        # CONTRIBUTION OBLIGATION
        # --------------------------------------------------

        self.obligation = ContributionObligation.objects.create(
            circle=self.circle,
            member=self.user,
            period_number=1,
            amount_due=Decimal("50.00"),
            due_date=self.circle.created_at,
            status=ObligationStatus.PENDING,
        )

        # --------------------------------------------------
        # AUTHENTICATION
        # --------------------------------------------------

        refresh = RefreshToken.for_user(self.user)

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}"
        )

    # ======================================================
    # TEST 1
    # ======================================================

    def test_create_payment(self):

        url = reverse(
            "create-payment",
            kwargs={
                "obligation_id": self.obligation.id,
            },
        )

        response = self.client.post(url)

        self.assertEqual(
            response.status_code,
            201,
        )

        self.assertEqual(
            response.data["status"],
            PaymentStatus.PENDING,
        )

        payment = Payment.objects.get(
            obligation=self.obligation,
        )

        self.assertEqual(
            payment.amount,
            Decimal("50.00"),
        )

        self.assertEqual(
            payment.status,
            PaymentStatus.PENDING,
        )

    # ======================================================
    # TEST 2
    # ======================================================

    def test_failed_payment_does_not_mark_obligation_paid(self):

        payment = Payment.objects.create(
            obligation=self.obligation,
            provider="mock",
            provider_payment_id="mock_payment_failed_001",
            amount=Decimal("50.00"),
            currency="GBP",
            status=PaymentStatus.PENDING,
            idempotency_key="idem_failed_001",
        )

        response = self.post_signed_webhook(
            {
                "provider_event_id": "evt_failed_001",
                "event_type": "payment.failed",
                "payload": {
                    "provider_payment_id": (
                        payment.provider_payment_id
                    ),
                },
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        payment.refresh_from_db()
        self.obligation.refresh_from_db()

        self.assertEqual(
            payment.status,
            PaymentStatus.FAILED,
        )

        self.assertEqual(
            self.obligation.status,
            ObligationStatus.PENDING,
        )

        self.assertIsNone(
            self.obligation.paid_at,
        )

        self.assertEqual(
            LedgerTransaction.objects.count(),
            0,
        )

    # ======================================================
    # TEST 3
    # ======================================================

    def test_successful_payment_completes_obligation_and_creates_ledger(
        self,
    ):

        payment = Payment.objects.create(
            obligation=self.obligation,
            provider="mock",
            provider_payment_id="mock_payment_success_001",
            amount=Decimal("50.00"),
            currency="GBP",
            status=PaymentStatus.PENDING,
            idempotency_key="idem_success_001",
        )

        response = self.post_signed_webhook(
            {
                "provider_event_id": "evt_success_001",
                "event_type": "payment.completed",
                "payload": {
                    "provider_payment_id": (
                        payment.provider_payment_id
                    ),
                },
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        payment.refresh_from_db()
        self.obligation.refresh_from_db()

        self.assertEqual(
            payment.status,
            PaymentStatus.COMPLETED,
        )

        self.assertEqual(
            self.obligation.status,
            ObligationStatus.PAID,
        )

        self.assertIsNotNone(
            self.obligation.paid_at,
        )

        ledger = LedgerTransaction.objects.get(
            payment_reference=payment.provider_payment_id,
        )

        self.assertEqual(
            ledger.transaction_type,
            "contribution",
        )

        self.assertEqual(
            ledger.amount,
            Decimal("50.00"),
        )

        self.assertEqual(
            ledger.period_number,
            1,
        )

    # ======================================================
    # TEST 4
    # ======================================================

    def test_duplicate_webhook_does_not_create_duplicate_ledger(
        self,
    ):

        payment = Payment.objects.create(
            obligation=self.obligation,
            provider="mock",
            provider_payment_id="mock_payment_duplicate_001",
            amount=Decimal("50.00"),
            currency="GBP",
            status=PaymentStatus.PENDING,
            idempotency_key="idem_duplicate_001",
        )

        payload = {
            "provider_event_id": "evt_duplicate_001",
            "event_type": "payment.completed",
            "payload": {
                "provider_payment_id": (
                    payment.provider_payment_id
                ),
            },
        }

        # First webhook
        first_response = self.post_signed_webhook(payload)

        # Same webhook again
        second_response = self.post_signed_webhook(payload)

        self.assertEqual(
            first_response.status_code,
            200,
        )

        self.assertEqual(
            second_response.status_code,
            200,
        )

        # There must only be ONE ledger transaction.
        self.assertEqual(
            LedgerTransaction.objects.filter(
                payment_reference=payment.provider_payment_id,
            ).count(),
            1,
        )

        # There must only be ONE webhook event.
        self.assertEqual(
            WebhookEvent.objects.filter(
                provider_event_id="evt_duplicate_001",
            ).count(),
            1,
        )

        payment.refresh_from_db()

        self.assertEqual(
            payment.status,
            PaymentStatus.COMPLETED,
        )

    # ======================================================
    # TEST 5
    # ======================================================

    def test_user_cannot_create_payment_for_another_member(
        self,
    ):

        other_obligation = ContributionObligation.objects.create(
            circle=self.circle,
            member=self.other_user,
            period_number=1,
            amount_due=Decimal("50.00"),
            due_date=self.circle.created_at,
            status=ObligationStatus.PENDING,
        )

        url = reverse(
            "create-payment",
            kwargs={
                "obligation_id": other_obligation.id,
            },
        )

        response = self.client.post(url)

        self.assertEqual(
            response.status_code,
            403,
        )

        self.assertFalse(
            Payment.objects.filter(
                obligation=other_obligation,
            ).exists()
        )