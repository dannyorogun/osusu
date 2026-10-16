import uuid

from django.db import models
from django.utils import timezone


class RiskLevel(models.TextChoices):

    LOW = "low", "Low"

    MEDIUM = "medium", "Medium"

    HIGH = "high", "High"


class RiskAssessment(models.Model):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    circle = models.ForeignKey(
        "circles.Circle",
        on_delete=models.CASCADE,
        related_name="risk_assessments",
    )

    risk_level = models.CharField(
        max_length=20,
        choices=RiskLevel.choices,
    )

    risk_score = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
    )

    payment_rate = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=0,
    )

    overdue_rate = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=0,
    )

    funding_ratio = models.DecimalField(
        max_digits=8,
        decimal_places=4,
        default=0,
    )

    trust_connection_count = models.PositiveIntegerField(
        default=0,
    )

    successful_connection_ratio = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=0,
    )

    model_version = models.CharField(
        max_length=50,
        default="rules-v1",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"{self.circle.name} - "
            f"{self.risk_level}"
        )


class RiskSignal(models.Model):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    assessment = models.ForeignKey(
        RiskAssessment,
        on_delete=models.CASCADE,
        related_name="signals",
    )

    signal_type = models.CharField(
        max_length=100,
    )

    severity = models.CharField(
        max_length=20,
        choices=RiskLevel.choices,
    )

    message = models.TextField()

    value = models.CharField(
        max_length=100,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"{self.signal_type} - "
            f"{self.severity}"
        )

class MemberRiskAssessment(models.Model):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    circle = models.ForeignKey(
        "circles.Circle",
        on_delete=models.CASCADE,
        related_name="member_risk_assessments",
    )

    member = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="risk_assessments",
    )

    risk_level = models.CharField(
        max_length=20,
        choices=RiskLevel.choices,
    )

    risk_score = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
    )

    payment_rate = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=0,
    )

    overdue_rate = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=0,
    )

    completed_cycles = models.PositiveIntegerField(
        default=0,
    )

    payments_made = models.PositiveIntegerField(
        default=0,
    )

    late_payments = models.PositiveIntegerField(
        default=0,
    )

    defaults = models.PositiveIntegerField(
        default=0,
    )

    votes_participated = models.PositiveIntegerField(
        default=0,
    )

    model_version = models.CharField(
        max_length=50,
        default="rules-v1",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):

        return (
            f"{self.member.email} - "
            f"{self.risk_level}"
        )


class MemberRiskSignal(models.Model):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    assessment = models.ForeignKey(
        MemberRiskAssessment,
        on_delete=models.CASCADE,
        related_name="signals",
    )

    signal_type = models.CharField(
        max_length=100,
    )

    severity = models.CharField(
        max_length=20,
        choices=RiskLevel.choices,
    )

    message = models.TextField()

    value = models.CharField(
        max_length=100,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):

        return (
            f"{self.signal_type} - "
            f"{self.severity}"
        )

class MemberRiskFeatureSnapshot(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    circle = models.ForeignKey(
        "circles.Circle",
        on_delete=models.CASCADE,
        related_name="member_risk_feature_snapshots",
    )

    member = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="risk_feature_snapshots",
    )

    assessment = models.ForeignKey(
        MemberRiskAssessment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feature_snapshots",
    )

    payment_rate = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=0,
    )

    overdue_rate = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=0,
    )

    completed_cycles = models.PositiveIntegerField(
        default=0,
    )

    payments_made = models.PositiveIntegerField(
        default=0,
    )

    late_payments = models.PositiveIntegerField(
        default=0,
    )

    defaults = models.PositiveIntegerField(
        default=0,
    )

    votes_participated = models.PositiveIntegerField(
        default=0,
    )

    trust_connections = models.PositiveIntegerField(
        default=0,
    )

    successful_trust_connections = models.PositiveIntegerField(
        default=0,
    )

    snapshot_period = models.PositiveIntegerField(
        null=True,
        blank=True,
)

    prediction_horizon_periods = models.PositiveIntegerField(
        default=1,
)

    feature_version = models.CharField(
        max_length=50,
        default="features-v1",
)

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"{self.member.email} - "
            f"{self.circle.name} - "
            f"{self.created_at}"
        )


class RiskOutcomeType(models.TextChoices):

    DEFAULTED = "defaulted", "Defaulted"

    PAID_ON_TIME = "paid_on_time", "Paid on time"

    PAID_LATE = "paid_late", "Paid late"


class MemberRiskOutcome(models.Model):
    """
    Observed real-world outcome (label) for a feature snapshot.

    One outcome per (snapshot, outcome_type) keeps label recording
    idempotent: replaying the same observation cannot create duplicates.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    snapshot = models.ForeignKey(
        MemberRiskFeatureSnapshot,
        on_delete=models.CASCADE,
        related_name="outcomes",
    )

    circle = models.ForeignKey(
        "circles.Circle",
        on_delete=models.CASCADE,
        related_name="member_risk_outcomes",
    )

    member = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="risk_outcomes",
    )

    outcome_type = models.CharField(
        max_length=30,
        choices=RiskOutcomeType.choices,
    )

    outcome_period = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    observed_at = models.DateTimeField(
        default=timezone.now,
    )

    outcome_version = models.CharField(
        max_length=50,
        default="outcomes-v1",
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    class Meta:
        ordering = ["-observed_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot", "outcome_type"],
                name="unique_member_risk_outcome_per_snapshot_type",
            ),
        ]

    def __str__(self):
        return (
            f"{self.member.email} - "
            f"{self.outcome_type} - "
            f"{self.observed_at}"
        )
