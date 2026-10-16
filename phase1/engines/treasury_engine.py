from decimal import Decimal
from uuid import uuid4

from models.treasury_transaction import (
    TreasuryTransaction,
    TreasuryTransactionType
)


class TreasuryEngine:

    @staticmethod
    def deposit(
        treasury,
        member_id,
        amount,
        period
    ):

        transaction = TreasuryTransaction(
            transaction_id=str(uuid4()),
            circle_id=treasury.circle_id,
            member_id=member_id,
            transaction_type=(
                TreasuryTransactionType.CONTRIBUTION
            ),
            amount=Decimal(str(amount)),
            period=period
        )

        treasury.add_transaction(transaction)

        return transaction

    @staticmethod
    def payout(
        treasury,
        member_id,
        amount,
        period
    ):

        transaction = TreasuryTransaction(
            transaction_id=str(uuid4()),
            circle_id=treasury.circle_id,
            member_id=member_id,
            transaction_type=(
                TreasuryTransactionType.PAYOUT
            ),
            amount=Decimal(str(amount)),
            period=period
        )

        treasury.add_transaction(transaction)

        return transaction

    @staticmethod
    def sponsor(
        treasury,
        sponsor_id,
        amount,
        period
    ):

        transaction = TreasuryTransaction(
            transaction_id=str(uuid4()),
            circle_id=treasury.circle_id,
            member_id=sponsor_id,
            transaction_type=(
                TreasuryTransactionType.SPONSOR
            ),
            amount=Decimal(str(amount)),
            period=period
        )

        treasury.add_transaction(transaction)

        return transaction