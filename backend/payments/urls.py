from django.urls import path

from payments.views import (
    CreatePaymentView,
    MockPaymentWebhookView,
)


urlpatterns = [
    path(
        "obligations/<uuid:obligation_id>/create/",
        CreatePaymentView.as_view(),
        name="create-payment",
    ),

    path(
        "webhooks/mock/",
        MockPaymentWebhookView.as_view(),
        name="mock-payment-webhook",
    ),
]