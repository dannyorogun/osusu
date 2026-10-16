from decimal import Decimal

from models.circle import Circle


circle = Circle(
    name="Friends Circle",
    contribution_amount=Decimal("50"),
    members=10,
    contribution_frequency="weekly",
    payout_frequency="biweekly",
)

print("Circle:", circle.name)
print("Members:", circle.members)
print("Contribution: £", circle.contribution_amount)
print("Payout: £", circle.calculate_payout())
print("Cycle:", circle.calculate_cycle_length(), "weeks")
print("Total contributions: £", circle.calculate_total_contributions())
print("Total payouts: £", circle.calculate_total_payouts())
print("Financially balanced:", circle.is_financially_balanced())