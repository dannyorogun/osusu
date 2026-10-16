"""
Out-of-time evaluation of the default-risk model.

Pipeline:
    RiskDatasetBuilder -> TimeAwareDatasetSplitter -> load trained model
    -> test-period X -> predicted probabilities -> predicted classes
    -> metrics

Label convention (positive class = the event we want to catch):
    1 = DEFAULTED
    0 = PAID_ON_TIME

Metrics are never fabricated. A metric that is mathematically undefined
for the evaluation data (e.g. ROC-AUC on a single-class test period, or
precision when nothing was predicted positive) is returned as None, with
the reason recorded in `unavailable_metrics`.

Evaluation is informational only: it reads data and a model file and
writes nothing.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime

import numpy as np
from django.utils import timezone
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)

from services.ml.model_registry import (
    DEFAULT_MODEL_VERSION,
    ModelArtifactError,
    ModelRegistry,
)
from services.risk.dataset_builder import RiskDatasetBuilder
from services.risk.time_aware_splitter import TimeAwareDatasetSplitter


POSITIVE_CLASS = 1   # DEFAULTED
NEGATIVE_CLASS = 0   # PAID_ON_TIME
LABELS = [NEGATIVE_CLASS, POSITIVE_CLASS]

DEFAULT_THRESHOLD = 0.5


class InsufficientEvaluationDataError(ValueError):
    """Not enough out-of-time data to evaluate honestly."""


class EvaluationLeakageError(ModelArtifactError):
    """The evaluation period overlaps the model's training data."""


@dataclass
class ClassificationMetrics:
    accuracy: float
    precision: float | None
    recall: float | None
    f1: float | None
    roc_auc: float | None
    average_precision: float | None
    brier_score: float
    log_loss: float

    true_negatives: int
    false_positives: int
    false_negatives: int
    true_positives: int

    # Why each None metric is unavailable.
    unavailable_metrics: dict[str, str] = field(default_factory=dict)

    @property
    def confusion_matrix(self):
        """
        Standard 2x2 layout, rows = actual, columns = predicted,
        both ordered [PAID_ON_TIME (0), DEFAULTED (1)]:

            [[TN, FP],
             [FN, TP]]
        """
        return [
            [self.true_negatives, self.false_positives],
            [self.false_negatives, self.true_positives],
        ]


def compute_classification_metrics(
    y_true,
    probabilities,
    *,
    threshold=DEFAULT_THRESHOLD,
) -> ClassificationMetrics:
    """
    Metrics for positive class DEFAULTED (1) at the given threshold.
    Requires at least one sample.
    """
    y_true = np.asarray(y_true, dtype=int)
    probabilities = np.asarray(probabilities, dtype=float)

    if y_true.size == 0:
        raise InsufficientEvaluationDataError(
            "Cannot compute metrics on an empty evaluation set."
        )

    if y_true.shape != probabilities.shape:
        raise ValueError("Labels and probabilities differ in length.")

    if not 0 < threshold < 1:
        raise ValueError("threshold must be between 0 and 1 (exclusive).")

    predictions = (probabilities >= threshold).astype(int)

    tn, fp, fn, tp = (
        int(v)
        for v in confusion_matrix(
            y_true,
            predictions,
            labels=LABELS,
        ).ravel()
    )

    unavailable = {}

    if tp + fp > 0:
        precision = float(
            precision_score(y_true, predictions, pos_label=POSITIVE_CLASS)
        )
    else:
        precision = None
        unavailable["precision"] = (
            "No member was predicted to default at this threshold "
            "(TP + FP = 0)."
        )

    if tp + fn > 0:
        recall = float(
            recall_score(y_true, predictions, pos_label=POSITIVE_CLASS)
        )
    else:
        recall = None
        unavailable["recall"] = (
            "The evaluation period contains no defaults (TP + FN = 0)."
        )

    # F1 = 2TP / (2TP + FP + FN): defined whenever there is any actual
    # or predicted default.
    if 2 * tp + fp + fn > 0:
        f1 = float(
            f1_score(
                y_true,
                predictions,
                pos_label=POSITIVE_CLASS,
                zero_division=0,
            )
        )
    else:
        f1 = None
        unavailable["f1"] = (
            "No actual or predicted defaults (2TP + FP + FN = 0)."
        )

    if len(set(y_true.tolist())) == 2:
        roc_auc = float(roc_auc_score(y_true, probabilities))
        average_precision = float(
            average_precision_score(
                y_true,
                probabilities,
                pos_label=POSITIVE_CLASS,
            )
        )
    else:
        roc_auc = None
        average_precision = None
        only = (
            "DEFAULTED" if y_true[0] == POSITIVE_CLASS else "PAID_ON_TIME"
        )
        reason = (
            f"The evaluation period contains only {only} outcomes; "
            "ranking metrics need both classes."
        )
        unavailable["roc_auc"] = reason
        unavailable["average_precision"] = reason

    return ClassificationMetrics(
        accuracy=float(accuracy_score(y_true, predictions)),
        precision=precision,
        recall=recall,
        f1=f1,
        roc_auc=roc_auc,
        average_precision=average_precision,
        brier_score=float(brier_score_loss(y_true, probabilities)),
        log_loss=float(log_loss(y_true, probabilities, labels=LABELS)),
        true_negatives=tn,
        false_positives=fp,
        false_negatives=fn,
        true_positives=tp,
        unavailable_metrics=unavailable,
    )


