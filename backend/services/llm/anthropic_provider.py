"""
Anthropic (Claude) adapter - the ONLY module that imports the Anthropic SDK.

Verified against the Anthropic API documentation on 2026-09-30 (anthropic
Python SDK 1.9.0; see evaluation/SPRINT26_PROVIDER_NOTES.md):

- Messages API with structured outputs (`output_config.format`, JSON
  schema, GA): the model can only return {"status", "answer",
  "citations"}. ExplanationService still parses and validates everything.
- NO tools are ever passed: the model cannot call functions, reach the
  database or change anything.
- claude-opus-5 thinks by default (adaptive thinking) and `max_tokens`
  is a hard cap on thinking PLUS answer text. Answers here are short
  (<= 4000 characters), so the budget is bounded (MAX_OUTPUT_TOKENS_CEILING)
  and `output_config.effort` limits thinking spend. A response cut off by
  the budget fails closed (LLMMalformedResponse), never half-parsed.
- Server-side refusal fallback (`fallbacks="default"`, beta
  `server-side-fallback-2026-07-01`) is on by default so a safety-classifier
  decline is retried server-side on Anthropic's recommended model;
  disable with OSUSU_LLM_REFUSAL_FALLBACK=off. A refusal that survives the
  fallback chain is an error (LLMRefusal), never an answer.
- SDK failures map onto the LLMError hierarchy with FIXED messages. SDK
  exception text is never propagated (it can contain request details).
  The SDK retries 408/409/429/5xx and connection errors `max_retries`
  times, and retried timeouts mean worst-case wall-clock is
  timeout * (max_retries + 1).

Data sent: SYSTEM_PROMPT plus the user prompt built by ExplanationService
from authorized, circle-scoped, allowlisted evidence. Nothing else.
"""

import re

import anthropic

from services.llm.provider import (
    LLMAuthenticationError,
    LLMMalformedResponse,
    LLMProvider,
    LLMProviderError,
    LLMProviderUnavailable,
    LLMRateLimited,
    LLMRefusal,
    LLMResult,
    LLMTimeout,
)


DEFAULT_MODEL = "claude-opus-5"
REFUSAL_FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Short factual explanations: the answer is capped at 4000 characters
# (~1000 tokens) and the rest of the budget is room for adaptive thinking.
DEFAULT_MAX_OUTPUT_TOKENS = 4096
# Below this, thinking alone can exhaust the budget. Above the ceiling,
# the SDK requires streaming (HTTP timeouts), which this adapter does not
# use - and an explanation never needs it.
MIN_OUTPUT_TOKENS = 1024
MAX_OUTPUT_TOKENS_CEILING = 16000

DEFAULT_EFFORT = "medium"
EFFORT_LEVELS = ("low", "medium", "high")

_MODEL_ID = re.compile(r"^claude-[a-z0-9]+(?:-[a-z0-9]+)*$")

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": ["answered", "insufficient_context"],
        },
        "answer": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["status", "answer", "citations"],
    "additionalProperties": False,
}


def validate_configuration(*, model, max_output_tokens, effort):
    """Fixed messages only; configuration values are not secret but are
    not echoed either."""
    if not _MODEL_ID.match(str(model)):
        raise LLMProviderUnavailable(
            "Invalid explanation model configuration."
        )

    try:
        max_output_tokens = int(max_output_tokens)
    except (TypeError, ValueError):
        raise LLMProviderUnavailable(
            "Invalid explanation output budget."
        ) from None

    if not MIN_OUTPUT_TOKENS <= max_output_tokens <= MAX_OUTPUT_TOKENS_CEILING:
        raise LLMProviderUnavailable("Invalid explanation output budget.")

    if effort not in EFFORT_LEVELS:
        raise LLMProviderUnavailable("Invalid explanation effort level.")

    return max_output_tokens


