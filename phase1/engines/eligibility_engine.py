class EligibilityEngine:

    @staticmethod
    def get_payout_eligible_members(members):
        return [
            member
            for member in members
            if member.is_payout_eligible()
        ]

    @staticmethod
    def get_voting_eligible_members(members):
        return [
            member
            for member in members
            if member.is_voting_eligible()
        ]

    @staticmethod
    def get_contribution_eligible_members(members):
        return [
            member
            for member in members
            if member.is_contribution_eligible()
        ]