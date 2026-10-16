"""
Per-user rate limiting for assistant requests (fixed window).

Backend: Django's cache framework, alias "assistant_rate_limit".
- Production: OSUSU_RATE_LIMIT_REDIS_URL -> django RedisCache (package
  `redis`), shared by every application instance, 2s socket timeouts.
- Development default: LocMemCache - per-process and bounded (culls at
  MAX_ENTRIES), NOT a production limiter.

Fail closed:
- a paid LLM provider configured with anything but Redis -> refused
  (RateLimiterUnavailable -> 503) instead of metering per process;
- any cache error (Redis down, timeout) -> refused, never unmetered.

Atomicity: `cache.add` (SET NX) + `cache.incr` (INCR) are atomic on
Redis and lock-protected in LocMem.
"""

import time
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import caches

CACHE_ALIAS = "assistant_rate_limit"
PAID_PROVIDERS = frozenset({"anthropic"})


def requires_shared_backend():
    provider = str(getattr(settings, "OSUSU_LLM_PROVIDER", "") or "").strip()
    return provider in PAID_PROVIDERS


def configured_backend_is_redis():
    backend = settings.CACHES.get(CACHE_ALIAS, {}).get("BACKEND", "")
    return backend.endswith("RedisCache")


class RateLimitExceeded(Exception):

    def __init__(self, retry_after):
        super().__init__("Assistant rate limit exceeded.")
        self.retry_after = retry_after


class RateLimiterUnavailable(Exception):
    """The rate-limit backend failed; the request must not proceed."""


@dataclass(frozen=True)
class RateLimitDecision:
    count: int
    limit: int
    remaining: int
    retry_after: int


class AssistantRateLimiter:

    def __init__(self, *, limit=None, window_seconds=None, cache=None,
                 clock=time.time):
        self.limit = int(
            limit if limit is not None
            else getattr(settings, "OSUSU_ASSISTANT_RATE_LIMIT", 20)
        )
        self.window = int(
            window_seconds if window_seconds is not None
            else getattr(settings, "OSUSU_ASSISTANT_RATE_WINDOW_SECONDS", 3600)
        )
        if self.limit < 1 or self.window < 1:
            raise ValueError("Rate limit and window must be positive.")

        # An injected cache is the caller's (tests) responsibility; the
        # configured one must be Redis whenever a paid provider is on.
        self._unshared = (
            cache is None
            and requires_shared_backend()
            and not configured_backend_is_redis()
        )
        self.cache = cache if cache is not None else caches[CACHE_ALIAS]
        self.clock = clock

    def hit(self, user_id) -> RateLimitDecision:
        """Count one request; raise RateLimitExceeded when over the limit."""
        if self._unshared:
            raise RateLimiterUnavailable(
                "A shared rate-limit backend is required for the paid "
                "provider."
            )

        now = int(self.clock())
        window_start = now - (now % self.window)
        retry_after = max(1, window_start + self.window - now)
        key = f"assistant-rl:{user_id}:{window_start}"

        try:
            self.cache.add(key, 0, timeout=self.window + 5)
            try:
                count = self.cache.incr(key)
            except ValueError:  # expired between add and incr
                self.cache.add(key, 0, timeout=self.window + 5)
                count = self.cache.incr(key)
        except Exception as exc:
            raise RateLimiterUnavailable("Rate limiter unavailable.") from exc

        if count > self.limit:
            raise RateLimitExceeded(retry_after)

        return RateLimitDecision(
            count=count,
            limit=self.limit,
            remaining=self.limit - count,
            retry_after=retry_after,
        )
