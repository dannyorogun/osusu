"""
Default-risk prediction.

Produces an informational probability only. It must never approve or
reject payouts, move money, or override TreasuryEngine, governance, or
any deterministic financial rule. This module performs no database
writes: features come from MemberFeatureService.compute_current(), which
is read-only.
"""

import numpy as np

from services.ml.model_registry import (
    DEFAULT_MODEL_VERSION,
    ModelRegistry,
)
from services.risk.member_features import (
    MemberFeatureService,
    to_feature_vector,
)


class DefaultRiskPredictor:

    @staticmethod
    def predict(
        *,
        circle,
        member,
        model_version=DEFAULT_MODEL_VERSION,
    ):
        artifact = ModelRegistry.load(model_version)

        features = MemberFeatureService.compute_current(
            circle=circle,
            member=member,
        )

        vector = np.asarray(
            [to_feature_vector(features)],
            dtype=float,
        )

        classes = list(artifact.pipeline.classes_)
        probability = float(
            artifact.pipeline.predict_proba(vector)[0][classes.index(1)]
        )

        return {
            "member_id": str(member.id),
            "circle_id": str(circle.id),
            "default_probability": probability,
            "model_version": artifact.model_version,
            "feature_version": artifact.feature_version,
            "features": {
                name: str(value) for name, value in features.items()
            },
            "informational_only": True,
        }
