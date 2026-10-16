"""
LLM provider abstraction.

A provider turns (system prompt, user prompt, context) into raw text. It
has NO tools, NO function calling and NO database access: it only ever
sees what ExplanationService hands it, which is authorized, circle-scoped
retrieved evidence. Parsing and validation of the output happen in
ExplanationService, never in the provider.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


class LLMError(Exception):
    """Base class. Messages must never contain credentials."""


class LLMProviderUnavailable(LLMError):
    """No provider configured, disabled, or unreachable."""


class LLMAuthenticationError(LLMError):
    """Provider rejected our credentials."""


class LLMTimeout(LLMError):
    """Provider did not answer in time."""


class LLMRateLimited(LLMError):
    """Provider throttled the request."""


class LLMMalformedResponse(LLMError):
    """Provider answered, but not in the required structured format."""


class LLMProviderError(LLMError):
    """Any other provider-side failure."""


class LLMRefusal(LLMProviderError):
    """
    The provider declined to answer (after any configured fallback).
    Handled exactly like any other provider failure: it is never an
    answer, and refusal itself is not a business rule.
    """


@dataclass(frozen=True)
class ContextItem:
    """
    One piece of authorized evidence. `source_id` ("S1", "S2", ...) is the
    only identifier the model sees; real ids stay server-side.
    """

    source_id: str
    title: str
    document_type: str
    document_version: int
    content: str


@dataclass(frozen=True)
class LLMResult:
    text: str
    provider: str
    model: str
    # Observability only (never used for decisions): whether a provider-
    # side refusal fallback served the answer, and billed output tokens.
    fallback_used: bool = False
    output_tokens: int | None = None


class LLMProvider(ABC):

    name: str
    model: str

    @abstractmethod
    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        context: tuple[ContextItem, ...],
    ) -> LLMResult:
        """
        Return the model's raw text. Implementations map their own
        failures onto the LLMError subclasses above and must not leak
        provider-specific exceptions or credentials.
        """
