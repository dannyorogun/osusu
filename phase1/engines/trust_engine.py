class TrustEngine:

    @staticmethod
    def complete_cycle(profile):
        profile.completed_cycles += 1

    @staticmethod
    def record_missed_payment(profile):
        profile.missed_payments += 1

    @staticmethod
    def record_default(profile):
        profile.defaults += 1

    @staticmethod
    def record_vote(profile):
        profile.votes_participated += 1

    @staticmethod
    def record_invitation(profile):
        profile.invitations_sent += 1

    @staticmethod
    def record_successful_invite(profile):
        profile.successful_invites += 1

    @staticmethod
    def record_sponsorship(profile):
        profile.sponsored_members += 1