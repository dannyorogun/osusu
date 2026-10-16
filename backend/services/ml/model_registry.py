"""
Minimal file-based registry for trained ML artifacts.

One joblib file per model version under settings.ML_MODEL_DIR. joblib
uses pickle, so artifacts must only ever be loaded from this trusted,
server-controlled directory — never from user uploads.
"""

import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import joblib
from django.conf import settings

from services.risk.member_features import (
    FEATURE_VERSION,
    MEMBER_DEFAULT_FEATURE_NAMES,
)


DEFAULT_MODEL_VERSION = "logistic-default-v1"

_VERSION_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.\-]*$")


class ModelArtifactError(Exception):
    """The artifact is missing, unreadable, or incompatible."""


class ModelArtifactNotFound(ModelArtifactError):
    pass


@dataclass
class ModelArtifact:
    model_version: str
    feature_names: list[str]
    feature_version: str
    pipeline: object
    trained_at: datetime
    train_size: int
    test_size: int
    metrics: dict
    split_timestamp: datetime | None

    # Training provenance, used by evaluation to prove the test period
    # is strictly later than, and disjoint from, the training data.
    # Defaults keep artifacts pickled before these fields loadable.
    train_start: datetime | None = None
    train_end: datetime | None = None
    train_snapshot_ids: list[str] | None = None
    train_ratio: float | None = None


class ModelRegistry:

    @staticmethod
    def model_dir():
        return Path(settings.ML_MODEL_DIR)

    @classmethod
    def artifact_path(cls, model_version):
        if not _VERSION_PATTERN.match(model_version):
            raise ValueError(
                f"Invalid model version: {model_version!r}"
            )

        return cls.model_dir() / f"{model_version}.joblib"

    @classmethod
    def save(cls, artifact: ModelArtifact):
        path = cls.artifact_path(artifact.model_version)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write to a temp file then atomically replace, so a reader never
        # sees a half-written model.
        fd, tmp_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{artifact.model_version}.",
            suffix=".tmp",
        )
        os.close(fd)

        try:
            joblib.dump(artifact, tmp_name)
            os.replace(tmp_name, path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

        return path

    @classmethod
    def load(cls, model_version=DEFAULT_MODEL_VERSION):
        path = cls.artifact_path(model_version)

        if not path.exists():
            raise ModelArtifactNotFound(
                f"No trained model '{model_version}' at {path}. "
                "Train one with: python manage.py train_default_model"
            )

        artifact = joblib.load(path)

        if not isinstance(artifact, ModelArtifact):
            raise ModelArtifactError(
                f"{path} does not contain a ModelArtifact."
            )

        if artifact.model_version != model_version:
            raise ModelArtifactError(
                f"{path} holds version {artifact.model_version!r}, "
                f"expected {model_version!r}."
            )

        if (
            list(artifact.feature_names)
            != list(MEMBER_DEFAULT_FEATURE_NAMES)
            or artifact.feature_version != FEATURE_VERSION
        ):
            raise ModelArtifactError(
                f"Model '{model_version}' was trained on a different "
                "feature definition; retrain it."
            )

        return artifact
