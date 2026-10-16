import secrets
from collections import Counter

from models.vote import Vote


class VotingEngine:

    @staticmethod
    def cast_vote(
        voter,
        recipient,
        payout_period,
        eligible_members
    ):

        if voter.member_id == recipient.member_id:
            raise ValueError(
                "Members cannot vote for themselves."
            )

        eligible_ids = {
            member.member_id
            for member in eligible_members
        }

        if voter.member_id not in eligible_ids:
            raise ValueError(
                "Voter is not eligible."
            )

        if recipient.member_id not in eligible_ids:
            raise ValueError(
                "Recipient is not eligible."
            )

        return Vote(
            voter_id=voter.member_id,
            recipient_id=recipient.member_id,
            payout_period=payout_period
        )

    @staticmethod
    def calculate_quorum(
        votes,
        eligible_members,
        minimum_percentage=50
    ):

        if len(eligible_members) == 0:
            return False

        participation = (
            len(votes) / len(eligible_members)
        ) * 100

        return participation >= minimum_percentage

    @staticmethod
    def determine_winner(votes):

        if not votes:
            return None

        counts = Counter(
            vote.recipient_id
            for vote in votes
        )

        highest = max(counts.values())

        tied = [
            member_id
            for member_id, count in counts.items()
            if count == highest
        ]

        winner = secrets.choice(tied)

        return winner

    @staticmethod
        def validate_unique_votes(votes):

        voters = [
            vote.voter_id
            for vote in votes
        ]

        return len(voters) == len(set(voters))
        
        if not VotingEngine.validate_unique_votes(votes):
            raise ValueError("Duplicate votes detected.")