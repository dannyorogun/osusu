from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from enum import Enum


class TreasuryTransactionType(Enum):
    CONTRIBUTION = "contribution"
    SPONSOR = "sponsor"
    PAYOUT = "payout"
    REFUND = "refund"
    RESERVE = "reserve"


@dataclass
class TreasuryTransaction:
    transaction_id: str
    circle_id: str
    member_id: str | None

    transaction_type: TreasuryTransactionType

    amount: Decimal

    period: int

    created_at: datetime = datetime.now()