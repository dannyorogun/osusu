from models.cycle import Cycle, CycleStatus
from engines.cycle_engine import CycleEngine


cycle = Cycle(
    total_positions=3
)

cycle.status = CycleStatus.READY

print("Initial:", cycle.status.value)

CycleEngine.start_cycle(cycle)

print("Locked:", cycle.financial_locked)
print("Status:", cycle.status.value)

CycleEngine.start_voting(cycle)

print("Voting:", cycle.status.value)

CycleEngine.start_payout(cycle)

print("Payout:", cycle.status.value)

CycleEngine.finish_payout(cycle)

print("Period:", cycle.current_period)
print("Completed payouts:", cycle.completed_payouts)
print("Status:", cycle.status.value)