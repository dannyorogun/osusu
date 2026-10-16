from decimal import Decimal

from models.member import Member, MemberStatus
from engines.payout_engine import PayoutEngine


sarah = Member(
    name="Sarah",
    member_id="M001"
)

sarah.status = MemberStatus.ACTIVE

available_balance = Decimal("1000")
payout_amount = Decimal("1000")

payout = PayoutEngine.process_payout(
    member=sarah,
    period=1,
    payout_amount=payout_amount,
    available_balance=available_balance
)

print("Payout status:", payout.status.value)
print("Sarah received: £", sarah.total_received)
print("Payout eligible:", sarah.is_payout_eligible())
print("Contribution eligible:", sarah.is_contribution_eligible())