import os
import threading
import time
import unittest
import uuid
from unittest import mock

from django.core.cache import caches
from django.core.cache.backends.locmem import LocMemCache
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from knowledge.tests.test_retrieval_security import IndexedFixture
from services.llm.rate_limiter import (
    CACHE_ALIAS,
    AssistantRateLimiter,
    RateLimiterUnavailable,
    RateLimitExceeded,
)


def fresh_cache():
    return LocMemCache(f"test-{uuid.uuid4()}", {})


class Clock:

    def __init__(self, now=1_000_000):
        self.now = now

    def __call__(self):
        return self.now


class AssistantRateLimiterTests(SimpleTestCase):

    def limiter(self, limit=3, window=60, clock=None, cache=None):
        return AssistantRateLimiter(
            limit=limit,
            window_seconds=window,
            cache=cache or fresh_cache(),
            clock=clock or Clock(),
        )

    def test_blocks_after_the_limit(self):
        limiter = self.limiter(limit=3)

        decisions = [limiter.hit("u1") for _ in range(3)]
        self.assertEqual([d.count for d in decisions], [1, 2, 3])
        self.assertEqual(decisions[-1].remaining, 0)

        with self.assertRaises(RateLimitExceeded) as ctx:
            limiter.hit("u1")
        self.assertGreaterEqual(ctx.exception.retry_after, 1)

    def test_users_are_limited_independently(self):
        limiter = self.limiter(limit=1)

        limiter.hit("u1")
        limiter.hit("u2")
        with self.assertRaises(RateLimitExceeded):
            limiter.hit("u1")

    def test_window_resets(self):
        clock = Clock(now=1_000_040)  # 1_000_020 is a window start; +20s
        limiter = self.limiter(limit=1, window=60, clock=clock)

        limiter.hit("u1")
        with self.assertRaises(RateLimitExceeded) as ctx:
            limiter.hit("u1")
        self.assertEqual(ctx.exception.retry_after, 40)

        clock.now += 40
        self.assertEqual(limiter.hit("u1").count, 1)

    def test_shared_backend_is_shared_between_instances(self):
        # Two limiter instances (two "processes") on one shared cache.
        cache = fresh_cache()
        first = self.limiter(limit=2, cache=cache)
        second = self.limiter(limit=2, cache=cache)

        first.hit("u1")
        second.hit("u1")
        with self.assertRaises(RateLimitExceeded):
            first.hit("u1")

    def test_backend_failure_fails_closed(self):
        class BrokenCache:
            def add(self, *args, **kwargs):
                raise ConnectionError("redis down")

        with self.assertRaises(RateLimiterUnavailable):
            self.limiter(cache=BrokenCache()).hit("u1")

    def test_configuration(self):
        with override_settings(OSUSU_ASSISTANT_RATE_LIMIT=7,
                               OSUSU_ASSISTANT_RATE_WINDOW_SECONDS=120):
            limiter = AssistantRateLimiter(cache=fresh_cache())
        self.assertEqual((limiter.limit, limiter.window), (7, 120))

        for limit, window in ((0, 60), (5, 0)):
            with self.assertRaises(ValueError):
                AssistantRateLimiter(limit=limit, window_seconds=window,
                                     cache=fresh_cache())

    def test_default_alias_is_the_dedicated_cache(self):
        self.assertIs(AssistantRateLimiter().cache, caches[CACHE_ALIAS])


