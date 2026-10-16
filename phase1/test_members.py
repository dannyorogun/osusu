from models.member import Member, MemberStatus
from engines.eligibility_engine import EligibilityEngine


sarah = Member(
    name="Sarah",
    member_id="M001",
)

daniel = Member(
    name="Daniel",
    member_id="M002",
)

sarah.status = MemberStatus.ACTIVE
daniel.status = MemberStatus.ACTIVE

members = [sarah, daniel]

# Check initial payout eligibility
eligible = EligibilityEngine.get_payout_eligible_members(members)

print("Payout eligible:")

for member in eligible:
    print(member.name)


# Sarah receives her £1,000 payout
sarah.record_payout(1000)


# Check eligibility again
eligible = EligibilityEngine.get_payout_eligible_members(members)

print("\nPayout eligible after Sarah receives £1,000:")

for member in eligible:
    print(member.name)


# Sarah is still an active member
print("\nSarah still active:", sarah.is_active())

# Sarah can still contribute
print("Sarah can still contribute:", sarah.is_contribution_eligible())