"""Authentication throttling and the CORS allowlist (Sprint 31)."""

from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient


User = get_user_model()

PASSWORD = "Harbour-Lantern-42"

RATES = {"login_username": "3/minute", "login_ip": "100/minute", "register_ip": "2/hour"}


@override_settings(OSUSU_THROTTLE_RATES=RATES)
class AuthThrottleTests(TestCase):

    def setUp(self):
        caches["throttle"].clear()
        self.addCleanup(caches["throttle"].clear)
        self.client = APIClient()
        User.objects.create_user(username="ada", email="ada@example.com", password=PASSWORD)
        User.objects.create_user(username="bola", email="bola@example.com", password=PASSWORD)

    def login(self, username, password="wrong-password", **extra):
        return self.client.post(
            reverse("token_obtain_pair"),
            {"username": username, "password": password},
            format="json",
            **extra,
        )

    def register(self, n):
        return self.client.post(reverse("register"), {
            "email": f"new{n}@example.com", "username": f"new{n}",
            "first_name": "New", "last_name": "User", "password": PASSWORD,
        }, format="json")

    def test_login_is_throttled_per_username(self):
        for _ in range(3):
            self.assertEqual(self.login("ada").status_code, 401)

        blocked = self.login("ada", PASSWORD)  # even the right password

        self.assertEqual(blocked.status_code, 429)
        self.assertIn("Retry-After", blocked.headers)
        self.assertNotIn("refresh", blocked.json())
        self.assertNotIn("ada", blocked.content.decode())
        self.assertNotIn(PASSWORD, blocked.content.decode())

    def test_username_limit_ignores_case_and_spacing(self):
        for name in ("ada", "ADA", " Ada "):
            self.login(name)
        self.assertEqual(self.login("ada").status_code, 429)

    def test_other_usernames_are_unaffected(self):
        for _ in range(4):
            self.login("ada")
        self.assertEqual(self.login("bola", PASSWORD).status_code, 200)

    def test_username_limit_holds_across_addresses(self):
        for n in range(3):
            self.login("ada", REMOTE_ADDR=f"10.0.0.{n}")
        self.assertEqual(self.login("ada", REMOTE_ADDR="10.0.0.99").status_code, 429)

    @override_settings(OSUSU_THROTTLE_RATES={**RATES, "login_username": "100/minute", "login_ip": "3/minute"})
    def test_login_is_throttled_per_ip_and_forwarded_for_is_not_trusted(self):
        for n in range(3):
            self.login(f"user{n}", HTTP_X_FORWARDED_FOR=f"203.0.113.{n}")

        blocked = self.login("someone-else", HTTP_X_FORWARDED_FOR="198.51.100.7")

        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(self.login("bola", PASSWORD, REMOTE_ADDR="10.9.9.9").status_code, 200)

    def test_successful_login_still_works_below_the_limit(self):
        self.login("ada")
        response = self.login("ada", PASSWORD)
        self.assertEqual(response.status_code, 200)
        self.assertIn("refresh", response.json())

    def test_registration_is_throttled_per_ip(self):
        self.assertEqual(self.register(1).status_code, 201)
        self.assertEqual(self.register(2).status_code, 201)

        blocked = self.register(3)

        self.assertEqual(blocked.status_code, 429)
        self.assertIn("Retry-After", blocked.headers)
        self.assertFalse(User.objects.filter(username="new3").exists())

    def test_refresh_and_logout_are_not_pooled_with_login(self):
        token = self.login("bola", PASSWORD).json()["refresh"]
        for _ in range(5):
            self.login("ada")
        self.assertEqual(
            self.client.post(reverse("token_refresh"), {"refresh": token}, format="json").status_code,
            200,
        )


class CorsAllowlistTests(TestCase):

    def preflight(self, origin):
        return self.client.options(
            reverse("token_obtain_pair"),
            HTTP_ORIGIN=origin,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,content-type",
        )

    @override_settings(CORS_ALLOWED_ORIGINS=["https://app.osusu.example"])
    def test_allowed_origin_gets_cors_headers(self):
        response = self.preflight("https://app.osusu.example")
        self.assertEqual(response.headers.get("access-control-allow-origin"), "https://app.osusu.example")

    @override_settings(CORS_ALLOWED_ORIGINS=["https://app.osusu.example"])
    def test_other_origins_get_none(self):
        for origin in (
            "https://evil.example",
            "http://app.osusu.example",  # scheme matters
            "https://app.osusu.example.evil.example",
            "null",
        ):
            with self.subTest(origin):
                response = self.preflight(origin)
                self.assertNotIn("access-control-allow-origin", response.headers)

    @override_settings(CORS_ALLOWED_ORIGINS=["https://app.osusu.example"])
    def test_simple_request_from_other_origin_gets_no_cors_header(self):
        response = self.client.get(reverse("me"), HTTP_ORIGIN="https://evil.example")
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_allow_all_is_off(self):
        from django.conf import settings

        self.assertFalse(getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False))
        self.assertFalse(getattr(settings, "CORS_ALLOW_CREDENTIALS", False))
