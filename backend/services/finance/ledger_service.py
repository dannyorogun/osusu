from django.db import transaction
from django.utils import timezone

from finance.models import (
    LedgerTransaction,
    TransactionStatus,
)

from services.audit.audit_service import AuditService


class LedgerService:

    @staticmethod
    @transaction.atomic
    def record_transaction(
        *,
        circle,
        member,
        transaction_type,
        amount,
        period_number,
        reference="",
        payment_reference=None,
        metadata=None,
    ):
        if payment_reference:
            existing = LedgerTransaction.objects.filter(
                payment_reference=payment_reference
            ).first()

            if existing:
                return existing

        ledger = LedgerTransaction.objects.create(
            circle=circle,
            member=member,
            transaction_type=transaction_type,
            amount=amount,
            period_number=period_number,
            status=TransactionStatus.COMPLETED,
            reference=reference,
            payment_reference=payment_reference,
            metadata=metadata or {},
            completed_at=timezone.now(),
        )

        AuditService.record(
            action="LEDGER_TRANSACTION_CREATED",
            entity_type="LedgerTransaction",
            entity_id=ledger.id,
            user=member,
            metadata={
                "type": transaction_type,
                "amount": str(amount),
                "period": period_number,
                "payment_reference": payment_reference,
            },
        )

        return ledger