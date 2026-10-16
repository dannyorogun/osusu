from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient


User = get_user_model()

STRONG_PASSWORD = "Harbour-Lantern-42"


class RegistrationPasswordValidationTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        caches["throttle"].clear()  # these tests are not about throttling

    def register(self, password, **overrides):
        data = {
            "email": "ada@example.com",
            "username": "adaobi",
            "first_name": "Ada",
            "last_name": "Obi",
            "password": password,
            **overrides,
        }
        return self.client.post(reverse("register"), data, format="json")

    def assert_rejected(self, response):
        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.json())
        self.assertFalse(User.objects.filter(username="adaobi").exists())

    def test_valid_password_registers_without_echoing_it(self):
        response = self.register(STRONG_PASSWORD)

        self.assertEqual(response.status_code, 201)
        self.assertNotIn("password", response.json())
        self.assertNotIn(STRONG_PASSWORD, response.content.decode())
        user = User.objects.get(username="adaobi")
        self.assertTrue(user.check_password(STRONG_PASSWORD))
        self.assertNotEqual(user.password, STRONG_PASSWORD)

    def test_response_contract_is_unchanged(self):
        body = self.register(STRONG_PASSWORD).json()
        self.assertEqual(
            set(body), {"email", "username", "first_name", "last_name"}
        )

    def test_short_password_is_rejected(self):
        self.assert_rejected(self.register("Ab1!x"))

    def test_common_password_is_rejected(self):
        response = self.register("password123")
        self.assert_rejected(response)
        self.assertIn("This password is too common.", response.json()["password"])

    def test_numeric_password_is_rejected(self):
        response = self.register("8392017465")
        self.assert_rejected(response)
        self.assertIn(
            "This password is entirely numeric.", response.json()["password"]
        )

    def test_password_similar_to_username_is_rejected(self):
        response = self.register("adaobi2026", username="adaobi2026x")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(
            any("too similar" in m for m in response.json()["password"])
        )

    def test_password_similar_to_email_is_rejected(self):
        response = self.register(
            "lanternharbour", email="lanternharbour@example.com"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.json())

    def test_rejected_password_is_not_echoed(self):
        response = self.register("password123")
        self.assertNotIn("password123", response.content.decode())

    def test_other_field_errors_still_reported(self):
        User.objects.create_user(
            username="taken", email="ada@example.com", password=STRONG_PASSWORD
        )
        response = self.register(STRONG_PASSWORD)
        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.json())


class RefreshTokenRevocationTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        caches["throttle"].clear()  # these tests are not about throttling
        User.objects.create_user(
            username="ada", email="ada@example.com", password=STRONG_PASSWORD
        )

    def login(self):
        response = self.client.post(
            reverse("token_obtain_pair"),
            {"username": "ada", "password": STRONG_PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["refresh"]

    def refresh(self, token):
        return self.client.post(
            reverse("token_refresh"), {"refresh": token}, format="json"
        )

    def logout(self, token):
        return self.client.post(
            reverse("token_blacklist"), {"refresh": token}, format="json"
        )

    def test_refresh_works_before_logout(self):
        token = self.login()
        self.assertEqual(self.refresh(token).status_code, 200)

    def test_revoked_refresh_token_cannot_get_access_token(self):
        token = self.login()

        self.assertEqual(self.logout(token).status_code, 200)

        response = self.refresh(token)
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("access", response.json())

    def test_logout_needs_no_access_token(self):
        token = self.login()
        self.client.credentials()  # no Authorization header
        self.assertEqual(self.logout(token).status_code, 200)

    def test_logout_only_revokes_that_token(self):
        revoked = self.login()
        other_session = self.login()

        self.logout(revoked)

        self.assertEqual(self.refresh(other_session).status_code, 200)

    def test_logging_out_twice_is_safe(self):
        token = self.login()
        self.assertEqual(self.logout(token).status_code, 200)
        self.assertEqual(self.logout(token).status_code, 401)
        self.assertEqual(self.refresh(token).status_code, 401)

    def test_invalid_token_is_rejected_without_error(self):
        self.assertEqual(self.logout("not-a-token").status_code, 401)

    def test_missing_token_is_a_validation_error(self):
        response = self.client.post(reverse("token_blacklist"), {}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_access_token_cannot_be_used_to_logout(self):
        response = self.client.post(
            reverse("token_obtain_pair"),
            {"username": "ada", "password": STRONG_PASSWORD},
            format="json",
        )
        access = response.json()["access"]
        self.assertEqual(self.logout(access).status_code, 401)
