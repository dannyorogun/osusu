"""
Settings under a production-style environment (Sprint 31). Each case
imports config.settings in a fresh process, because the test process has
already loaded the development settings.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from django.test import SimpleTestCase


BACKEND = Path(__file__).resolve().parent.parent

PRODUCTION_ENV = {
    "DJANGO_DEBUG": "false",
    "DJANGO_SECRET_KEY": "test-only-" + "x" * 60,
    "DJANGO_ALLOWED_HOSTS": "api.osusu.example",
    "DJANGO_CORS_ALLOWED_ORIGINS": "https://app.osusu.example",
    "DJANGO_CSRF_TRUSTED_ORIGINS": "https://api.osusu.example",
}

PROBE = """
import json, django
from django.conf import settings
django.setup()
print(json.dumps({k: (list(v) if isinstance(v, tuple) else v) for k, v in {
    "DEBUG": settings.DEBUG,
    "SECURE_SSL_REDIRECT": settings.SECURE_SSL_REDIRECT,
    "SECURE_HSTS_SECONDS": settings.SECURE_HSTS_SECONDS,
    "SECURE_HSTS_INCLUDE_SUBDOMAINS": settings.SECURE_HSTS_INCLUDE_SUBDOMAINS,
    "SESSION_COOKIE_SECURE": settings.SESSION_COOKIE_SECURE,
    "CSRF_COOKIE_SECURE": settings.CSRF_COOKIE_SECURE,
    "SECURE_PROXY_SSL_HEADER": settings.SECURE_PROXY_SSL_HEADER,
    "CSRF_TRUSTED_ORIGINS": settings.CSRF_TRUSTED_ORIGINS,
    "CORS_ALLOWED_ORIGINS": settings.CORS_ALLOWED_ORIGINS,
    "CORS_ALLOW_ALL_ORIGINS": getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False),
    "OSUSU_PAYOUT_PROVIDER": settings.OSUSU_PAYOUT_PROVIDER,
    "OSUSU_PAYOUT_MOCK_ALLOWED": settings.OSUSU_PAYOUT_MOCK_ALLOWED,
    "THROTTLE_CACHE": settings.CACHES["throttle"]["BACKEND"],
    "NUM_PROXIES": settings.REST_FRAMEWORK["NUM_PROXIES"],
}.items()}))
"""


def run(args, **env):
    # Start from the parent environment minus anything these settings
    # read, then apply only what the case specifies. load_dotenv() never
    # overrides a variable that is already set.
    base = {
        k: v for k, v in os.environ.items()
        if not k.startswith(("DJANGO_", "OSUSU_"))
    }
    base["DJANGO_SETTINGS_MODULE"] = "config.settings"
    return subprocess.run(
        [sys.executable, *args], cwd=BACKEND, env={**base, **env},
        capture_output=True, text=True, timeout=120,
    )


def load(**env):
    result = run(["-c", PROBE], **env)
    if result.returncode:
        raise AssertionError(result.stderr[-3000:])
    return json.loads(result.stdout.strip().splitlines()[-1])


class ProductionSettingsTests(SimpleTestCase):

    def assert_refused(self, message, **env):
        result = run(["-c", PROBE], **{**PRODUCTION_ENV, **env})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ImproperlyConfigured", result.stderr)
        self.assertIn(message, result.stderr)
        # The secret key is never echoed in the failure.
        self.assertNotIn(PRODUCTION_ENV["DJANGO_SECRET_KEY"], result.stderr + result.stdout)

    def test_production_defaults_are_secure_and_fail_closed(self):
        s = load(**PRODUCTION_ENV)
        self.assertIs(s["DEBUG"], False)
        self.assertIs(s["SECURE_SSL_REDIRECT"], True)
        self.assertGreater(s["SECURE_HSTS_SECONDS"], 0)
        self.assertIs(s["SESSION_COOKIE_SECURE"], True)
        self.assertIs(s["CSRF_COOKIE_SECURE"], True)
        self.assertIsNone(s["SECURE_PROXY_SSL_HEADER"])  # opt-in only
        self.assertEqual(s["CORS_ALLOWED_ORIGINS"], ["https://app.osusu.example"])
        self.assertEqual(s["CSRF_TRUSTED_ORIGINS"], ["https://api.osusu.example"])
        self.assertIs(s["CORS_ALLOW_ALL_ORIGINS"], False)
        self.assertEqual(s["OSUSU_PAYOUT_PROVIDER"], "disabled")
        self.assertIs(s["OSUSU_PAYOUT_MOCK_ALLOWED"], False)
        self.assertEqual(s["THROTTLE_CACHE"], "django.core.cache.backends.db.DatabaseCache")
        self.assertEqual(s["NUM_PROXIES"], 0)

    def test_production_without_cors_origins_allows_none(self):
        env = {k: v for k, v in PRODUCTION_ENV.items() if k != "DJANGO_CORS_ALLOWED_ORIGINS"}
        self.assertEqual(load(**env)["CORS_ALLOWED_ORIGINS"], [])

    def test_proxy_https_header_and_hsts_are_configurable(self):
        s = load(
            **PRODUCTION_ENV,
            DJANGO_TRUST_X_FORWARDED_PROTO="true",
            DJANGO_SECURE_HSTS_SECONDS="31536000",
            DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS="true",
            DJANGO_NUM_PROXIES="1",
        )
        self.assertEqual(s["SECURE_PROXY_SSL_HEADER"], ["HTTP_X_FORWARDED_PROTO", "https"])
        self.assertEqual(s["SECURE_HSTS_SECONDS"], 31536000)
        self.assertIs(s["SECURE_HSTS_INCLUDE_SUBDOMAINS"], True)
        self.assertEqual(s["NUM_PROXIES"], 1)

    def test_development_keeps_local_http_and_the_mock(self):
        s = load(DJANGO_DEBUG="true")
        self.assertIs(s["SECURE_SSL_REDIRECT"], False)
        self.assertEqual(s["SECURE_HSTS_SECONDS"], 0)
        self.assertIs(s["SESSION_COOKIE_SECURE"], False)
        self.assertEqual(s["OSUSU_PAYOUT_PROVIDER"], "mock")
        self.assertIs(s["OSUSU_PAYOUT_MOCK_ALLOWED"], True)
        self.assertIn("http://localhost:3000", s["CORS_ALLOWED_ORIGINS"])

    def test_mock_payout_provider_is_refused_in_production(self):
        self.assert_refused("OSUSU_PAYOUT_PROVIDER=mock is development-only", OSUSU_PAYOUT_PROVIDER="mock")

    def test_unknown_payout_provider_is_refused(self):
        self.assert_refused("is not supported", OSUSU_PAYOUT_PROVIDER="stripe")

    def test_mock_payment_webhook_is_refused_in_production(self):
        self.assert_refused("OSUSU_MOCK_PAYMENTS_ENABLED is development-only", OSUSU_MOCK_PAYMENTS_ENABLED="true")

    def test_cors_origins_must_be_exact_https_origins(self):
        for origin, message in (
            ("http://app.osusu.example", "must use https"),
            ("https://*.osusu.example", "exact origin"),
            ("https://app.osusu.example/", "exact origin"),
        ):
            with self.subTest(origin):
                self.assert_refused(message, DJANGO_CORS_ALLOWED_ORIGINS=origin)

    def test_missing_secret_key_is_refused(self):
        self.assert_refused("DJANGO_SECRET_KEY must be set", DJANGO_SECRET_KEY="")

    def test_deploy_check_is_clean_with_the_documented_production_settings(self):
        result = run(
            ["manage.py", "check", "--deploy", "--fail-level", "WARNING"],
            **PRODUCTION_ENV,
            DJANGO_SECURE_HSTS_SECONDS="31536000",
            DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS="true",
            DJANGO_SECURE_HSTS_PRELOAD="true",
        )
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        self.assertIn("no issues", result.stdout)


STATIC_PROBE = """
import json, django
from django.core.management import call_command
django.setup()
call_command("collectstatic", interactive=False, verbosity=0)
from django.templatetags.static import static
from django.test import Client
client = Client()
url = static("admin/css/base.css")
css = client.get(url, secure=True, HTTP_HOST="api.osusu.example")
login = client.get("/admin/login/", secure=True, HTTP_HOST="api.osusu.example")
plain = client.get("/admin/login/", HTTP_HOST="api.osusu.example")
print(json.dumps({
    "url": url,
    "css_status": css.status_code,
    "css_type": css.headers.get("Content-Type", ""),
    "css_cache": css.headers.get("Cache-Control", ""),
    "login_status": login.status_code,
    "login_links_hashed_css": url in login.content.decode(),
    "login_hsts": login.headers.get("Strict-Transport-Security", ""),
    "http_status": plain.status_code,
    "http_location": plain.headers.get("Location", ""),
}))
"""


class ProductionStaticFilesTests(SimpleTestCase):
    """Django admin static files under production settings (WhiteNoise)."""

    def test_collected_admin_static_is_served_with_hashed_names(self):
        with tempfile.TemporaryDirectory() as static_root:
            result = run(["-c", STATIC_PROBE], **PRODUCTION_ENV, DJANGO_STATIC_ROOT=static_root)
            self.assertEqual(result.returncode, 0, result.stderr[-3000:])
            s = json.loads(result.stdout.strip().splitlines()[-1])

        self.assertRegex(s["url"], r"^/static/admin/css/base\.[0-9a-f]{12}\.css$")
        self.assertEqual(s["css_status"], 200)
        self.assertTrue(s["css_type"].startswith("text/css"))
        self.assertIn("immutable", s["css_cache"])
        self.assertEqual(s["login_status"], 200)
        self.assertTrue(s["login_links_hashed_css"])
        self.assertIn("max-age=", s["login_hsts"])
        # Plain HTTP is redirected to HTTPS.
        self.assertEqual(s["http_status"], 301)
        self.assertTrue(s["http_location"].startswith("https://api.osusu.example/"))
