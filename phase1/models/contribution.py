from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum


class ContributionStatus(Enum):
    PENDING = "pending"
    PAID = "paid"
    LATE = "late"
    MISSED = "missed"
    SPONSORED = "sponsored"
    WAIVED = "waived"


@dataclass
class Contribution:
    member_id: str
    period: int
    amount_due: Decimal
    due_date: date

    amount_paid: Decimal = Decimal("0")
    status: ContributionStatus = ContributionStatus.PENDING

    def make_payment(self, amount: Decimal):
        if amount <= 0:
            raise ValueError("Payment must be greater than zero.")

        self.amount_paid += amount

        if self.amount_paid >= self.amount_due:
            self.status = ContributionStatus.PAID

    def mark_late(self):
        if self.status != ContributionStatus.PAID:
            self.status = ContributionStatus.LATE

    def mark_missed(self):
        if self.status != ContributionStatus.PAID:
            self.status = ContributionStatus.MISSED

    @property
    def outstanding_amount(self):
        return max(
            self.amount_due - self.amount_paid,
            Decimal("0")
        )