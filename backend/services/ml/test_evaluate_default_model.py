import io
import json
from datetime import timedelta

from django.core.management import CommandError, call_command
from django.db import connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext

from services.ml.evaluate_default_model import (
    DefaultModelEvaluation,
    DefaultModelEvaluator,
    EvaluationLeakageError,
    InsufficientEvaluationDataError,
    compute_classification_metrics,
)
from services.ml.model_registry import (
    ModelArtifactNotFound,
    ModelRegistry,
)
from services.ml.test_default_risk_model import (
    BASE_TIME,
    WRITE_SQL,
    MLTestCase,
)
from services.ml.train_default_model import DefaultModelTrainer


def day(n):
    return BASE_TIME + timedelta(days=n)


class ClassificationMetricsTests(SimpleTestCase):

    def test_known_values(self):
        metrics = compute_classification_metrics(
            [0, 0, 1, 1],
            [0.1, 0.6, 0.4, 0.9],
        )

        self.assertEqual(metrics.accuracy, 0.5)
        self.assertEqual(metrics.precision, 0.5)
        self.assertEqual(metrics.recall, 0.5)
        self.assertEqual(metrics.f1, 0.5)
        self.assertAlmostEqual(metrics.roc_auc, 0.75)
        self.assertAlmostEqual(metrics.average_precision, 5 / 6)
        self.assertEqual(metrics.unavailable_metrics, {})

    def test_confusion_matrix_layout_and_positive_class(self):
        # Positive class is 1 = DEFAULTED.
        # preds at 0.5: [1, 0, 0, 0, 1, 1, 0]
        metrics = compute_classification_metrics(
            [0, 0, 0, 0, 1, 1, 1],
            [0.9, 0.1, 0.2, 0.3, 0.8, 0.7, 0.4],
        )

        self.assertEqual(metrics.true_negatives, 3)
        self.assertEqual(metrics.false_positives, 1)
        self.assertEqual(metrics.false_negatives, 1)
        self.assertEqual(metrics.true_positives, 2)
        self.assertEqual(metrics.confusion_matrix, [[3, 1], [1, 2]])
        self.assertAlmostEqual(metrics.precision, 2 / 3)
        self.assertAlmostEqual(metrics.recall, 2 / 3)

    def test_threshold_controls_predicted_classes(self):
        y = [0, 0, 1, 1]
        p = [0.1, 0.6, 0.4, 0.9]

        strict = compute_classification_metrics(y, p, threshold=0.95)

        self.assertEqual(strict.true_positives + strict.false_positives, 0)
        self.assertIsNone(strict.precision)
        self.assertIn("precision", strict.unavailable_metrics)
        self.assertEqual(strict.recall, 0.0)
        self.assertEqual(strict.f1, 0.0)
        # Ranking metrics don't depend on the threshold.
        self.assertAlmostEqual(strict.roc_auc, 0.75)

    def test_single_class_paid_on_time_does_not_fabricate_metrics(self):
        metrics = compute_classification_metrics(
            [0, 0, 0],
            [0.1, 0.2, 0.3],
        )

        self.assertEqual(metrics.accuracy, 1.0)
        for name in ("precision", "recall", "f1", "roc_auc",
                     "average_precision"):
            with self.subTest(metric=name):
                self.assertIsNone(getattr(metrics, name))
                self.assertIn(name, metrics.unavailable_metrics)

        self.assertIn(
            "only PAID_ON_TIME",
            metrics.unavailable_metrics["roc_auc"],
        )

    def test_single_class_defaulted(self):
        metrics = compute_classification_metrics(
            [1, 1],
            [0.9, 0.2],
        )

        self.assertEqual(metrics.recall, 0.5)
        self.assertEqual(metrics.precision, 1.0)
        self.assertIsNone(metrics.roc_auc)
        self.assertIsNone(metrics.average_precision)
        self.assertIn(
            "only DEFAULTED",
            metrics.unavailable_metrics["average_precision"],
        )

    def test_empty_input_fails_clearly(self):
        with self.assertRaises(InsufficientEvaluationDataError):
            compute_classification_metrics([], [])

    def test_invalid_inputs_raise(self):
        with self.assertRaises(ValueError):
            compute_classification_metrics([0, 1], [0.5])

        for threshold in (0, 1, 1.5):
            with self.subTest(threshold=threshold):
                with self.assertRaises(ValueError):
                    compute_classification_metrics(
                        [0, 1],
                        [0.2, 0.8],
                        threshold=threshold,
                    )


