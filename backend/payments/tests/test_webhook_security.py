import hmac
import json
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

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
)
from payments.models import Payment, PaymentStatus, WebhookEvent

from services.payments.mock_provider import (
    SIGNATURE_HEADER,
    MockPaymentProvider,
)
from services.payments.provider import (
    VerifiedWebhook,
    WebhookPayloadError,
    WebhookVerificationError,
)
from services.payments.webhook_service import PaymentWebhookService


User = get_user_model()

# Test-only secrets; never used outside the test process.
TEST_SECRET = "test-only-mock-webhook-secret-0123456789abcdef"
ATTACKER_SECRET = "attacker-guess-secret-0123456789abcdefghijkl"

ENABLED = override_settings(
    OSUSU_MOCK_PAYMENTS_ENABLED=True,
    OSUSU_MOCK_WEBHOOK_SECRET=TEST_SECRET,
)


def body_for(**overrides):
    data = {
        "provider_event_id": "evt_001",
        "event_type": "payment.completed",
        "payload": {"provider_payment_id": "mock_pay_001"},
    }
    data.update(overrides)
    return json.dumps(data).encode()


@ENABLED
class WebhookSecurityTestCase(TestCase):
    """
    One ACTIVE circle, one PENDING obligation and one PENDING mock
    payment ("mock_pay_001"). Every rejection must leave the snapshot()
    of financial state untouched.
    """

    def setUp(self):
        self.client = APIClient()

        self.member = User.objects.create_user(
            username="payer",
            email="payer@example.com",
            password="StrongPassword123!",
        )

        self.circle = Circle.objects.create(
            creator=self.member,
            name="Webhook Circle",
            status=CircleStatus.ACTIVE,
        )
        CircleConstitution.objects.create(
            circle=self.circle,
            member_limit=2,
            contribution_amount=Decimal("50.00"),
            payout_amount=Decimal("100.00"),
            cycle_length=2,
        )
        CircleMembership.objects.create(
            circle=self.circle,
            user=self.member,
            status=MembershipStatus.ACTIVE,
        )

        self.obligation = ContributionObligation.objects.create(
            circle=self.circle,
            member=self.member,
            period_number=1,
            amount_due=Decimal("50.00"),
            due_date=self.circle.created_at,
        )

        self.payment = Payment.objects.create(
            obligation=self.obligation,
            provider="mock",
            provider_payment_id="mock_pay_001",
            amount=Decimal("50.00"),
            status=PaymentStatus.PENDING,
            idempotency_key="idem_001",
        )

    # Helpers

    def sign(self, body, secret=TEST_SECRET):
        return MockPaymentProvider(webhook_secret=secret).sign(body)

    def post(self, body, signature=None, **extra):
        headers = {}
        if signature is not None:
            headers["HTTP_X_OSUSU_MOCK_SIGNATURE"] = signature

        return self.client.post(
            reverse("mock-payment-webhook"),
            data=body,
            content_type="application/json",
            **headers,
            **extra,
        )

    def post_signed(self, body, **extra):
        return self.post(body, signature=self.sign(body), **extra)

    def snapshot(self):
        return {
            "payments": list(
                Payment.objects.order_by("id").values_list(
                    "id", "status", "completed_at",
                )
            ),
            "obligations": list(
                ContributionObligation.objects.order_by("id").values_list(
                    "id", "status", "paid_at",
                )
            ),
            "ledger": list(
                LedgerTransaction.objects.order_by("id").values_list(
                    "id", "amount", "payment_reference",
                )
            ),
            "webhooks": list(
                WebhookEvent.objects.order_by("id").values_list(
                    "id", "processed",
                )
            ),
            "audit": AuditLog.objects.count(),
        }

    def assert_rejected(self, response, status_code):
        self.assertEqual(response.status_code, status_code)
        self.assertEqual(self.snapshot(), self.before)

    def assert_completed_once(self):
        self.payment.refresh_from_db()
        self.obligation.refresh_from_db()

        self.assertEqual(self.payment.status, PaymentStatus.COMPLETED)
        self.assertEqual(self.obligation.status, ObligationStatus.PAID)
        self.assertEqual(LedgerTransaction.objects.count(), 1)
        self.assertEqual(
            LedgerTransaction.objects.get().payment_reference,
            "mock_pay_001",
        )


