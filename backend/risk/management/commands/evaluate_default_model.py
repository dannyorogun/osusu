import json

from django.core.management.base import BaseCommand, CommandError

from services.ml.evaluate_default_model import (
    DEFAULT_THRESHOLD,
    DefaultModelEvaluator,
    InsufficientEvaluationDataError,
)
from services.ml.model_registry import (
    DEFAULT_MODEL_VERSION,
    ModelArtifactError,
)


class Command(BaseCommand):
    help = (
        "Evaluate the trained default-risk model on the out-of-time "
        "(later) test period. Positive class: 1 = DEFAULTED."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--model-version",
            default=DEFAULT_MODEL_VERSION,
        )
        parser.add_argument(
            "--threshold",
            type=float,
            default=DEFAULT_THRESHOLD,
            help="Probability at or above which a default is predicted.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Print the full evaluation as JSON.",
        )

    def handle(self, *args, **options):
        try:
            result = DefaultModelEvaluator.evaluate(
                model_version=options["model_version"],
                threshold=options["threshold"],
            )
        except (InsufficientEvaluationDataError, ModelArtifactError) as exc:
            raise CommandError(f"Cannot evaluate: {exc}") from exc
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        if options["json"]:
            self.stdout.write(json.dumps(result.to_dict(), indent=2))
            return

        def fmt(value):
            return "unavailable" if value is None else f"{value:.4f}"

        self.stdout.write(self.style.SUCCESS(
            f"{result.model_version} ({result.feature_version}) "
            f"@ threshold {result.threshold}"
        ))
        self.stdout.write(
            f"train: {result.train_samples} rows "
            f"[{result.train_start} .. {result.train_end}]"
        )
        self.stdout.write(
            f"test:  {result.test_samples} rows "
            f"[{result.test_start} .. {result.test_end}] "
            f"defaults={result.test_defaults} "
            f"paid_on_time={result.test_paid_on_time}"
        )

        for name in (
            "accuracy",
            "precision",
            "recall",
            "f1",
            "roc_auc",
            "average_precision",
            "brier_score",
            "log_loss",
        ):
            self.stdout.write(f"  {name}: {fmt(getattr(result, name))}")

        self.stdout.write(
            "  confusion [[TN, FP], [FN, TP]]: "
            f"{result.confusion_matrix}"
        )

        for name, reason in result.unavailable_metrics.items():
            self.stdout.write(self.style.WARNING(f"  {name}: {reason}"))
