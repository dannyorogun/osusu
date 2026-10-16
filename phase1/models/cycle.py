from dataclasses import dataclass
from enum import Enum


class CycleStatus(Enum):
    RECRUITING = "recruiting"
    READY = "ready"
    LOCKED = "locked"
    ACTIVE = "active"
    VOTING = "voting"
    PAYOUT = "payout"
    COMPLETED = "completed"


@dataclass
class Cycle:
    total_positions: int

    current_period: int = 1
    completed_payouts: int = 0

    status: CycleStatus = CycleStatus.RECRUITING

    financial_locked: bool = False

    def lock(self):
        self.financial_locked = True
        self.status = CycleStatus.LOCKED

    def activate(self):
        self.status = CycleStatus.ACTIVE

    def next_period(self):
        self.current_period += 1

    def complete_payout(self):
        self.completed_payouts += 1

    def complete(self):
        self.status = CycleStatus.COMPLETED