class SignatureTests(WebhookSecurityTestCase):

    def setUp(self):
        super().setUp()
        self.before = self.snapshot()

    def test_missing_signature_is_rejected(self):
        self.assert_rejected(self.post(body_for()), 401)

    def test_wrong_secret_is_rejected(self):
        body = body_for()

        self.assert_rejected(
            self.post(body, signature=self.sign(body, ATTACKER_SECRET)),
            401,
        )

    def test_malformed_signature_headers_are_rejected(self):
        body = body_for()
        valid_hex = self.sign(body).removeprefix("sha256=")

        for signature in ("", "sha256=", valid_hex, "md5=" + valid_hex,
                          "sha256=" + valid_hex.upper()):
            with self.subTest(signature=signature):
                self.assert_rejected(
                    self.post(body, signature=signature),
                    401,
                )

    def test_signature_for_different_body_is_rejected(self):
        # Replaying a genuine signature on a tampered body fails.
        genuine = body_for(event_type="payment.failed")
        tampered = body_for(event_type="payment.completed")

        self.assert_rejected(
            self.post(tampered, signature=self.sign(genuine)),
            401,
        )

    def test_valid_signature_is_accepted(self):
        response = self.post_signed(body_for())

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["processed"])
        self.assert_completed_once()

    def test_signature_uses_constant_time_comparison(self):
        with mock.patch(
            "services.payments.mock_provider.hmac.compare_digest",
            wraps=hmac.compare_digest,
        ) as compare:
            self.post_signed(body_for())

        compare.assert_called_once()

    def test_response_never_contains_secret(self):
        for response in (
            self.post(body_for()),
            self.post_signed(body_for()),
        ):
            self.assertNotIn(TEST_SECRET, response.content.decode())


