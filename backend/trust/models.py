import uuid

from django.conf import settings
from django.db import models


class TrustProfile(models.Model):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trust_profile",
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

    invitations_sent = models.PositiveIntegerField(
        default=0,
    )

    successful_invitations = models.PositiveIntegerField(
        default=0,
    )

    sponsored_members = models.PositiveIntegerField(
        default=0,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self):
        return f"Trust Profile - {self.user.email}"

class TrustEdge(models.Model):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    inviter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trust_edges_created",
    )

    invited = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trust_edges_received",
    )

    completed_together = models.PositiveIntegerField(
        default=0,
    )

    successful_cycles_together = models.PositiveIntegerField(
        default=0,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["inviter", "invited"],
                name="unique_trust_edge",
            ),
        ]

    def __str__(self):
        return (
            f"{self.inviter.email} → "
            f"{self.invited.email}"
        )