class AnthropicLLMProvider(LLMProvider):

    name = "anthropic"

    def __init__(
        self,
        *,
        api_key,
        model=DEFAULT_MODEL,
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        effort=DEFAULT_EFFORT,
        timeout=60.0,
        max_retries=2,
        refusal_fallback=True,
        client=None,
    ):
        if client is None and not api_key:
            raise LLMProviderUnavailable(
                "The explanation provider is not configured."
            )

        self.model = model or DEFAULT_MODEL
        self.effort = effort
        self.max_output_tokens = validate_configuration(
            model=self.model,
            max_output_tokens=max_output_tokens,
            effort=effort,
        )
        self.refusal_fallback = refusal_fallback
        self._client = client or anthropic.Anthropic(
            api_key=api_key,
            timeout=timeout,
            max_retries=max_retries,
        )

    def __repr__(self):
        # Never include the client (it holds the API key).
        return f"AnthropicLLMProvider(model={self.model!r})"

    def generate(self, *, system_prompt, user_prompt, context):
        request = {
            "model": self.model,
            "max_tokens": self.max_output_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "output_config": {
                "format": {"type": "json_schema", "schema": ANSWER_SCHEMA},
                "effort": self.effort,
            },
        }

        try:
            if self.refusal_fallback:
                response = self._client.beta.messages.create(
                    **request,
                    betas=[REFUSAL_FALLBACK_BETA],
                    fallbacks="default",
                )
            else:
                response = self._client.messages.create(**request)

        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
            raise LLMAuthenticationError(
                "The explanation provider rejected the credentials."
            ) from None
        except anthropic.RateLimitError:
            raise LLMRateLimited(
                "The explanation provider is rate limiting requests."
            ) from None
        except (anthropic.APITimeoutError, anthropic.DeadlineExceededError):
            # APITimeoutError before APIConnectionError (its subclass).
            raise LLMTimeout("The explanation provider timed out.") from None
        except anthropic.APIConnectionError:
            raise LLMProviderUnavailable(
                "The explanation provider is unreachable."
            ) from None
        except anthropic.APIStatusError as exc:
            # 5xx (500 InternalServerError, 503 ServiceUnavailableError,
            # 529 OverloadedError - separate classes in SDK 1.x) is an
            # outage; 4xx means the request itself was rejected.
            if getattr(exc, "status_code", 0) >= 500:
                raise LLMProviderUnavailable(
                    "The explanation provider is unavailable."
                ) from None
            raise LLMProviderError(
                "The explanation provider rejected the request."
            ) from None
        except anthropic.AnthropicError:
            # Credential resolution, response validation, retry
            # exhaustion and any future SDK error: never let SDK text out.
            raise LLMProviderUnavailable(
                "The explanation provider is unavailable."
            ) from None

        return LLMResult(
            text=self._extract_text(response),
            provider=self.name,
            model=str(getattr(response, "model", "") or self.model),
            fallback_used=self._fallback_used(response),
            output_tokens=self._output_tokens(response),
        )

    @staticmethod
    def _fallback_used(response):
        iterations = getattr(getattr(response, "usage", None), "iterations", None)
        try:
            return any(
                getattr(i, "type", None) == "fallback_message"
                for i in iterations or ()
            )
        except TypeError:
            return False

    @staticmethod
    def _output_tokens(response):
        value = getattr(getattr(response, "usage", None), "output_tokens", None)
        return value if isinstance(value, int) else None

    @staticmethod
    def _extract_text(response):
        stop_reason = getattr(response, "stop_reason", None)

        if stop_reason == "refusal":
            raise LLMRefusal("The explanation provider declined to answer.")

        if stop_reason == "max_tokens":
            raise LLMMalformedResponse("The model response was cut off.")

        try:
            texts = []
            for block in response.content:
                block_type = getattr(block, "type", None)
                if block_type == "fallback":
                    # Only the model that finished the turn answers; text
                    # before a fallback boundary belongs to the declined one.
                    texts = []
                elif block_type == "text":
                    texts.append(block.text)
        except (AttributeError, TypeError):
            raise LLMMalformedResponse("Unexpected model response.") from None

        if not texts or not all(isinstance(t, str) for t in texts):
            raise LLMMalformedResponse("The model returned no text.")

        return "".join(texts)