@override_settings(OSUSU_LLM_PROVIDER="fake", OSUSU_ASSISTANT_RATE_LIMIT=3)
class AssistantEndpointRateLimitTests(IndexedFixture):

    def setUp(self):
        super().setUp()
        caches[CACHE_ALIAS].clear()
        self.addCleanup(caches[CACHE_ALIAS].clear)
        self.client = APIClient()

    def authenticate(self, user):
        token = RefreshToken.for_user(user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def post(self, body=None, circle=None):
        return self.client.post(
            reverse("circle-assistant", kwargs={"circle_id": (circle or self.circle).id}),
            body or {"question": "What is the current treasury balance?"},
            format="json",
        )

    def test_blocks_after_configured_limit_with_retry_after(self):
        self.authenticate(self.alice)

        statuses = [self.post().status_code for _ in range(3)]
        blocked = self.post()

        self.assertEqual(statuses, [200, 200, 200])
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.data["code"], "assistant_rate_limited")
        self.assertGreaterEqual(int(blocked["Retry-After"]), 1)
        self.assertNotIn("answer", blocked.data)

    def test_limit_is_per_user(self):
        self.authenticate(self.alice)
        for _ in range(3):
            self.post()

        self.authenticate(self.bob)
        self.assertEqual(self.post().status_code, 200)

    def test_invalid_requests_count(self):
        self.authenticate(self.alice)
        for _ in range(3):
            self.assertEqual(self.post({"question": ""}).status_code, 400)

        self.assertEqual(self.post().status_code, 429)

    def test_outsiders_are_rejected_before_metering(self):
        self.authenticate(self.outsider)
        for _ in range(5):
            self.assertEqual(self.post().status_code, 404)

        # The outsider consumed nothing; members are unaffected.
        self.authenticate(self.alice)
        self.assertEqual(self.post().status_code, 200)

    def test_rate_limiter_outage_is_503(self):
        with override_settings(CACHES={
            "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
            CACHE_ALIAS: {"BACKEND": "django.core.cache.backends.dummy.DummyCache"},
        }):
            # DummyCache.incr raises (key never stored): treated as outage.
            self.authenticate(self.alice)
            with self.assertLogs("knowledge.views", level="ERROR"):
                response = self.post()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["code"], "assistant_unavailable")


