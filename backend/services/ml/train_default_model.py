"""
Baseline default-risk model training.

Pipeline: RiskDatasetBuilder -> TimeAwareDatasetSplitter -> validate ->
StandardScaler + LogisticRegression -> evaluate on the later (test) period
-> persist via ModelRegistry.

No random splitting or shuffling: the model only ever learns from rows
created before every row it is evaluated on.
"""

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
from django.utils import timezone
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from services.ml.evaluate_default_model import (
    POSITIVE_CLASS,
    compute_classification_metrics,
)
from services.ml.model_registry import (
    DEFAULT_MODEL_VERSION,
    ModelArtifact,
    ModelRegistry,
)
from services.risk.dataset_builder import RiskDatasetBuilder
from services.risk.member_features import (
    FEATURE_VERSION,
    MEMBER_DEFAULT_FEATURE_NAMES,
)
from services.risk.time_aware_splitter import TimeAwareDatasetSplitter


REQUIRED_CLASSES = {0, 1}


class InsufficientTrainingDataError(ValueError):
    """Not enough labelled history to train or evaluate honestly."""


@dataclass
class TrainingResult:
    model_version: str
    artifact_path: Path
    train_size: int
    test_size: int
    split_timestamp: datetime | None
    metrics: dict


class DefaultModelTrainer:

    @staticmethod
    def build_pipeline():
        return Pipeline([
            ("scaler", StandardScaler()),
            (
                "classifier",
                LogisticRegression(
                    max_iter=1000,
                    class_weight="balanced",
                ),
            ),
        ])

    @classmethod
    def train(
        cls,
        *,
        model_version=DEFAULT_MODEL_VERSION,
        train_ratio=TimeAwareDatasetSplitter.DEFAULT_TRAIN_RATIO,
        require_evaluation=True,
    ) -> TrainingResult:

        dataset = RiskDatasetBuilder.build_member_default_dataset()

        cls._validate_dataset(dataset)

        split = TimeAwareDatasetSplitter.split(
            dataset,
            train_ratio=train_ratio,
        )

        cls._validate_split(
            split,
            require_evaluation=require_evaluation,
        )

        X_train = np.asarray(split.train.X, dtype=float)
        y_train = np.asarray(split.train.y, dtype=int)

        pipeline = cls.build_pipeline()
        pipeline.fit(X_train, y_train)

        metrics = cls._evaluate(pipeline, split.test)

        artifact = ModelArtifact(
            model_version=model_version,
            feature_names=list(MEMBER_DEFAULT_FEATURE_NAMES),
            feature_version=FEATURE_VERSION,
            pipeline=pipeline,
            trained_at=timezone.now(),
            train_size=len(split.train.y),
            test_size=len(split.test.y),
            metrics=metrics,
            split_timestamp=split.split_timestamp,
            train_start=min(split.train.snapshot_created_at),
            train_end=max(split.train.snapshot_created_at),
            train_snapshot_ids=list(split.train.snapshot_ids),
            train_ratio=train_ratio,
        )

        path = ModelRegistry.save(artifact)

        return TrainingResult(
            model_version=model_version,
            artifact_path=path,
            train_size=artifact.train_size,
            test_size=artifact.test_size,
            split_timestamp=split.split_timestamp,
            metrics=metrics,
        )

    @staticmethod
    def _validate_dataset(dataset):
        if not dataset.y:
            raise InsufficientTrainingDataError(
                "No labelled history: there are no feature snapshots with "
                "a DEFAULTED or PAID_ON_TIME outcome observed after the "
                "snapshot. Record outcomes with RiskOutcomeService first."
            )

        if list(dataset.feature_names) != list(
            MEMBER_DEFAULT_FEATURE_NAMES
        ):
            raise ValueError(
                "Dataset feature names do not match the feature "
                f"definition: {dataset.feature_names}"
            )

        width = len(MEMBER_DEFAULT_FEATURE_NAMES)
        bad_rows = [
            i for i, row in enumerate(dataset.X) if len(row) != width
        ]

        if bad_rows or len(dataset.X) != len(dataset.y):
            raise ValueError(
                f"Feature dimension mismatch: expected {width} columns "
                f"and one label per row (bad rows: {bad_rows[:10]})."
            )

    @staticmethod
    def _validate_split(split, *, require_evaluation):
        if not split.train.y:
            raise InsufficientTrainingDataError(
                "Time-aware split produced an empty training set."
            )

        if require_evaluation and not split.test.y:
            raise InsufficientTrainingDataError(
                "Time-aware split produced an empty test set, so the "
                "model cannot be evaluated on later data. More history "
                "with distinct snapshot timestamps is required "
                "(or pass require_evaluation=False)."
            )

        present = set(split.train.y)
        missing = REQUIRED_CLASSES - present

        if missing:
            names = {0: "PAID_ON_TIME (0)", 1: "DEFAULTED (1)"}
            raise InsufficientTrainingDataError(
                "Training period lacks required outcome classes: "
                f"{', '.join(names[c] for c in sorted(missing))}. "
                "Both defaults and on-time payments must exist before "
                "the split point."
            )

    @staticmethod
    def _evaluate(pipeline, test):
        if not test.y:
            return {}

        X_test = np.asarray(test.X, dtype=float)
        y_test = np.asarray(test.y, dtype=int)

        classes = list(pipeline.classes_)
        probabilities = pipeline.predict_proba(X_test)[
            :, classes.index(POSITIVE_CLASS)
        ]

        # Shared with DefaultModelEvaluator so training-time and
        # standalone evaluation can never disagree on definitions.
        metrics = asdict(
            compute_classification_metrics(y_test, probabilities)
        )
        metrics["test_positive_rate"] = float(y_test.mean())

        return metrics
