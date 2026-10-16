from decimal import Decimal

from django.db.models import Count, Sum

from finance.models import (
    LedgerTransaction,
    Payout,
    PayoutStatus,
    TransactionType,
    TransactionStatus,
)


# Every TransactionType must appear in exactly one of these (tested).
INCOMING_TYPES = (
    TransactionType.CONTRIBUTION,
    TransactionType.RESERVE,
    TransactionType.ADJUSTMENT,
    TransactionType.PAYOUT_RETURN,
)

OUTGOING_TYPES = (
    TransactionType.PAYOUT,
    TransactionType.REFUND,
    TransactionType.ADJUSTMENT_OUT,
)


class TreasuryEngine:

    @staticmethod
    def current_balance(circle):

        completed = LedgerTransaction.objects.filter(
            circle=circle,
            status=TransactionStatus.COMPLETED,
        )

        incoming = Decimal("0")
        outgoing = Decimal("0")

        for transaction in completed:

            if transaction.transaction_type in INCOMING_TYPES:
                incoming += transaction.amount

            elif transaction.transaction_type in OUTGOING_TYPES:
                outgoing += transaction.amount

        return incoming - outgoing

    @staticmethod
    def reserved_for_payouts(circle, exclude=None):
        """
        Amounts of payouts whose money may be moving (PROCESSING: an
        attempt is prepared, submitted or of unknown outcome). They have
        no ledger row yet, so current_balance() still includes them; they
        are reserved until the attempt is resolved by provider evidence.
        """
        payouts = Payout.objects.filter(
            circle=circle,
            status=PayoutStatus.PROCESSING,
        )
        if exclude is not None:
            payouts = payouts.exclude(pk=exclude.pk)
        return payouts.aggregate(total=Sum("amount"))["total"] or Decimal("0")

    @staticmethod
    def available_balance(circle, exclude=None):
        """Balance not reserved for a payout in progress."""
        return (
            TreasuryEngine.current_balance(circle)
            - TreasuryEngine.reserved_for_payouts(circle, exclude=exclude)
        )

    @staticmethod
    def ledger_totals(circle):
        """
        Read-only per-type totals of COMPLETED ledger transactions, using
        the same incoming/outgoing classification as current_balance().
        Every TransactionType is present (Decimal("0") when unused).
        """
        rows = (
            LedgerTransaction.objects
            .filter(
                circle=circle,
                status=TransactionStatus.COMPLETED,
            )
            .values("transaction_type")
            .annotate(total=Sum("amount"), count=Count("id"))
        )

        totals = {
            choice: {"total": Decimal("0"), "count": 0}
            for choice in TransactionType.values
        }

        for row in rows:
            totals[row["transaction_type"]] = {
                "total": row["total"],
                "count": row["count"],
            }

        return totals

    @staticmethod
    def summary(circle):

        completed = LedgerTransaction.objects.filter(
            circle=circle,
            status=TransactionStatus.COMPLETED,
        )

        return {
            "balance": TreasuryEngine.current_balance(circle),
            "transactions": completed.count(),
        }