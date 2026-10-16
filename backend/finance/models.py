import uuid

from django.conf import settings
from django.db import models
from django.db.models.fields.json import KeyTextTransform


class TransactionType(models.TextChoices):
    """
    Amounts are always positive magnitudes; the type gives the direction
    (services.finance.treasury_engine.INCOMING_TYPES / OUTGOING_TYPES).
    """

    CONTRIBUTION = "contribution", "Contribution"
    PAYOUT = "payout", "Payout"
    REFUND = "refund", "Refund"
    RESERVE = "reserve", "Reserve"
    # Incoming correction (historical name; counted as incoming).
    ADJUSTMENT = "adjustment", "Adjustment"
    # Outgoing correction: reduces the treasury balance.
    ADJUSTMENT_OUT = "adjustment_out", "Adjustment (outgoing)"
    # Incoming: a settled payout came back (returned or reversed). The
    # compensating entry for a PAYOUT row, which is never edited.
    PAYOUT_RETURN = "payout_return", "Payout return"


class TransactionStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"

class ObligationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PAID = "paid", "Paid"
    OVERDUE = "overdue", "Overdue"
    WAIVED = "waived", "Waived"


class ContributionObligation(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    circle = models.ForeignKey(
        "circles.Circle",
        on_delete=models.CASCADE,
        related_name="obligations"
    )

    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="contribution_obligations"
    )

    period_number = models.PositiveIntegerField()

    amount_due = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )

    due_date = models.DateTimeField()

    status = models.CharField(
        max_length=20,
        choices=ObligationStatus.choices,
        default=ObligationStatus.PENDING
    )

    paid_at = models.DateTimeField(
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        unique_together = (
            "circle",
            "member",
            "period_number",
        )

    def __str__(self):
        return (
            f"{self.member.email} "
            f"Period {self.period_number}"
        )

    
class LedgerTransaction(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    circle = models.ForeignKey(
        "circles.Circle",
        on_delete=models.CASCADE,
        related_name="ledger_transactions"
    )

    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ledger_transactions"
    )

    payment_reference = models.CharField(
    max_length=150,
    blank=True,
    unique=True,
    null=True,
)
    
    transaction_type = models.CharField(
        max_length=20,
        choices=TransactionType.choices
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )

    period_number = models.PositiveIntegerField()

    status = models.CharField(
        max_length=20,
        choices=TransactionStatus.choices,
        default=TransactionStatus.PENDING
    )

    reference = models.CharField(
        max_length=100,
        blank=True
    )

    metadata = models.JSONField(
        default=dict,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True
    )

    class Meta:
        ordering = ["created_at"]
        constraints = [
            # Exactly one PAYOUT row per payout, whatever its provider
            # reference (payment_reference is unique on its own).
            models.UniqueConstraint(
                KeyTextTransform("payout_id", "metadata"),
                condition=models.Q(transaction_type="payout"),
                name="ledger_one_payout_row_per_payout",
            ),
            models.UniqueConstraint(
                KeyTextTransform("payout_id", "metadata"),
                condition=models.Q(transaction_type="payout_return"),
                name="ledger_one_return_row_per_payout",
            ),
        ]
        permissions = [
            (
                "record_ledger_correction",
                "Can record a ledger correction entry",
            ),
        ]

    def __str__(self):
        return f"{self.transaction_type} £{self.amount}"

class PayoutStatus(models.TextChoices):
    """
    One Payout row per (circle, member, payout_window). Lifecycle:

    PENDING    -> candidate in an open window (PayoutEngine)
    APPROVED   -> the window's selected recipient, awaiting execution
    PROCESSING -> a PayoutAttempt is live (prepared, submitted or outcome
                  unknown). Money may be moving: the amount stays reserved
                  and the payout is never executed again until the
                  attempt is resolved by provider evidence.
    PAID       -> settlement confirmed; exactly one PAYOUT ledger row
    FAILED     -> the latest attempt was confirmed failed (no money
                  moved); no ledger row; may be executed again
    RETURNED   -> paid, then returned/reversed; one compensating
                  PAYOUT_RETURN row. Paying again is a new decision.
    CANCELLED  -> losing candidate, finalised when the window is decided

    Once a payout has attempts, its status is set only together with its
    latest attempt's state (services.payouts.payout_attempt_service).

    The window is open while it has PENDING rows and no decided row
    (DECIDED_STATUSES); deciding it cancels every remaining PENDING row.
    """

    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    PROCESSING = "processing", "Processing"
    PAID = "paid", "Paid"
    FAILED = "failed", "Failed"
    RETURNED = "returned", "Returned"
    CANCELLED = "cancelled", "Cancelled"


# Selected recipients, whatever happened since (the window is decided).
DECIDED_PAYOUT_STATUSES = (
    PayoutStatus.APPROVED,
    PayoutStatus.PROCESSING,
    PayoutStatus.PAID,
    PayoutStatus.FAILED,
    PayoutStatus.RETURNED,
)

# Selected recipients whose payout is not finished: no new window opens
# while one exists. RETURNED needs a human/governance decision.
UNRESOLVED_PAYOUT_STATUSES = (
    PayoutStatus.APPROVED,
    PayoutStatus.PROCESSING,
    PayoutStatus.FAILED,
    PayoutStatus.RETURNED,
)


class Payout(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    circle = models.ForeignKey(
        "circles.Circle",
        on_delete=models.CASCADE,
        related_name="payouts",
    )

    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="payouts",
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    payout_window = models.PositiveIntegerField()

    status = models.CharField(
        max_length=20,
        choices=PayoutStatus.choices,
        default=PayoutStatus.PENDING,
    )

    approved_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    paid_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        unique_together = (
            "circle",
            "member",
            "payout_window",
        )

    def __str__(self):
        return f"{self.member.email} - £{self.amount}"


class PayoutVote(models.Model):

    payout = models.ForeignKey(
        Payout,
        on_delete=models.CASCADE,
        related_name="votes",
    )

    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        unique_together = (
            "payout",
            "member",
        )

    def __str__(self):
        return f"{self.member.email}"


class PayoutAttemptState(models.TextChoices):
    """
    One attempt = one instruction sent (or possibly sent) to a payout
    provider. Transitions (PayoutAttempt.TRANSITIONS, enforced by
    PayoutAttempt.transition_to):

    PREPARED  -> SUBMITTED | UNKNOWN | SUCCEEDED | FAILED
    SUBMITTED -> SUCCEEDED | FAILED
    UNKNOWN   -> SUBMITTED | SUCCEEDED | FAILED
    SUCCEEDED -> RETURNED
    FAILED, RETURNED: final

    PREPARED  persisted and committed before the provider is called; a
              crash after this point may or may not have sent money.
    SUBMITTED the provider acknowledged the request (reference stored);
              settlement not yet confirmed.
    UNKNOWN   possibly sent, no definitive answer (timeout, reset,
              ambiguous error). Never retried blindly.
    SUCCEEDED authoritative evidence of settlement; one PAYOUT row.
    FAILED    authoritative evidence that no money moved.
    RETURNED  settled, then returned or reversed; one PAYOUT_RETURN row.
    """

    PREPARED = "prepared", "Prepared"
    SUBMITTED = "submitted", "Submitted"
    UNKNOWN = "unknown", "Outcome unknown"
    SUCCEEDED = "succeeded", "Confirmed successful"
    FAILED = "failed", "Confirmed failed"
    RETURNED = "returned", "Returned or reversed"


# Money may be moving: the payout stays PROCESSING and reserved.
LIVE_ATTEMPT_STATES = (
    PayoutAttemptState.PREPARED,
    PayoutAttemptState.SUBMITTED,
    PayoutAttemptState.UNKNOWN,
)


class PayoutAttemptTransitionError(ValueError):
    """A state change the payout-attempt state machine does not permit."""


class PayoutAttempt(models.Model):
    """
    Append-only record of each attempt to pay a Payout. Never deleted
    (PROTECT). Holds no credentials, bank details or provider payloads:
    only identifiers, states, timestamps and short error classes.
    """

    TRANSITIONS = {
        PayoutAttemptState.PREPARED: {
            PayoutAttemptState.SUBMITTED,
            PayoutAttemptState.UNKNOWN,
            PayoutAttemptState.SUCCEEDED,
            PayoutAttemptState.FAILED,
        },
        PayoutAttemptState.SUBMITTED: {
            PayoutAttemptState.SUCCEEDED,
            PayoutAttemptState.FAILED,
        },
        PayoutAttemptState.UNKNOWN: {
            PayoutAttemptState.SUBMITTED,
            PayoutAttemptState.SUCCEEDED,
            PayoutAttemptState.FAILED,
        },
        PayoutAttemptState.SUCCEEDED: {
            PayoutAttemptState.RETURNED,
        },
        PayoutAttemptState.FAILED: set(),
        PayoutAttemptState.RETURNED: set(),
    }

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    payout = models.ForeignKey(
        Payout,
        on_delete=models.PROTECT,
        related_name="attempts",
    )

    attempt_number = models.PositiveIntegerField()

    # Stable and immutable: sent with every request for this attempt.
    idempotency_key = models.CharField(
        max_length=150,
        unique=True,
        editable=False,
    )

    # sha256 of what was asked for (payout, member, amount, currency).
    request_hash = models.CharField(
        max_length=64,
        editable=False,
    )

    state = models.CharField(
        max_length=20,
        choices=PayoutAttemptState.choices,
        default=PayoutAttemptState.PREPARED,
    )

    provider = models.CharField(
        max_length=30,
    )

    provider_reference = models.CharField(
        max_length=150,
        blank=True,
    )

    # Short provider status code last seen, e.g. "executed".
    provider_status = models.CharField(
        max_length=50,
        blank=True,
    )

    # Short classification only (e.g. "TimeoutError", "not_sent"): never
    # an exception message or response body.
    error_class = models.CharField(
        max_length=100,
        blank=True,
    )

    # Identifier of the authoritative evidence for the last decisive
    # transition (provider event id, status lookup, sync response).
    evidence_reference = models.CharField(
        max_length=200,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    submitted_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    returned_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["payout", "attempt_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["payout", "attempt_number"],
                name="payout_attempt_number_unique",
            ),
            # At most one attempt per payout that is live or succeeded:
            # concurrent workers cannot hold two attempts that could each
            # move the payout's money. Only FAILED attempts may coexist.
            models.UniqueConstraint(
                fields=["payout"],
                condition=~models.Q(state="failed"),
                name="payout_one_open_or_successful_attempt",
            ),
            models.UniqueConstraint(
                fields=["provider", "provider_reference"],
                condition=~models.Q(provider_reference=""),
                name="payout_attempt_provider_reference_unique",
            ),
        ]

    def __str__(self):
        return f"{self.payout_id} #{self.attempt_number} {self.state}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            stored = (
                PayoutAttempt.objects
                .filter(pk=self.pk)
                .values("idempotency_key", "request_hash", "payout_id", "attempt_number")
                .first()
            )
            if stored and (
                stored["idempotency_key"] != self.idempotency_key
                or stored["request_hash"] != self.request_hash
                or stored["payout_id"] != self.payout_id
                or stored["attempt_number"] != self.attempt_number
            ):
                raise PayoutAttemptTransitionError(
                    "A payout attempt's identity and idempotency key are immutable."
                )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PayoutAttemptTransitionError("Payout attempts are never deleted.")

    @property
    def is_live(self):
        return self.state in LIVE_ATTEMPT_STATES

    def can_transition_to(self, state):
        return state in self.TRANSITIONS[PayoutAttemptState(self.state)]

    def transition_to(self, state):
        """Set the new state in memory, or raise for a forbidden change."""
        if not self.can_transition_to(state):
            raise PayoutAttemptTransitionError(
                f"Payout attempt cannot move from {self.state} to {state}."
            )
        self.state = state