class FinancialSafetyTests(WebhookSecurityTestCase):

    def test_valid_webhook_completes_payment_obligation_and_ledger(self):
        response = self.post_signed(body_for())

        self.assertEqual(response.status_code, 200)
        self.assert_completed_once()
        self.assertEqual(
            LedgerTransaction.objects.get().amount,
            Decimal("50.00"),
        )
        self.assertTrue(WebhookEvent.objects.get().processed)
        self.assertTrue(
            AuditLog.objects.filter(
                action="LEDGER_TRANSACTION_CREATED",
            ).exists()
        )

    def test_provider_payment_id_alone_cannot_authenticate(self):
        # The payer knows their provider_payment_id (it is returned by
        # CreatePaymentView) and is even JWT-authenticated.
        self.before = self.snapshot()
        token = RefreshToken.for_user(self.member).access_token

        response = self.post(
            body_for(),
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assert_rejected(response, 401)

    def test_member_cannot_fabricate_payment_through_api(self):
        other = ContributionObligation.objects.create(
            circle=self.circle,
            member=self.member,
            period_number=2,
            amount_due=Decimal("50.00"),
            due_date=self.circle.created_at,
        )
        token = RefreshToken.for_user(self.member).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        created = self.client.post(
            reverse("create-payment", kwargs={"obligation_id": other.id})
        )
        self.assertEqual(created.status_code, 201)
        self.before = self.snapshot()

        forged = body_for(
            provider_event_id="evt_forged",
            payload={
                "provider_payment_id": created.data["provider_payment_id"],
            },
        )

        for signature in (None, self.sign(forged, ATTACKER_SECRET)):
            with self.subTest(signed=signature is not None):
                self.assert_rejected(
                    self.post(forged, signature=signature),
                    401,
                )

        other.refresh_from_db()
        self.assertEqual(other.status, ObligationStatus.PENDING)


class IdempotencyTests(WebhookSecurityTestCase):

    def test_duplicate_event_is_processed_once(self):
        body = body_for()

        first = self.post_signed(body)
        self.obligation.refresh_from_db()
        paid_at = self.obligation.paid_at
        after_first = self.snapshot()

        second = self.post_signed(body)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(self.snapshot(), after_first)
        self.assert_completed_once()
        self.assertEqual(self.obligation.paid_at, paid_at)
        self.assertEqual(WebhookEvent.objects.count(), 1)
        self.assertEqual(
            AuditLog.objects.filter(
                action="LEDGER_TRANSACTION_CREATED",
            ).count(),
            1,
        )

    def test_new_event_for_completed_payment_creates_no_contribution(self):
        self.post_signed(body_for())
        after_first = self.snapshot()

        response = self.post_signed(
            body_for(provider_event_id="evt_002"),
        )

        self.assertEqual(response.status_code, 200)
        self.assert_completed_once()
        self.assertEqual(after_first["ledger"], self.snapshot()["ledger"])
        self.assertEqual(
            after_first["obligations"],
            self.snapshot()["obligations"],
        )


class PayloadValidationTests(WebhookSecurityTestCase):

    def setUp(self):
        super().setUp()
        self.before = self.snapshot()

    def assert_signed_rejected(self, body, status_code):
        self.assert_rejected(self.post_signed(body), status_code)

    def test_missing_provider_payment_id(self):
        for payload in ({}, {"provider_payment_id": ""},
                        {"provider_payment_id": 123}):
            with self.subTest(payload=payload):
                self.assert_signed_rejected(body_for(payload=payload), 400)

    def test_missing_event_id(self):
        for event_id in (None, "", 42):
            with self.subTest(event_id=event_id):
                self.assert_signed_rejected(
                    body_for(provider_event_id=event_id),
                    400,
                )

    def test_unknown_provider_payment(self):
        self.assert_signed_rejected(
            body_for(payload={"provider_payment_id": "mock_pay_unknown"}),
            404,
        )

    def test_payment_of_another_provider_is_not_found(self):
        Payment.objects.filter(pk=self.payment.pk).update(provider="other")
        self.before = self.snapshot()

        self.assert_signed_rejected(body_for(), 404)

    def test_unsupported_event_type(self):
        for event_type in ("payment.refunded", "", None):
            with self.subTest(event_type=event_type):
                self.assert_signed_rejected(
                    body_for(event_type=event_type),
                    400,
                )

    def test_malformed_bodies(self):
        for body in (
            b"",
            b"not json",
            b"\xff\xfe",
            b"[]",
            b'"string"',
            json.dumps({"provider_event_id": "e", "event_type":
                        "payment.completed", "payload": "x"}).encode(),
        ):
            with self.subTest(body=body):
                self.assert_signed_rejected(body, 400)


class StateTransitionTests(WebhookSecurityTestCase):

    def test_completed_payment_cannot_become_failed(self):
        self.post_signed(body_for())
        self.before = self.snapshot()

        self.assert_rejected(
            self.post_signed(
                body_for(
                    provider_event_id="evt_fail",
                    event_type="payment.failed",
                )
            ),
            400,
        )
        self.assert_completed_once()

    def test_failed_payment_cannot_be_completed(self):
        Payment.objects.filter(pk=self.payment.pk).update(
            status=PaymentStatus.FAILED,
        )
        self.before = self.snapshot()

        # Unsigned: rejected before anything is read.
        self.assert_rejected(self.post(body_for()), 401)

        # Even a genuine provider event cannot complete a FAILED payment
        # (existing rule: completion requires PENDING).
        self.assert_rejected(self.post_signed(body_for()), 400)

    def test_only_pending_payment_can_fail(self):
        for payment_status in (PaymentStatus.CREATED,
                               PaymentStatus.CANCELLED):
            with self.subTest(status=payment_status):
                Payment.objects.filter(pk=self.payment.pk).update(
                    status=payment_status,
                )
                self.before = self.snapshot()

                self.assert_rejected(
                    self.post_signed(
                        body_for(event_type="payment.failed"),
                    ),
                    400,
                )

    def test_pending_payment_can_fail_idempotently(self):
        body = body_for(event_type="payment.failed")

        self.assertEqual(self.post_signed(body).status_code, 200)
        self.assertEqual(
            self.post_signed(body_for(
                provider_event_id="evt_fail_again",
                event_type="payment.failed",
            )).status_code,
            200,
        )

        self.payment.refresh_from_db()
        self.obligation.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.FAILED)
        self.assertEqual(self.obligation.status, ObligationStatus.PENDING)
        self.assertFalse(LedgerTransaction.objects.exists())


