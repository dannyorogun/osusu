"""
Explicit, reviewed ledger corrections.

The ledger is append-only: a mistake is corrected by a NEW entry, never by
editing or deleting the original. A correction is:

- incoming  -> TransactionType.ADJUSTMENT      (raises the balance)
- outgoing  -> TransactionType.ADJUSTMENT_OUT  (lowers the balance)

Every correction carries a reason, the actor, and what it corrects (a
ledger transaction of the same circle and/or an incident reference), and
an operator-chosen unique reference that makes it idempotent: recording
the same correction twice returns the first entry; reusing a reference for
a different correction is refused.

Only users with the `finance.record_ledger_correction` permission may
record one. There is no HTTP endpoint; operators use the
`record_ledger_correction` management command (backend/OPERATIONS.md).
"""

import re
from decimal import Decimal, InvalidOperation

from django.db import transaction

from finance.models import (
    LedgerTransaction,
    TransactionStatus,
    TransactionType,
)
from services.audit.audit_service import AuditService
from services.finance.ledger_service import LedgerService


PERMISSION = "finance.record_ledger_correction"

DIRECTIONS = {
    "in": TransactionType.ADJUSTMENT,
    "out": TransactionType.ADJUSTMENT_OUT,
}

REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,99}$")

MAX_AMOUNT = Decimal("9999999999.99")  # LedgerTransaction.amount: 12 digits, 2 dp


class CorrectionNotAuthorized(Exception):
    pass


class CorrectionInvalid(ValueError):
    pass


def ledger_reference(reference):
    return f"correction:{reference}"


def _amount(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise CorrectionInvalid("Amount must be a decimal number.")

    if not amount.is_finite() or amount <= 0:
        raise CorrectionInvalid("Amount must be greater than zero.")

    if amount.as_tuple().exponent < -2:
        raise CorrectionInvalid("Amount must have at most 2 decimal places.")

    if amount > MAX_AMOUNT:
        raise CorrectionInvalid("Amount is too large.")

    return amount.quantize(Decimal("0.01"))


class LedgerCorrectionService:

    @staticmethod
    @transaction.atomic
    def record(
        *,
        circle,
        direction,
        amount,
        reason,
        reference,
        actor,
        corrects_transaction=None,
        incident="",
    ):
        """
        Returns (entry, created). Raises CorrectionNotAuthorized or
        CorrectionInvalid; nothing is written in either case.
        """

        if actor is None or not actor.is_active or not actor.has_perm(PERMISSION):
            raise CorrectionNotAuthorized(
                "This user may not record ledger corrections."
            )

        if direction not in DIRECTIONS:
            raise CorrectionInvalid("Direction must be 'in' or 'out'.")

        amount = _amount(amount)

        reason = (reason or "").strip()
        if not reason:
            raise CorrectionInvalid("A reason is required.")
        if len(reason) > 500:
            raise CorrectionInvalid("Reason must be at most 500 characters.")

        reference = (reference or "").strip()
        if not REFERENCE_PATTERN.match(reference):
            raise CorrectionInvalid(
                "Reference must be 3-100 characters: letters, digits, . _ : -"
            )

        incident = (incident or "").strip()
        if corrects_transaction is None and not incident:
            raise CorrectionInvalid(
                "A correction must name the ledger entry or incident it corrects."
            )

        if corrects_transaction is not None:
            if corrects_transaction.circle_id != circle.pk:
                raise CorrectionInvalid(
                    "The corrected entry belongs to a different circle."
                )
            if corrects_transaction.status != TransactionStatus.COMPLETED:
                raise CorrectionInvalid(
                    "Only completed ledger entries can be corrected."
                )

        transaction_type = DIRECTIONS[direction]
        key = ledger_reference(reference)

        existing = (
            LedgerTransaction.objects
            .select_for_update()
            .filter(payment_reference=key)
            .first()
        )

        if existing is not None:
            same = (
                existing.circle_id == circle.pk
                and existing.transaction_type == transaction_type
                and existing.amount == amount
                and existing.metadata.get("corrects_transaction_id")
                == (str(corrects_transaction.id) if corrects_transaction else None)
            )
            if not same:
                raise CorrectionInvalid(
                    "This reference is already used by a different correction."
                )
            return existing, False

        metadata = {
            "kind": "correction",
            "direction": direction,
            "reason": reason,
            "corrects_transaction_id": (
                str(corrects_transaction.id) if corrects_transaction else None
            ),
            "incident": incident or None,
            "actor_id": str(actor.pk),
        }

        entry = LedgerService.record_transaction(
            circle=circle,
            member=None,
            transaction_type=transaction_type,
            amount=amount,
            period_number=(
                corrects_transaction.period_number if corrects_transaction else 0
            ),
            reference=f"CORRECTION-{reference}"[:100],
            payment_reference=key,
            metadata=metadata,
        )

        AuditService.record(
            action="LEDGER_CORRECTION_RECORDED",
            entity_type="LedgerTransaction",
            entity_id=entry.id,
            user=actor,
            metadata={
                "circle_id": str(circle.id),
                "direction": direction,
                "amount": str(amount),
                "reason": reason,
                "reference": reference,
                "corrects_transaction_id": metadata["corrects_transaction_id"],
                "incident": metadata["incident"],
            },
        )

        return entry, True
