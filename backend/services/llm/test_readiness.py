"""
Production readiness gate (services/llm/readiness.py).

Offline: no network, no real keys. The "validation report" used here is
SYNTHETIC test data written to a temporary directory; it demonstrates
the gate's logic and is never a claim that live validation happened.
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from services.llm.config import get_llm_provider
from services.llm.fake_provider import FakeLLMProvider
from services.llm.provider import LLMProviderUnavailable
from services.llm.readiness import REPORT_TYPE, REPORT_VERSION, assess_readiness


LLM_KEY = "sk-ant-readiness-SECRET-0123456789"
EMBED_KEY = "sk-openai-readiness-SECRET-0123456789"
REDIS_URL = "redis://:redis-SECRET-pw@localhost:6379/1"

REDIS_CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "assistant_rate_limit": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    },
}


def synthetic_report(**overrides):
    report = {
        "report_type": REPORT_TYPE,
        "report_version": REPORT_VERSION,
        "live": True,
        "passed": True,
        "llm": {"provider": "anthropic", "model": "claude-opus-5"},
        "embedding": {"provider": "openai", "model": "text-embedding-3-small",
                      "dimension": 1536, "embedding_version": "1"},
        "provider_checks": {"passed": True},
        "pipeline": {"passed": True},
        "retrieval": {"threshold_selection": {"threshold": 0.3,
                                              "provisional": False}},
    }
    for key, value in overrides.items():
        report[key] = value
    return report


class ReadinessFixture(SimpleTestCase):

    def setUp(self):
        directory = Path(tempfile.mkdtemp(prefix="osusu-readiness-"))
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        self.report_path = directory / "validation.json"
        self.write_report(synthetic_report())

    def write_report(self, report):
        self.report_path.write_text(json.dumps(report))

    def complete(self, **overrides):
        values = {
            "OSUSU_LLM_PROVIDER": "anthropic",
            "OSUSU_LLM_API_KEY": LLM_KEY,
            "OSUSU_LLM_MODEL": "",
            "OSUSU_LLM_MAX_OUTPUT_TOKENS": 4096,
            "OSUSU_LLM_EFFORT": "medium",
            "OSUSU_EMBEDDING_PROVIDER": "openai",
            "OSUSU_EMBEDDING_API_KEY": EMBED_KEY,
            "OSUSU_EMBEDDING_MODEL": "text-embedding-3-small",
            "OSUSU_EMBEDDING_DIMENSIONS": 1536,
            "OSUSU_RAG_MIN_SIMILARITY": "0.35",
            "OSUSU_RATE_LIMIT_REDIS_URL": REDIS_URL,
            "OSUSU_ASSISTANT_VALIDATION_REPORT": str(self.report_path),
            "CACHES": REDIS_CACHES,
        }
        values.update(overrides)
        return override_settings(**values)

    def failed(self, **overrides):
        with self.complete(**overrides):
            return {c.name for c in assess_readiness().failures}


class ReadinessGateTests(ReadinessFixture):

    def test_every_gate_satisfied_is_ready(self):
        with self.complete():
            self.assertTrue(assess_readiness().ready)

    def test_default_configuration_is_not_ready(self):
        # The shipped defaults: disabled, hashing, no keys, no Redis.
        readiness = assess_readiness()

        self.assertFalse(readiness.ready)
        self.assertTrue({"llm_provider", "llm_api_key", "embedding_provider",
                         "embedding_api_key", "retrieval_threshold",
                         "redis_rate_limit", "live_validation"}
                        <= {c.name for c in readiness.failures})

    def test_each_missing_prerequisite_fails_its_own_gate(self):
        locmem = {
            "default": REDIS_CACHES["default"],
            "assistant_rate_limit": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
        }
        cases = {
            "llm_provider": {"OSUSU_LLM_PROVIDER": "fake"},
            "llm_api_key": {"OSUSU_LLM_API_KEY": ""},
            "llm_configuration": {"OSUSU_LLM_MODEL": "gpt-5"},
            "embedding_provider": {"OSUSU_EMBEDDING_PROVIDER": "hashing"},
            "embedding_api_key": {"OSUSU_EMBEDDING_API_KEY": ""},
            "embedding_model": {"OSUSU_EMBEDDING_MODEL": "text-embedding-ada-002"},
            "retrieval_threshold": {"OSUSU_RAG_MIN_SIMILARITY": ""},
            "redis_rate_limit": {"OSUSU_RATE_LIMIT_REDIS_URL": "", "CACHES": locmem},
            "live_validation": {"OSUSU_ASSISTANT_VALIDATION_REPORT": ""},
        }
        for gate, overrides in cases.items():
            with self.subTest(gate=gate):
                self.assertIn(gate, self.failed(**overrides))

    def test_invalid_values_fail(self):
        for overrides, gate in (
            ({"OSUSU_LLM_MAX_OUTPUT_TOKENS": 64000}, "llm_configuration"),
            ({"OSUSU_LLM_EFFORT": "max"}, "llm_configuration"),
            ({"OSUSU_EMBEDDING_DIMENSIONS": 4096}, "embedding_model"),
            ({"OSUSU_RAG_MIN_SIMILARITY": "abc"}, "retrieval_threshold"),
            ({"OSUSU_RAG_MIN_SIMILARITY": "1.5"}, "retrieval_threshold"),
            ({"OSUSU_RAG_MIN_SIMILARITY": "-0.1"}, "retrieval_threshold"),
        ):
            with self.subTest(overrides=overrides):
                self.assertIn(gate, self.failed(**overrides))

    def test_redis_package_is_required(self):
        with mock.patch.dict(sys.modules, {"redis": None}):
            self.assertIn("redis_rate_limit", self.failed())

    def test_validation_report_must_match_configuration(self):
        cases = {
            "missing file": None,
            "not live": synthetic_report(live=False),
            "not passed": synthetic_report(passed=False),
            "pipeline failed": synthetic_report(pipeline={"passed": False}),
            "provider checks failed": synthetic_report(provider_checks={"passed": False}),
            "other llm model": synthetic_report(
                llm={"provider": "anthropic", "model": "claude-sonnet-5"}),
            "other embedding dimension": synthetic_report(
                embedding={"provider": "openai", "model": "text-embedding-3-small",
                           "dimension": 512, "embedding_version": "1"}),
            "other embedding version": synthetic_report(
                embedding={"provider": "openai", "model": "text-embedding-3-small",
                           "dimension": 1536, "embedding_version": "0"}),
            "provisional threshold": synthetic_report(retrieval={
                "threshold_selection": {"threshold": 0.3, "provisional": True}}),
            "threshold above configured": synthetic_report(retrieval={
                "threshold_selection": {"threshold": 0.5, "provisional": False}}),
            "wrong format": synthetic_report(report_type="something-else"),
        }
        for label, report in cases.items():
            with self.subTest(case=label):
                if report is None:
                    self.report_path.unlink(missing_ok=True)
                else:
                    self.write_report(report)
                self.assertEqual(self.failed(), {"live_validation"})

        self.report_path.write_text("{not json")
        self.assertEqual(self.failed(), {"live_validation"})

    def test_no_secret_appears_in_any_readiness_message(self):
        for overrides in ({}, {"OSUSU_RAG_MIN_SIMILARITY": ""},
                          {"OSUSU_ASSISTANT_VALIDATION_REPORT": "/nope"}):
            with self.complete(**overrides):
                text = repr(assess_readiness())
            for secret in (LLM_KEY, EMBED_KEY, "redis-SECRET-pw"):
                self.assertNotIn(secret, text)


class ProviderSelectionGateTests(ReadinessFixture):

    def test_ready_configuration_serves_the_real_adapter(self):
        from services.llm.anthropic_provider import AnthropicLLMProvider

        with self.complete():
            provider = get_llm_provider()
        self.assertIsInstance(provider, AnthropicLLMProvider)

    def test_any_failed_gate_refuses_the_real_provider(self):
        for overrides in (
            {"OSUSU_RAG_MIN_SIMILARITY": ""},
            {"OSUSU_RATE_LIMIT_REDIS_URL": ""},
            {"OSUSU_ASSISTANT_VALIDATION_REPORT": ""},
            {"OSUSU_EMBEDDING_API_KEY": ""},
        ):
            with self.subTest(overrides=overrides):
                with self.complete(**overrides):
                    with self.assertLogs("services.llm.config", "WARNING") as logs:
                        with self.assertRaises(LLMProviderUnavailable):
                            get_llm_provider()
                self.assertNotIn(LLM_KEY, "".join(logs.output))

    def test_real_provider_never_silently_becomes_fake(self):
        with mock.patch("services.llm.config.FakeLLMProvider",
                        side_effect=AssertionError("fake must not be used")):
            with self.complete(OSUSU_RAG_MIN_SIMILARITY=""):
                with self.assertRaises(LLMProviderUnavailable), \
                        self.assertLogs("services.llm.config", "WARNING"):
                    get_llm_provider()

    def test_disabled_default_and_unknown_providers(self):
        for name in ("", "disabled", "openai", "Anthropic", "fake "):
            with self.subTest(provider=name):
                with override_settings(OSUSU_LLM_PROVIDER=name):
                    if name.strip() == "fake":
                        self.assertIsInstance(get_llm_provider(), FakeLLMProvider)
                    else:
                        with self.assertRaises(LLMProviderUnavailable):
                            get_llm_provider()


class ReadinessCommandTests(ReadinessFixture):

    def test_not_ready_exits_non_zero_without_secrets(self):
        out = io.StringIO()
        with self.complete(OSUSU_RAG_MIN_SIMILARITY=""):
            with self.assertRaises(CommandError) as ctx:
                call_command("assistant_readiness", stdout=out)

        text = out.getvalue() + str(ctx.exception)
        self.assertIn("[FAIL] retrieval_threshold", text)
        self.assertIn("NOT READY", text)
        for secret in (LLM_KEY, EMBED_KEY, "redis-SECRET-pw"):
            self.assertNotIn(secret, text)

    def test_ready(self):
        out = io.StringIO()
        with self.complete():
            call_command("assistant_readiness", stdout=out)
        self.assertIn("READY", out.getvalue())
        self.assertNotIn("[FAIL]", out.getvalue())


class SystemCheckTests(ReadinessFixture):

    def test_paid_provider_without_readiness_warns(self):
        from knowledge.checks import assistant_production_readiness

        with self.complete(OSUSU_RAG_MIN_SIMILARITY=""):
            (warning,) = assistant_production_readiness(None)
        self.assertEqual(warning.id, "knowledge.W002")
        self.assertIn("retrieval_threshold", warning.hint)
        self.assertNotIn(LLM_KEY, warning.hint + warning.msg)

        with self.complete():
            self.assertEqual(assistant_production_readiness(None), [])


class DjangoSecretSettingsTests(SimpleTestCase):
    """Settings are evaluated in a fresh interpreter with a clean env."""

    def load_settings(self, **env):
        base = {k: v for k, v in os.environ.items()
                if not k.startswith(("DJANGO_", "OSUSU_"))}
        # Explicit values take precedence over the developer's .env
        # (python-dotenv never overrides existing variables).
        base.update({"DJANGO_DEBUG": "false", "DJANGO_SECRET_KEY": "",
                     "DJANGO_ALLOWED_HOSTS": ""})
        base.update(env)
        return subprocess.run(
            [sys.executable, "-c",
             "import config.settings as s; "
             "print(s.DEBUG, len(s.SECRET_KEY), s.ALLOWED_HOSTS)"],
            cwd=Path(__file__).resolve().parents[2],
            env=base, capture_output=True, text=True, timeout=60,
        )

    def test_production_requires_a_secret_key(self):
        result = self.load_settings()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY must be set", result.stderr)

    def test_debug_is_off_unless_explicitly_enabled(self):
        secret = "x" * 64
        result = self.load_settings(DJANGO_SECRET_KEY=secret,
                                    DJANGO_ALLOWED_HOSTS="api.example.com, b.example.com")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(),
                         "False 64 ['api.example.com', 'b.example.com']")
        self.assertNotIn(secret, result.stdout + result.stderr)

    def test_development_fallback_only_with_debug(self):
        result = self.load_settings(DJANGO_DEBUG="true")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("True "))
