import uuid
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


def invitation_expiry():
    return timezone.now() + timedelta(days=7)


class CircleStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    RECRUITING = "recruiting", "Recruiting"
    READY = "ready", "Ready"
    LOCKED = "locked", "Financial Locked"
    ACTIVE = "active", "Active"
    COMPLETED = "completed", "Completed"


class Circle(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_circles"
    )

    name = models.CharField(max_length=120)

    description = models.TextField(blank=True)

    status = models.CharField(
        max_length=20,
        choices=CircleStatus.choices,
        default=CircleStatus.DRAFT
    )

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    financial_locked_at = models.DateTimeField(
        null=True,
        blank=True
)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class CircleConstitution(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    circle = models.OneToOneField(
        Circle,
        on_delete=models.CASCADE,
        related_name="constitution"
    )

    member_limit = models.PositiveIntegerField(
        default=10
    )

    contribution_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    contribution_frequency = models.CharField(
        max_length=20,
        default="weekly"
    )

    payout_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    payout_frequency = models.CharField(
        max_length=20,
        default="biweekly"
    )

    cycle_length = models.PositiveIntegerField(
        default=20
    )

    quorum_percentage = models.PositiveIntegerField(
        default=50
    )

    grace_period_days = models.PositiveIntegerField(
        default=7
    )

    reserve_enabled = models.BooleanField(
        default=False
    )

    reserve_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    allow_replacement_before_lock = models.BooleanField(
        default=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return f"{self.circle.name} Constitution"


class MembershipStatus(models.TextChoices):
    INVITED = "invited", "Invited"
    ACTIVE = "active", "Active"
    LEFT = "left", "Left"
    REMOVED = "removed", "Removed"


class CircleMembership(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    circle = models.ForeignKey(
        Circle,
        on_delete=models.CASCADE,
        related_name="memberships"
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="circle_memberships"
    )

    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_circle_invites"
    )

    status = models.CharField(
        max_length=20,
        choices=MembershipStatus.choices,
        default=MembershipStatus.INVITED
    )

    joined_at = models.DateTimeField(
        null=True,
        blank=True
    )

    constitution_accepted = models.BooleanField(
        default=False
    )

    constitution_accepted_at = models.DateTimeField(
        null=True,
        blank=True
    )

    class Meta:
        unique_together = ("circle", "user")

    def __str__(self):
        return f"{self.user.email} - {self.circle.name}"


class InvitationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ACCEPTED = "accepted", "Accepted"
    EXPIRED = "expired", "Expired"
    REVOKED = "revoked", "Revoked"


class CircleInvitation(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    circle = models.ForeignKey(
        Circle,
        on_delete=models.CASCADE,
        related_name="invitations"
    )

    inviter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sent_invitations"
    )

    email = models.EmailField()

    token = models.CharField(
        max_length=64,
        unique=True,
        default=secrets.token_hex
    )

    status = models.CharField(
        max_length=20,
        choices=InvitationStatus.choices,
        default=InvitationStatus.PENDING
    )

    expires_at = models.DateTimeField(
        default=invitation_expiry
    )

    accepted_at = models.DateTimeField(
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        ordering = ["-created_at"]

    def is_expired(self):
        return timezone.now() > self.expires_at

    def __str__(self):
        return f"{self.email} - {self.circle.name}"

class RestructureStatus(models.TextChoices):
    PROPOSED = "proposed", "Proposed"
    VOTING = "voting", "Voting"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    APPLIED = "applied", "Applied"


class CircleRestructure(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    circle = models.ForeignKey(
        Circle,
        on_delete=models.CASCADE,
        related_name="restructures"
    )

    proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT
    )

    removed_members = models.PositiveIntegerField()

    remaining_members = models.PositiveIntegerField()

    new_payout_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )

    remaining_periods = models.PositiveIntegerField()

    status = models.CharField(
        max_length=20,
        choices=RestructureStatus.choices,
        default=RestructureStatus.PROPOSED
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    applied_at = models.DateTimeField(
        null=True,
        blank=True
    )

    def __str__(self):
        return f"Restructure {self.circle.name}"

class RestructureVote(models.Model):
    restructure = models.ForeignKey(
        CircleRestructure,
        on_delete=models.CASCADE,
        related_name="votes"
    )

    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )

    approved = models.BooleanField()

    voted_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        unique_together = (
            "restructure",
            "member",
        )
    