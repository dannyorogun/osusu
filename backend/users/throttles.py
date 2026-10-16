import hashlib

from django.conf import settings
from django.core.cache import caches
from rest_framework.throttling import SimpleRateThrottle


class AuthRateThrottle(SimpleRateThrottle):
    """
    Rates come from settings.OSUSU_THROTTLE_RATES (read per request, so
    they stay configurable) and counters from the shared "throttle" cache.
    """

    def __init__(self):
        # SimpleRateThrottle reads its rate in __init__; defer to the
        # settings and cache current at request time.
        self.cache = caches["throttle"]
        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)

    def get_rate(self):
        return settings.OSUSU_THROTTLE_RATES[self.scope]

    def key(self, ident):
        return self.cache_format % {"scope": self.scope, "ident": ident}


class LoginUsernameThrottle(AuthRateThrottle):
    """Per submitted username, whatever address the attempts come from."""

    scope = "login_username"

    def get_cache_key(self, request, view):
        username = request.data.get("username") if hasattr(request, "data") else None
        if not isinstance(username, str) or not username.strip():
            return None  # rejected as a validation error; nothing to guess
        # Hashed: usernames never appear in cache keys or the cache table.
        digest = hashlib.sha256(username.strip().lower().encode("utf-8")).hexdigest()
        return self.key(digest)


class LoginIPThrottle(AuthRateThrottle):

    scope = "login_ip"

    def get_cache_key(self, request, view):
        return self.key(self.get_ident(request))


class RegisterIPThrottle(AuthRateThrottle):

    scope = "register_ip"

    def get_cache_key(self, request, view):
        return self.key(self.get_ident(request))
