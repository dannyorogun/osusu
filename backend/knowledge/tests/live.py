"""
Opt-in live provider tests.

- Never run unless OSUSU_RUN_EXTERNAL_AI_TESTS=true (normal suite and CI
  need no network and no keys).
- When requested but a required key is missing, they FAIL with a clear
  message instead of skipping or silently using a fake provider.
- Keys are read from settings only; they are never printed, logged or
  written to any report.
"""

import os
import unittest

from django.conf import settings


EXTERNAL = os.getenv("OSUSU_RUN_EXTERNAL_AI_TESTS", "").strip().lower() == "true"

NOT_REQUESTED = (
    "Live provider test not run: set OSUSU_RUN_EXTERNAL_AI_TESTS=true "
    "(uses paid APIs)."
)


def live(test_class):
    return unittest.skipUnless(EXTERNAL, NOT_REQUESTED)(test_class)


class LiveCredentialsMixin:

    required_settings = ()

    def setUp(self):
        # Checked BEFORE the fixture's setUp, which may call paid APIs.
        missing = [
            name for name in self.required_settings
            if not str(getattr(settings, name, "") or "").strip()
        ]
        if missing:
            self.fail(
                "OSUSU_RUN_EXTERNAL_AI_TESTS=true but required credentials "
                "are not configured: " + ", ".join(missing)
                + ". Refusing to fall back to a fake provider."
            )
        super().setUp()

    def assert_no_secret(self, text):
        for name in self.required_settings:
            secret = str(getattr(settings, name, "") or "")
            if secret:
                self.assertNotIn(secret, str(text))


def output_dir():
    """Where live runs write their reports (None: do not write)."""
    return os.getenv("OSUSU_EVALUATION_OUTPUT_DIR") or None
