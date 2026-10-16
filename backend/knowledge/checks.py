from django.conf import settings
from django.core.checks import Warning, register

from services.llm.rate_limiter import (
    configured_backend_is_redis,
    requires_shared_backend,
)


@register()
def assistant_rate_limit_backend(app_configs, **kwargs):
    """
    A paid LLM provider must not run behind a per-process rate limiter:
    each instance would allow the full limit independently. (At runtime
    the limiter refuses such requests; this surfaces it at startup.)
    """
    if requires_shared_backend() and not configured_backend_is_redis():
        return [
            Warning(
                "The paid explanation provider is enabled but assistant "
                "rate limiting uses a per-process cache; assistant "
                "requests will be refused.",
                hint="Set OSUSU_RATE_LIMIT_REDIS_URL so limits are shared "
                     "across application instances.",
                id="knowledge.W001",
            )
        ]
    return []


@register()
def assistant_production_readiness(app_configs, **kwargs):
    """The paid provider is configured but a production gate fails."""
    provider = str(getattr(settings, "OSUSU_LLM_PROVIDER", "") or "").strip()
    if provider != "anthropic":
        return []

    from services.llm.readiness import assess_readiness

    readiness = assess_readiness()
    if readiness.ready:
        return []

    return [
        Warning(
            "The paid explanation provider is configured but not "
            "production-ready; the assistant will answer 503.",
            hint="Failed gates: "
                 + ", ".join(c.name for c in readiness.failures)
                 + ". Run `python manage.py assistant_readiness`.",
            id="knowledge.W002",
        )
    ]
