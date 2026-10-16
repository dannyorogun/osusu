from dataclasses import dataclass
from decimal import Decimal


@dataclass
class Circle:
    name: str
    contribution_amount: Decimal
    members: int
    contribution_frequency: str
    payout_frequency: str

    def calculate_payout(self):
        if self.payout_frequency == "weekly":
            periods = 1
        elif self.payout_frequency == "biweekly":
            periods = 2
        else:
            raise ValueError("Unsupported payout frequency")

        return self.contribution_amount * self.members * periods

    def calculate_cycle_length(self):
        if self.payout_frequency == "weekly":
            payout_interval = 1
        elif self.payout_frequency == "biweekly":
            payout_interval = 2
        else:
            raise ValueError("Unsupported payout frequency")

        return self.members * payout_interval

    def calculate_total_contributions(self):
        return self.contribution_amount * self.members * self.calculate_cycle_length()

    def calculate_total_payouts(self):
        return self.calculate_payout() * self.members

    def is_financially_balanced(self):
        return (
            self.calculate_total_contributions()
            == self.calculate_total_payouts()
        )