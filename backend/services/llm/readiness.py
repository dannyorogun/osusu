"""
Production readiness gate for the explanation assistant.

The paid assistant ("anthropic") is served ONLY when every gate passes:

    LLM provider configured          OSUSU_LLM_PROVIDER=anthropic
    LLM API key configured           OSUSU_LLM_API_KEY
    LLM model/budget/effort valid    OSUSU_LLM_MODEL, _MAX_OUTPUT_TOKENS, _EFFORT
    embedding provider configured    OSUSU_EMBEDDING_PROVIDER=openai
    embedding API key configured     OSUSU_EMBEDDING_API_KEY
    production embedding model       OSUSU_EMBEDDING_MODEL / _DIMENSIONS
    threshold explicitly configured  OSUSU_RAG_MIN_SIMILARITY
    Redis rate limiting configured   OSUSU_RATE_LIMIT_REDIS_URL (+ redis package)
    real-provider validation passed  OSUSU_ASSISTANT_VALIDATION_REPORT

API keys alone never enable anything. The validation report is produced
by the opt-in live run (evaluation/README.md) and must describe EXACTLY
the configured models, embedding identity and a non-provisional
threshold no lower than the configured one. It is evidence against
accidental enablement, not a cryptographic control: deployment
configuration is trusted.

Pure: reads settings and one local file. No network, no secrets in any
message (details name settings, never values).
"""

import json
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings


REPORT_TYPE = "osusu-assistant-validation"
REPORT_VERSION = 1


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class ReadinessReport:
    checks: tuple

    @property
    def ready(self):
        return all(c.ok for c in self.checks)

    @property
    def failures(self):
        return tuple(c for c in self.checks if not c.ok)


def _setting(name, default=""):
    value = getattr(settings, name, default)
    return value.strip() if isinstance(value, str) else value


def _llm_checks():
    from services.llm.anthropic_provider import (
        DEFAULT_MODEL,
        validate_configuration,
    )
    from services.llm.provider import LLMProviderUnavailable

    provider = _setting("OSUSU_LLM_PROVIDER", "disabled")
    model = _setting("OSUSU_LLM_MODEL") or DEFAULT_MODEL

    checks = [
        Check("llm_provider", provider == "anthropic",
              "OSUSU_LLM_PROVIDER must be 'anthropic'."),
        Check("llm_api_key", bool(_setting("OSUSU_LLM_API_KEY")),
              "OSUSU_LLM_API_KEY is required."),
    ]
    try:
        validate_configuration(
            model=model,
            max_output_tokens=_setting("OSUSU_LLM_MAX_OUTPUT_TOKENS", 0),
            effort=_setting("OSUSU_LLM_EFFORT", ""),
        )
        ok = True
    except LLMProviderUnavailable:
        ok = False
    checks.append(Check(
        "llm_configuration", ok,
        "OSUSU_LLM_MODEL / OSUSU_LLM_MAX_OUTPUT_TOKENS / OSUSU_LLM_EFFORT "
        "must be valid.",
    ))
    return checks, model


def _embedding_checks():
    from services.knowledge.openai_embedding_provider import SUPPORTED_MODELS

    model = _setting("OSUSU_EMBEDDING_MODEL")
    dimension = _setting("OSUSU_EMBEDDING_DIMENSIONS", 0)

    return [
        Check("embedding_provider",
              _setting("OSUSU_EMBEDDING_PROVIDER") == "openai",
              "OSUSU_EMBEDDING_PROVIDER must be 'openai'."),
        Check("embedding_api_key", bool(_setting("OSUSU_EMBEDDING_API_KEY")),
              "OSUSU_EMBEDDING_API_KEY is required."),
        Check("embedding_model",
              model in SUPPORTED_MODELS
              and isinstance(dimension, int)
              and 16 <= dimension <= SUPPORTED_MODELS[model],
              "OSUSU_EMBEDDING_MODEL / OSUSU_EMBEDDING_DIMENSIONS must name "
              "a supported production model."),
    ]


def configured_threshold():
    raw = _setting("OSUSU_RAG_MIN_SIMILARITY")
    if raw in (None, ""):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if 0.0 <= value < 1.0 else None


def _redis_checks():
    url = _setting("OSUSU_RATE_LIMIT_REDIS_URL")
    backend = settings.CACHES.get("assistant_rate_limit", {}).get("BACKEND", "")

    try:
        import redis  # noqa: F401
        installed = True
    except ImportError:
        installed = False

    return [
        Check("redis_rate_limit",
              bool(url)
              and url.split("://", 1)[0] in {"redis", "rediss", "unix"}
              and backend.endswith("RedisCache")
              and installed,
              "OSUSU_RATE_LIMIT_REDIS_URL must point at Redis (and the "
              "`redis` package must be installed)."),
    ]


def _validation_check(llm_model, threshold):
    from services.knowledge.openai_embedding_provider import (
        OpenAIEmbeddingProvider,
    )

    name = "live_validation"
    path = _setting("OSUSU_ASSISTANT_VALIDATION_REPORT")
    if not path:
        return Check(name, False,
                     "OSUSU_ASSISTANT_VALIDATION_REPORT is not set.")

    try:
        report = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return Check(name, False, "The validation report cannot be read.")

    if not isinstance(report, dict):
        return Check(name, False, "The validation report is malformed.")

    llm = report.get("llm") or {}
    embedding = report.get("embedding") or {}
    selection = (report.get("retrieval") or {}).get("threshold_selection") or {}

    problems = []
    if report.get("report_type") != REPORT_TYPE or \
            report.get("report_version") != REPORT_VERSION:
        problems.append("unknown report format")
    if report.get("live") is not True:
        problems.append("not a live run")
    if report.get("passed") is not True:
        problems.append("validation did not pass")
    if (report.get("provider_checks") or {}).get("passed") is not True:
        problems.append("provider checks did not pass")
    if (report.get("pipeline") or {}).get("passed") is not True:
        problems.append("pipeline scenarios did not pass")
    if llm.get("provider") != "anthropic" or llm.get("model") != llm_model:
        problems.append("LLM model differs from configuration")
    if (
        embedding.get("provider") != "openai"
        or embedding.get("model") != _setting("OSUSU_EMBEDDING_MODEL")
        or embedding.get("dimension")
        != _setting("OSUSU_EMBEDDING_DIMENSIONS", 0)
        or embedding.get("embedding_version")
        != OpenAIEmbeddingProvider.embedding_version
    ):
        problems.append("embedding identity differs from configuration")
    if selection.get("provisional") is not False:
        problems.append("the measured threshold is provisional")
    selected = selection.get("threshold")
    if (
        threshold is None
        or not isinstance(selected, (int, float))
        or threshold < selected
    ):
        problems.append(
            "OSUSU_RAG_MIN_SIMILARITY is below the validated threshold"
        )

    if problems:
        return Check(name, False, "Validation report: " + "; ".join(problems) + ".")
    return Check(name, True, "Live validation report matches configuration.")


def assess_readiness() -> ReadinessReport:
    llm_checks, llm_model = _llm_checks()
    threshold = configured_threshold()

    checks = [
        *llm_checks,
        *_embedding_checks(),
        Check("retrieval_threshold", threshold is not None,
              "OSUSU_RAG_MIN_SIMILARITY must be set explicitly (0 <= t < 1)."),
        *_redis_checks(),
        _validation_check(llm_model, threshold),
    ]
    return ReadinessReport(checks=tuple(checks))
