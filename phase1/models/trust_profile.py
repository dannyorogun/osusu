from dataclasses import dataclass


@dataclass
class TrustProfile:

    member_id: str

    completed_cycles: int = 0
    missed_payments: int = 0
    defaults: int = 0

    invitations_sent: int = 0
    successful_invites: int = 0

    votes_participated: int = 0

    sponsored_members: int = 0