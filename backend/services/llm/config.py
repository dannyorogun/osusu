"""
Provider selection from settings (environment).

OSUSU_LLM_PROVIDER:
    "disabled" (default) -> LLMProviderUnavailable: the assistant fails
                            closed until a provider is chosen explicitly.
    "anthropic"          -> AnthropicLLMProvider (paid), served ONLY when
                            every production gate passes
                            (services/llm/readiness.py). API keys alone
                            never enable it.
    "fake"               -> FakeLLMProvider (development/tests only; quotes
                            the supplied context, not a language model).
    anything else        -> LLMProviderUnavailable.

There is NO fallback between providers: a failing, misconfigured or
not-yet-validated real provider never degrades to fake output, which a
user could mistake for a real answer.
"""

import logging

from django.conf import settings

from services.llm.fake_provider import FakeLLMProvider
from services.llm.provider import LLMProviderUnavailable
from services.llm.readiness import assess_readiness


logger = logging.getLogger(__name__)


def build_anthropic_provider():
    """The configured Anthropic adapter, WITHOUT the readiness gate (for
    the opt-in validation run that produces the readiness evidence)."""
    # Imported here so the SDK is only loaded when selected.
    from services.llm.anthropic_provider import AnthropicLLMProvider

    return AnthropicLLMProvider(
        api_key=getattr(settings, "OSUSU_LLM_API_KEY", ""),
        model=getattr(settings, "OSUSU_LLM_MODEL", "") or None,
        max_output_tokens=getattr(settings, "OSUSU_LLM_MAX_OUTPUT_TOKENS", 4096),
        effort=getattr(settings, "OSUSU_LLM_EFFORT", "medium"),
        timeout=float(getattr(settings, "OSUSU_LLM_TIMEOUT_SECONDS", 60)),
        refusal_fallback=(
            str(getattr(settings, "OSUSU_LLM_REFUSAL_FALLBACK", "default"))
            .strip().lower() != "off"
        ),
    )


def get_llm_provider():
    name = (getattr(settings, "OSUSU_LLM_PROVIDER", "disabled") or "").strip()

    if name == "fake":
        return FakeLLMProvider()

    if name == "anthropic":
        readiness = assess_readiness()
        if not readiness.ready:
            # Names of failed gates only - never values.
            logger.warning(
                "paid explanation provider refused: not production-ready",
                extra={"failed_gates": [c.name for c in readiness.failures]},
            )
            raise LLMProviderUnavailable(
                "The explanation assistant is not production-ready."
            )
        return build_anthropic_provider()

    if name in ("", "disabled"):
        raise LLMProviderUnavailable("The explanation assistant is disabled.")

    raise LLMProviderUnavailable(
        "The configured explanation provider is not available."
    )
