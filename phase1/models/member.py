from dataclasses import dataclass, field
from enum import Enum
from typing import List
from decimal import Decimal


class MemberStatus(Enum):
    INVITED = "invited"
    JOINED = "joined"
    VERIFIED = "verified"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEFAULTED = "defaulted"
    COMPLETED = "completed"


class ContributionStatus(Enum):
    REGULAR = "regular"
    SPONSORED = "sponsored"
    WAIVED = "waived"
    DEFERRED = "deferred"
    MISSED = "missed"
    DEFAULTED = "defaulted"


@dataclass
class Member:
    name: str
    member_id: str

    status: MemberStatus = MemberStatus.JOINED

    contribution_status: ContributionStatus = (
        ContributionStatus.REGULAR
    )

    payout_received: bool = False

    total_contributed: Decimal = Decimal("0")
    total_received: Decimal = Decimal("0")

    invited_by: str | None = None

    trusted: bool = False

    contribution_history: List[float] = field(default_factory=list)

    def is_active(self):
        return self.status == MemberStatus.ACTIVE

    def is_contribution_eligible(self):
        return self.status in [
            MemberStatus.VERIFIED,
            MemberStatus.ACTIVE,
        ]

    def is_payout_eligible(self):
        return (
            self.status == MemberStatus.ACTIVE
            and not self.payout_received
        )

    def is_voting_eligible(self):
        return (
            self.status == MemberStatus.ACTIVE
            and not self.payout_received
        )

    def record_contribution(self, amount):
        self.contribution_history.append(amount)
        self.total_contributed += amount

    def record_payout(self, amount):
        self.total_received += amount
        self.payout_received = True

    def mark_defaulted(self):
        self.status = MemberStatus.DEFAULTED
        self.contribution_status = ContributionStatus.DEFAULTED