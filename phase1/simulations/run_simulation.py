from decimal import Decimal

from models.circle import Circle
from models.member import Member, MemberStatus

from simulations.circle_simulator import CircleSimulator


circle = Circle(
    name="Friends Circle",
    contribution_amount=Decimal("50"),
    members=5,
    contribution_frequency="weekly",
    payout_frequency="biweekly",
)

members = []

for i, name in enumerate([
    "Sarah",
    "Daniel",
    "John",
    "Michael",
    "David"
]):

    member = Member(
        name=name,
        member_id=f"M{i+1}"
    )

    member.status = MemberStatus.ACTIVE

    members.append(member)

sim = CircleSimulator(circle, members)

sim.start()