class EnvironmentGatingTests(WebhookSecurityTestCase):

    def setUp(self):
        super().setUp()
        self.before = self.snapshot()

    def test_disabled_flag_hides_endpoint_even_with_valid_signature(self):
        with override_settings(OSUSU_MOCK_PAYMENTS_ENABLED=False):
            self.assert_rejected(self.post_signed(body_for()), 404)

    def test_missing_or_weak_secret_keeps_endpoint_disabled(self):
        for secret in ("", "short-secret", "change-me-in-development"):
            with self.subTest(secret=secret):
                with override_settings(OSUSU_MOCK_WEBHOOK_SECRET=secret):
                    self.assertFalse(MockPaymentProvider.webhook_enabled())
                    self.assert_rejected(
                        self.post(body_for(), signature=self.sign(
                            body_for(),
                            secret or "x",
                        )),
                        404,
                    )

    def test_non_boolean_flag_does_not_enable(self):
        for flag in ("true", 1, "yes"):
            with self.subTest(flag=flag):
                with override_settings(OSUSU_MOCK_PAYMENTS_ENABLED=flag):
                    self.assertFalse(MockPaymentProvider.webhook_enabled())


class ProviderAndServiceUnitTests(WebhookSecurityTestCase):

    def test_provider_rejects_unconfigured_secret(self):
        with self.assertRaises(WebhookVerificationError):
            MockPaymentProvider(webhook_secret="").verify_webhook(
                body=body_for(),
                headers={SIGNATURE_HEADER: "sha256=abc"},
            )

    def test_provider_returns_verified_event(self):
        body = body_for()

        event = MockPaymentProvider(webhook_secret=TEST_SECRET).verify_webhook(
            body=body,
            headers={SIGNATURE_HEADER: self.sign(body)},
        )

        self.assertEqual(
            event,
            VerifiedWebhook(
                provider="mock",
                provider_event_id="evt_001",
                event_type="payment.completed",
                provider_payment_id="mock_pay_001",
                payload={"provider_payment_id": "mock_pay_001"},
            ),
        )

    def test_provider_verifies_before_parsing(self):
        with self.assertRaises(WebhookVerificationError):
            MockPaymentProvider(webhook_secret=TEST_SECRET).verify_webhook(
                body=b"not json",
                headers={SIGNATURE_HEADER: "sha256=" + "0" * 64},
            )

        body = b"not json"
        with self.assertRaises(WebhookPayloadError):
            MockPaymentProvider(webhook_secret=TEST_SECRET).verify_webhook(
                body=body,
                headers={SIGNATURE_HEADER: self.sign(body)},
            )

    def test_service_refuses_unverified_input(self):
        before = self.snapshot()

        with self.assertRaises(TypeError):
            PaymentWebhookService.process(
                event={
                    "provider_event_id": "evt_001",
                    "event_type": "payment.completed",
                    "provider_payment_id": "mock_pay_001",
                }
            )

        self.assertEqual(self.snapshot(), before)