@dataclass
class DefaultModelEvaluation:
    model_version: str
    feature_version: str
    evaluated_at: datetime
    threshold: float

    train_samples: int
    test_samples: int
    test_defaults: int
    test_paid_on_time: int

    accuracy: float
    precision: float | None
    recall: float | None
    f1: float | None
    roc_auc: float | None
    average_precision: float | None
    brier_score: float
    log_loss: float

    true_negatives: int
    false_positives: int
    false_negatives: int
    true_positives: int
    confusion_matrix: list[list[int]]

    # Training window comes from the artifact (what the model actually
    # saw); test window from the current out-of-time split.
    train_start: datetime | None
    train_end: datetime | None
    test_start: datetime
    test_end: datetime
    split_timestamp: datetime | None

    unavailable_metrics: dict[str, str] = field(default_factory=dict)

    positive_class: str = "1 = DEFAULTED"
    negative_class: str = "0 = PAID_ON_TIME"

    def to_dict(self):
        data = asdict(self)
        for key, value in data.items():
            if isinstance(value, datetime):
                data[key] = value.isoformat()
        return data


class DefaultModelEvaluator:

    @classmethod
    def evaluate(
        cls,
        *,
        model_version=DEFAULT_MODEL_VERSION,
        threshold=DEFAULT_THRESHOLD,
        train_ratio=None,
    ) -> DefaultModelEvaluation:

        artifact = ModelRegistry.load(model_version)

        dataset = RiskDatasetBuilder.build_member_default_dataset()

        if not dataset.y:
            raise InsufficientEvaluationDataError(
                "No labelled history to evaluate on: there are no "
                "snapshots with a DEFAULTED or PAID_ON_TIME outcome "
                "observed after the snapshot."
            )

        split = TimeAwareDatasetSplitter.split(
            dataset,
            train_ratio=(
                train_ratio
                or artifact.train_ratio
                or TimeAwareDatasetSplitter.DEFAULT_TRAIN_RATIO
            ),
        )

        test = split.test

        if not test.y:
            raise InsufficientEvaluationDataError(
                "The time-aware split produced an empty test period, so "
                "there is no later data to evaluate on. More history with "
                "distinct snapshot timestamps is required."
            )

        cls._assert_out_of_time(artifact, test)

        X_test = np.asarray(test.X, dtype=float)

        if X_test.shape[1] != artifact.pipeline.n_features_in_:
            raise ModelArtifactError(
                f"Model expects {artifact.pipeline.n_features_in_} "
                f"features; evaluation data has {X_test.shape[1]}."
            )

        classes = list(artifact.pipeline.classes_)
        probabilities = artifact.pipeline.predict_proba(X_test)[
            :, classes.index(POSITIVE_CLASS)
        ]

        metrics = compute_classification_metrics(
            test.y,
            probabilities,
            threshold=threshold,
        )

        test_defaults = sum(1 for label in test.y if label == POSITIVE_CLASS)

        return DefaultModelEvaluation(
            model_version=artifact.model_version,
            feature_version=artifact.feature_version,
            evaluated_at=timezone.now(),
            threshold=threshold,
            train_samples=artifact.train_size,
            test_samples=len(test.y),
            test_defaults=test_defaults,
            test_paid_on_time=len(test.y) - test_defaults,
            accuracy=metrics.accuracy,
            precision=metrics.precision,
            recall=metrics.recall,
            f1=metrics.f1,
            roc_auc=metrics.roc_auc,
            average_precision=metrics.average_precision,
            brier_score=metrics.brier_score,
            log_loss=metrics.log_loss,
            true_negatives=metrics.true_negatives,
            false_positives=metrics.false_positives,
            false_negatives=metrics.false_negatives,
            true_positives=metrics.true_positives,
            confusion_matrix=metrics.confusion_matrix,
            train_start=artifact.train_start,
            train_end=artifact.train_end,
            test_start=min(test.snapshot_created_at),
            test_end=max(test.snapshot_created_at),
            split_timestamp=split.split_timestamp,
            unavailable_metrics=metrics.unavailable_metrics,
        )

    @staticmethod
    def _assert_out_of_time(artifact, test):
        """
        The model must never be scored on rows it trained on or on rows
        not strictly later than its training data. The dataset can change
        after training (e.g. backfilled outcomes), so re-splitting alone
        does not guarantee this.
        """
        if artifact.train_end is None or artifact.train_snapshot_ids is None:
            raise EvaluationLeakageError(
                f"Model '{artifact.model_version}' has no recorded "
                "training window, so an out-of-time evaluation cannot be "
                "verified. Retrain it with train_default_model."
            )

        seen = set(artifact.train_snapshot_ids) & set(test.snapshot_ids)

        if seen:
            raise EvaluationLeakageError(
                f"{len(seen)} test-period snapshot(s) were used to train "
                f"'{artifact.model_version}'. Retrain before evaluating."
            )

        earliest_test = min(test.snapshot_created_at)

        if earliest_test <= artifact.train_end:
            raise EvaluationLeakageError(
                f"Test period starts at {earliest_test.isoformat()}, not "
                "after the model's training data (ends "
                f"{artifact.train_end.isoformat()}). The dataset changed "
                "since training; retrain before evaluating."
            )
