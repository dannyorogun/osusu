from dataclasses import dataclass
from datetime import datetime


@dataclass
class Vote:
    voter_id: str
    recipient_id: str
    payout_period: int

    timestamp: datetime = datetime.now()