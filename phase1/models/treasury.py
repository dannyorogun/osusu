from dataclasses import dataclass, field
from decimal import Decimal

from models.treasury_transaction import TreasuryTransaction


@dataclass
class Treasury:

    circle_id: str

    transactions: list[TreasuryTransaction] = field(default_factory=list)

    def add_transaction(self, transaction):
        self.transactions.append(transaction)

    @property
    def balance(self):

        balance = Decimal("0")

        for transaction in self.transactions:

            if transaction.transaction_type.name in [
                "CONTRIBUTION",
                "SPONSOR",
                "RESERVE",
            ]:
                balance += transaction.amount

            elif transaction.transaction_type.name in [
                "PAYOUT",
                "REFUND",
            ]:
                balance -= transaction.amount

        return balance