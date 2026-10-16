class FairnessEngine:

    @staticmethod
    def verify_payout_fairness(
        winner,
        eligible_members
    ):

        eligible_ids = {
            member.member_id
            for member in eligible_members
        }

        return winner in eligible_ids