from dataclasses import dataclass


@dataclass
class TrustEdge:

    inviter_id: str
    invited_id: str

    completed_together: int = 0