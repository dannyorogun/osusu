from dataclasses import dataclass, field
from datetime import datetime

from risk.models import (
    MemberRiskFeatureSnapshot,
    RiskOutcomeType,
)

from services.risk.member_features import (
    MEMBER_DEFAULT_FEATURE_NAMES,
    to_feature_vector,
)


@dataclass
class RiskDataset:
    feature_names: list[str]
    X: list[list[float]]
    y: list[int]
    snapshot_ids: list[str]
    snapshot_created_at: list[datetime] = field(
        default_factory=list
    )


class RiskDatasetBuilder:

    FEATURE_NAMES = list(MEMBER_DEFAULT_FEATURE_NAMES)

    @classmethod
    def build_member_default_dataset(cls):

        snapshots = (
            MemberRiskFeatureSnapshot.objects
            .prefetch_related("outcomes")
            .order_by("created_at")
        )

        X = []
        y = []
        snapshot_ids = []
        snapshot_created_at = []

        for snapshot in snapshots:

            outcome = (
                snapshot.outcomes
                .filter(
                    outcome_type__in=[
                        RiskOutcomeType.DEFAULTED,
                        RiskOutcomeType.PAID_ON_TIME,
                    ]
                )
                .order_by("observed_at")
                .first()
            )

            if outcome is None:
                continue

            if outcome.observed_at <= snapshot.created_at:
                continue

            X.append(to_feature_vector(snapshot))

            if outcome.outcome_type == RiskOutcomeType.DEFAULTED:
                y.append(1)
            else:
                y.append(0)

            snapshot_ids.append(str(snapshot.id))
            snapshot_created_at.append(snapshot.created_at)

        return RiskDataset(
            feature_names=list(cls.FEATURE_NAMES),
            X=X,
            y=y,
            snapshot_ids=snapshot_ids,
            snapshot_created_at=snapshot_created_at,
        )