from decimal import Decimal
from datetime import date

from models.circle import Circle
from models.member import Member, MemberStatus
from models.cycle import Cycle, CycleStatus
from models.treasury import Treasury

from engines.contribution_engine import ContributionEngine
from engines.eligibility_engine import EligibilityEngine
from engines.treasury_engine import TreasuryEngine
from engines.voting_engine import VotingEngine
from engines.payout_engine import PayoutEngine
from engines.cycle_engine import CycleEngine

class CircleSimulator:

    def __init__(self, circle, members):

        self.circle = circle
        self.members = members

        self.cycle = Cycle(
            total_positions=len(members)
        )

        self.cycle.status = CycleStatus.READY

        self.treasury = Treasury(
            circle_id="SIM001"
        )

        self.period = 1

def start(self):

    print(f"Starting {self.circle.name}")

    CycleEngine.start_cycle(self.cycle)

    while self.cycle.status != CycleStatus.COMPLETED:

        self.run_period()

    print("\nSimulation Complete.")

def run_period(self):

    print(f"\nPeriod {self.period}")

    self.collect_contributions()

    if self.period % 2 == 0:

        self.process_payout()

    self.period += 1

def collect_contributions(self):

    for member in self.members:

        if member.is_contribution_eligible():

            TreasuryEngine.deposit(
                self.treasury,
                member.member_id,
                self.circle.contribution_amount,
                self.period
            )

            member.record_contribution(
                self.circle.contribution_amount
            )

    print("Treasury:", self.treasury.balance)

def process_payout(self):

    eligible = EligibilityEngine.get_payout_eligible_members(
        self.members
    )

    if not eligible:

        return

    votes = []

    for voter in eligible:

        for recipient in eligible:

            if voter != recipient:

                votes.append(
                    VotingEngine.cast_vote(
                        voter,
                        recipient,
                        self.period,
                        eligible
                    )
                )

                break

    if not VotingEngine.calculate_quorum(votes, eligible):

        print("Quorum not reached.")

        return

    winner_id = VotingEngine.determine_winner(votes)

    winner = next(
        member
        for member in eligible
        if member.member_id == winner_id
    )

    payout = PayoutEngine.process_payout(
        winner,
        self.cycle.completed_payouts + 1,
        self.circle.calculate_payout(),
        self.treasury.balance
    )

    if payout.status.value == "completed":

        TreasuryEngine.payout(
            self.treasury,
            winner.member_id,
            self.circle.calculate_payout(),
            self.period
        )

        CycleEngine.finish_payout(self.cycle)

        print(
            f"{winner.name} received £{self.circle.calculate_payout()}"
        )