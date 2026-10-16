from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from finance.models import ContributionObligation
from payments.models import Payment

from services.payments.mock_provider import MockPaymentProvider
from services.payments.payment_service import PaymentService
from services.payments.provider import (
    WebhookPayloadError,
    WebhookVerificationError,
)
from services.payments.webhook_service import PaymentWebhookService


class CreatePaymentView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, obligation_id):

        obligation = get_object_or_404(
            ContributionObligation,
            id=obligation_id,
        )

        if obligation.member != request.user:
            return Response(
                {
                    "detail": "You cannot create a payment for another member."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        payment = PaymentService.create_payment(
            obligation=obligation,
        )

        return Response(
            {
                "id": str(payment.id),
                "provider": payment.provider,
                "provider_payment_id": payment.provider_payment_id,
                "amount": str(payment.amount),
                "currency": payment.currency,
                "status": payment.status,
                "checkout_url": payment.metadata.get(
                    "checkout_url"
                ),
            },
            status=status.HTTP_201_CREATED,
        )


class MockPaymentWebhookView(APIView):
    """
    POST /api/payments/webhooks/mock/ — DEVELOPMENT/TEST ONLY.

    Authentication is the provider's webhook signature (see
    services.payments.mock_provider), not a user session or JWT: any
    Authorization header is ignored.

    - 404 unless OSUSU_MOCK_PAYMENTS_ENABLED is true and a strong
      OSUSU_MOCK_WEBHOOK_SECRET is configured (fails closed).
    - 401 if the signature is missing or wrong. Nothing is parsed or
      written.
    - 400 if the authentic body is malformed or the transition is invalid.
    - 404 if the payment is unknown for this provider.

    Every rejection leaves payments, obligations, ledger and webhook
    records unchanged.
    """

    authentication_classes = []
    permission_classes = []

    def post(self, request):

        if not MockPaymentProvider.webhook_enabled():
            return Response(
                {"detail": "Not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            # Raw bytes: the signature covers exactly what was sent.
            event = MockPaymentProvider().verify_webhook(
                body=request.body,
                headers=request.headers,
            )

        except WebhookVerificationError:
            return Response(
                {"detail": "Webhook signature verification failed."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        except WebhookPayloadError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            webhook = PaymentWebhookService.process(event=event)

        except Payment.DoesNotExist:
            return Response(
                {"detail": "Payment was not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        except ValueError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "event_id": str(webhook.id),
                "provider_event_id": webhook.provider_event_id,
                "processed": webhook.processed,
                "event_type": webhook.event_type,
            },
            status=status.HTTP_200_OK,
        )
