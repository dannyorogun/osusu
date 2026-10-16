from django.core.management.base import BaseCommand, CommandError

from services.ml.model_registry import DEFAULT_MODEL_VERSION
from services.ml.train_default_model import (
    DefaultModelTrainer,
    InsufficientTrainingDataError,
)


class Command(BaseCommand):
    help = (
        "Train the baseline default-risk model (Logistic Regression) "
        "on historical snapshots using a time-aware split."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--model-version",
            default=DEFAULT_MODEL_VERSION,
        )
        parser.add_argument(
            "--train-ratio",
            type=float,
            default=0.8,
        )
        parser.add_argument(
            "--skip-evaluation",
            action="store_true",
            help="Allow training when the later period has no test rows.",
        )

    def handle(self, *args, **options):
        try:
            result = DefaultModelTrainer.train(
                model_version=options["model_version"],
                train_ratio=options["train_ratio"],
                require_evaluation=not options["skip_evaluation"],
            )
        except InsufficientTrainingDataError as exc:
            raise CommandError(f"Cannot train: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(
            f"Trained {result.model_version} -> {result.artifact_path}"
        ))
        self.stdout.write(
            f"train rows={result.train_size} "
            f"test rows={result.test_size} "
            f"split at={result.split_timestamp}"
        )

        for name, value in result.metrics.items():
            self.stdout.write(f"  {name}: {value}")
