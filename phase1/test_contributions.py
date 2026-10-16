from datetime import date
from decimal import Decimal

from engines.contribution_engine import ContributionEngine


contributions = []


# Sarah
sarah = ContributionEngine.create_contribution(
    member_id="M001",
    period=1,
    amount=50,
    due_date=date(2026, 8, 30)
)

# Daniel
daniel = ContributionEngine.create_contribution(
    member_id="M002",
    period=1,
    amount=50,
    due_date=date(2026, 8, 30)
)

# John
john = ContributionEngine.create_contribution(
    member_id="M003",
    period=1,
    amount=50,
    due_date=date(2026, 8, 30)
)


contributions.extend([
    sarah,
    daniel,
    john
])


# Sarah pays
ContributionEngine.record_payment(
    sarah,
    50
)

# Daniel pays
ContributionEngine.record_payment(
    daniel,
    50
)


print("Expected: £", ContributionEngine.calculate_expected(contributions))

print("Collected: £", ContributionEngine.calculate_collected(contributions))

print("Shortfall: £", ContributionEngine.calculate_shortfall(contributions))


print("\nContribution statuses:")

for contribution in contributions:
    print(
        contribution.member_id,
        contribution.status.value,
        "Outstanding: £",
        contribution.outstanding_amount
    )