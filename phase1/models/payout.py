from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from enum import Enum


class PayoutStatus(Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    BLOCKED = "blocked"


@dataclass
class Payout:
    member_id: str
    period: int
    amount: Decimal

    status: PayoutStatus = PayoutStatus.PENDING
    created_at: datetime = datetime.now()
    paid_at: datetime | None = None

    def complete(self):
        self.status = PayoutStatus.COMPLETED
        self.paid_at = datetime.now()

    def block(self):
        self.status = PayoutStatus.BLOCKED