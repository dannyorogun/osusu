import uuid

from django.db import models


class PaymentStatus(models.TextChoices):
    CREATED = "created", "Created"
    PENDING = "pending", "Pending"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class Payment(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    obligation = models.OneToOneField(
        "finance.ContributionObligation",
        on_delete=models.PROTECT,
        related_name="payment",
    )

    provider = models.CharField(
        max_length=30,
    )

    provider_payment_id = models.CharField(
        max_length=150,
        blank=True,
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    currency = models.CharField(
        max_length=3,
        default="GBP",
    )

    status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.CREATED,
    )

    idempotency_key = models.CharField(
        max_length=150,
        unique=True,
    )

    provider_reference = models.CharField(
        max_length=150,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    def __str__(self):
        return f"{self.provider} - {self.amount} {self.currency}"


class WebhookEvent(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    provider = models.CharField(
        max_length=30,
    )

    provider_event_id = models.CharField(
        max_length=200,
        unique=True,
    )

    event_type = models.CharField(
        max_length=100,
    )

    processed = models.BooleanField(
        default=False,
    )

    payload = models.JSONField(
        default=dict,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    processed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    def __str__(self):
        return self.provider_event_id