class ConcurrencyAndFailureTests(SimpleTestCase):

    def test_concurrent_requests_never_exceed_the_limit(self):
        cache = fresh_cache()
        limiter = AssistantRateLimiter(limit=10, window_seconds=60, cache=cache,
                                       clock=Clock())
        allowed, blocked = [], []
        start = threading.Barrier(40)

        def worker():
            start.wait()
            try:
                limiter.hit("u1")
                allowed.append(1)
            except RateLimitExceeded:
                blocked.append(1)

        threads = [threading.Thread(target=worker) for _ in range(40)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual((len(allowed), len(blocked)), (10, 30))

    def test_expired_window_keys_do_not_carry_over(self):
        clock = Clock(now=1_000_020)
        cache = fresh_cache()
        limiter = AssistantRateLimiter(limit=2, window_seconds=60, cache=cache,
                                       clock=clock)
        limiter.hit("u1")
        limiter.hit("u1")

        clock.now += 60 * 5  # several windows later
        decision = limiter.hit("u1")
        self.assertEqual((decision.count, decision.remaining), (1, 1))
        self.assertEqual(decision.retry_after, 60)

    def test_unreachable_redis_fails_closed_quickly(self):
        from django.core.cache.backends.redis import RedisCache

        cache = RedisCache("redis://127.0.0.1:1/0", {"OPTIONS": {
            "socket_connect_timeout": 0.5, "socket_timeout": 0.5}})
        limiter = AssistantRateLimiter(limit=5, window_seconds=60, cache=cache)

        started = time.monotonic()
        with self.assertRaises(RateLimiterUnavailable) as ctx:
            limiter.hit("u1")
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(str(ctx.exception), "Rate limiter unavailable.")

    @override_settings(OSUSU_LLM_PROVIDER="anthropic")
    def test_paid_provider_refuses_a_per_process_limiter(self):
        # Configured backend is LocMem (no OSUSU_RATE_LIMIT_REDIS_URL).
        with self.assertRaises(RateLimiterUnavailable):
            AssistantRateLimiter().hit("u1")

    @override_settings(OSUSU_LLM_PROVIDER="anthropic", CACHES={
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
        CACHE_ALIAS: {"BACKEND": "django.core.cache.backends.redis.RedisCache",
                      "LOCATION": "redis://127.0.0.1:1/0",
                      "OPTIONS": {"socket_connect_timeout": 0.5}},
    })
    def test_paid_provider_with_redis_down_fails_closed(self):
        with self.assertRaises(RateLimiterUnavailable):
            AssistantRateLimiter().hit("u1")

    @override_settings(OSUSU_LLM_PROVIDER="fake")
    def test_development_providers_may_use_the_local_limiter(self):
        self.assertEqual(AssistantRateLimiter(limit=1).hit(str(uuid.uuid4())).count, 1)


@override_settings(OSUSU_LLM_PROVIDER="anthropic", OSUSU_LLM_API_KEY="sk-ant-x")
class PaidProviderEndpointOrderingTests(IndexedFixture):
    """Paid provider configured, Redis absent: fail closed, in order."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def post(self, user):
        token = RefreshToken.for_user(user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return self.client.post(
            reverse("circle-assistant", kwargs={"circle_id": self.circle.id}),
            {"question": "What is the current treasury balance?"},
            format="json",
        )

    def test_outsider_is_404_before_the_limiter(self):
        self.assertEqual(self.post(self.outsider).status_code, 404)

    def test_member_gets_503_and_no_retrieval_or_provider_call(self):
        with mock.patch(
            "services.llm.explanation_service.KnowledgeAccessService.retrieve_for_user",
            side_effect=AssertionError("retrieval must not run"),
        ), mock.patch(
            "services.llm.config.build_anthropic_provider",
            side_effect=AssertionError("provider must not be built"),
        ):
            with self.assertLogs("knowledge.views", "ERROR"):
                response = self.post(self.alice)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["code"], "assistant_unavailable")


@override_settings(OSUSU_LLM_PROVIDER="anthropic", OSUSU_LLM_API_KEY="sk-ant-x",
                   CACHES={
                       "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
                       CACHE_ALIAS: {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                                     "LOCATION": "unmetered-in-this-test"},
                   })
class NotReadyProviderEndpointTests(IndexedFixture):
    """Limiter passes (patched to a shared-backend state), but the
    readiness gate fails: 503 before any embedding call."""

    def test_not_ready_assistant_spends_nothing(self):
        client = APIClient()
        token = RefreshToken.for_user(self.alice).access_token
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        with mock.patch(
            "services.llm.rate_limiter.configured_backend_is_redis",
            return_value=True,
        ), mock.patch(
            "services.llm.explanation_service.KnowledgeAccessService.retrieve_for_user",
            side_effect=AssertionError("retrieval must not run"),
        ), self.assertLogs(level="WARNING") as logs:
            response = client.post(
                reverse("circle-assistant", kwargs={"circle_id": self.circle.id}),
                {"question": "What is the current treasury balance?"},
                format="json",
            )

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("sk-ant-x", str(response.data))
        self.assertNotIn("sk-ant-x", "".join(logs.output))


REDIS_TESTS = os.getenv("OSUSU_RUN_REDIS_TESTS", "").lower() == "true"


@unittest.skipUnless(
    REDIS_TESTS and os.getenv("OSUSU_RATE_LIMIT_REDIS_URL"),
    "Live Redis test not run: set OSUSU_RUN_REDIS_TESTS=true and "
    "OSUSU_RATE_LIMIT_REDIS_URL (a disposable database).",
)
class LiveRedisRateLimiterTests(SimpleTestCase):
    """OPT-IN: against a real Redis. Uses unique user ids; keys expire."""

    def setUp(self):
        from django.core.cache.backends.redis import RedisCache

        self.cache = RedisCache(os.environ["OSUSU_RATE_LIMIT_REDIS_URL"], {
            "OPTIONS": {"socket_connect_timeout": 2, "socket_timeout": 2}})
        self.user = f"live-test-{uuid.uuid4()}"

    def limiter(self, **kwargs):
        return AssistantRateLimiter(cache=self.cache, **kwargs)

    def test_limit_window_retry_after_and_isolation(self):
        clock = Clock(now=int(time.time()))
        limiter = self.limiter(limit=2, window_seconds=30, clock=clock)
        limiter.hit(self.user)
        limiter.hit(self.user)
        with self.assertRaises(RateLimitExceeded) as ctx:
            limiter.hit(self.user)
        self.assertTrue(1 <= ctx.exception.retry_after <= 30)

        self.assertEqual(limiter.hit(self.user + "-other").count, 1)

        clock.now += 30
        self.assertEqual(limiter.hit(self.user).count, 1)

    def test_concurrent_instances_share_one_limit(self):
        allowed = []
        start = threading.Barrier(20)

        def worker():
            start.wait()
            try:
                self.limiter(limit=5, window_seconds=60).hit(self.user)
                allowed.append(1)
            except RateLimitExceeded:
                pass

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(allowed), 5)