class DefaultModelEvaluatorTests(MLTestCase):

    def train(self):
        self.add_history(10)
        return DefaultModelTrainer.train()

    def test_missing_model_fails_clearly(self):
        with self.assertRaises(ModelArtifactNotFound):
            DefaultModelEvaluator.evaluate()

    def test_structured_out_of_time_result(self):
        self.train()

        result = DefaultModelEvaluator.evaluate()

        self.assertIsInstance(result, DefaultModelEvaluation)
        self.assertEqual(result.model_version, "logistic-default-v1")
        self.assertEqual(result.feature_version, "features-v1")
        self.assertEqual(result.threshold, 0.5)
        self.assertEqual(result.positive_class, "1 = DEFAULTED")

        self.assertEqual(result.train_samples, 8)
        self.assertEqual(result.test_samples, 2)
        self.assertEqual(result.test_defaults, 1)
        self.assertEqual(result.test_paid_on_time, 1)

        self.assertEqual(result.train_start, day(0))
        self.assertEqual(result.train_end, day(7))
        self.assertEqual(result.test_start, day(8))
        self.assertEqual(result.test_end, day(9))
        self.assertEqual(result.split_timestamp, day(8))
        self.assertGreater(result.test_start, result.train_end)

        self.assertEqual(
            result.true_negatives + result.false_positives
            + result.false_negatives + result.true_positives,
            result.test_samples,
        )
        self.assertEqual(
            result.confusion_matrix,
            [
                [result.true_negatives, result.false_positives],
                [result.false_negatives, result.true_positives],
            ],
        )

        for name in ("accuracy", "precision", "recall", "f1",
                     "roc_auc", "average_precision"):
            with self.subTest(metric=name):
                value = getattr(result, name)
                self.assertIsNotNone(value)
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 1.0)

    def test_matches_training_time_metrics(self):
        training = self.train()

        result = DefaultModelEvaluator.evaluate()

        for name in ("accuracy", "precision", "recall", "f1",
                     "roc_auc", "average_precision", "brier_score"):
            with self.subTest(metric=name):
                self.assertEqual(
                    getattr(result, name),
                    training.metrics[name],
                )

    def test_single_class_test_period_reports_unavailable(self):
        for n in range(8):
            self.add_labelled_snapshot(day=n, defaulted=n % 2 == 0)
        for n in (8, 9):
            self.add_labelled_snapshot(day=n, defaulted=False)
        DefaultModelTrainer.train()

        result = DefaultModelEvaluator.evaluate()

        self.assertEqual(result.test_defaults, 0)
        self.assertIsNone(result.roc_auc)
        self.assertIsNone(result.average_precision)
        self.assertIsNone(result.recall)
        self.assertIn("roc_auc", result.unavailable_metrics)
        self.assertIsNotNone(result.accuracy)

    def test_empty_test_period_fails_clearly(self):
        for n in range(6):
            self.add_labelled_snapshot(
                day=n,
                defaulted=n % 2 == 0,
                created_at=BASE_TIME,
            )
        DefaultModelTrainer.train(require_evaluation=False)

        with self.assertRaisesMessage(
            InsufficientEvaluationDataError,
            "empty test period",
        ):
            DefaultModelEvaluator.evaluate()

    def test_backfilled_history_cannot_leak_training_rows_into_test(self):
        self.train()

        # Outcomes recorded later for older snapshots move the 80% cut
        # back into the model's training window.
        for n in range(-20, 0):
            self.add_labelled_snapshot(day=n, defaulted=n % 2 == 0)

        with self.assertRaises(EvaluationLeakageError):
            DefaultModelEvaluator.evaluate()

    def test_artifact_without_training_window_is_rejected(self):
        self.train()

        artifact = ModelRegistry.load()
        artifact.train_end = None
        artifact.train_snapshot_ids = None
        ModelRegistry.save(artifact)

        with self.assertRaisesMessage(
            EvaluationLeakageError,
            "no recorded training window",
        ):
            DefaultModelEvaluator.evaluate()

    def test_evaluation_is_read_only(self):
        self.train()
        path = ModelRegistry.artifact_path("logistic-default-v1")
        modified = path.stat().st_mtime_ns

        with CaptureQueriesContext(connection) as queries:
            DefaultModelEvaluator.evaluate()

        writes = [q["sql"] for q in queries if WRITE_SQL.match(q["sql"])]
        self.assertEqual(writes, [])
        self.assertEqual(path.stat().st_mtime_ns, modified)

    def test_result_serializes_to_json(self):
        self.train()

        data = json.loads(
            json.dumps(DefaultModelEvaluator.evaluate().to_dict())
        )

        self.assertEqual(data["test_start"], day(8).isoformat())
        self.assertEqual(len(data["confusion_matrix"]), 2)

    def test_command_prints_json(self):
        self.train()
        output = io.StringIO()

        call_command("evaluate_default_model", "--json", stdout=output)

        data = json.loads(output.getvalue())
        self.assertEqual(data["model_version"], "logistic-default-v1")
        self.assertEqual(data["test_samples"], 2)

    def test_command_reports_missing_model(self):
        with self.assertRaisesMessage(CommandError, "Cannot evaluate"):
            call_command("evaluate_default_model")
