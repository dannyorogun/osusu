from models.member import Member, MemberStatus
from engines.voting_engine import VotingEngine


sarah = Member("Sarah", "M001")
daniel = Member("Daniel", "M002")
john = Member("John", "M003")

for member in [sarah, daniel, john]:
    member.status = MemberStatus.ACTIVE

eligible = [sarah, daniel, john]

votes = []

votes.append(
    VotingEngine.cast_vote(
        sarah,
        daniel,
        1,
        eligible
    )
)

votes.append(
    VotingEngine.cast_vote(
        daniel,
        john,
        1,
        eligible
    )
)

votes.append(
    VotingEngine.cast_vote(
        john,
        daniel,
        1,
        eligible
    )
)

print("Quorum reached:",
      VotingEngine.calculate_quorum(votes, eligible))

winner = VotingEngine.determine_winner(votes)

print("Winner:", winner)