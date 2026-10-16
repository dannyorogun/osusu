from models.treasury import Treasury
from engines.treasury_engine import TreasuryEngine


treasury = Treasury(
    circle_id="C001"
)

TreasuryEngine.deposit(
    treasury,
    "M001",
    50,
    1
)

TreasuryEngine.deposit(
    treasury,
    "M002",
    50,
    1
)

TreasuryEngine.deposit(
    treasury,
    "M003",
    50,
    1
)

print("Balance after contributions:", treasury.balance)

TreasuryEngine.payout(
    treasury,
    "M001",
    100,
    1
)

print("Balance after payout:", treasury.balance)