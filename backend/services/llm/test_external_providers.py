"""
OPT-IN integration tests against the REAL paid providers.

Run only with OSUSU_RUN_EXTERNAL_AI_TESTS=true; fail (never skip or fake)
if the needed key is then missing. They send only the tiny synthetic text
below (never Osusu data), touch no database, and assert structure and
invariants - never exact model wording.
"""

import json
import math

from django.conf import settings
from django.test import SimpleTestCase

from knowledge.tests.live import LiveCredentialsMixin, live
from services.llm.prompts import SYSTEM_PROMPT, build_user_prompt
from services.llm.provider import (
    ContextItem,
    LLMAuthenticationError,
    LLMProviderError,
    LLMProviderUnavailable,
    LLMTimeout,
)


CONTEXT = (
    ContextItem(
        source_id="S1",
        title="Treasury: Example Circle",
        document_type="circle_financial_summary",
        document_version=1,
        content="Treasury: Example Circle\n\nThe current treasury balance "
                "of Example Circle is £120.00.",
    ),
)

INVALID_ANTHROPIC_KEY = "sk-ant-api03-invalid-osusu-live-test-key"
INVALID_OPENAI_KEY = "sk-invalid-osusu-live-test-key"


def ask(provider, question="What is the treasury balance?"):
    return provider.generate(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=build_user_prompt(question=question, context=CONTEXT),
        context=CONTEXT,
    )


@live
class AnthropicLiveTest(LiveCredentialsMixin, SimpleTestCase):

    required_settings = ("OSUSU_LLM_API_KEY",)

    def provider(self, **kwargs):
        from services.llm.anthropic_provider import AnthropicLLMProvider
        from services.llm.config import build_anthropic_provider

        if not kwargs:
            return build_anthropic_provider()  # configured; gate bypassed
        return AnthropicLLMProvider(
            api_key=kwargs.pop("api_key", settings.OSUSU_LLM_API_KEY),
            model=settings.OSUSU_LLM_MODEL or None,
            **kwargs,
        )

    def test_initialization_does_not_expose_the_key(self):
        provider = self.provider()
        self.assert_no_secret(repr(provider))
        self.assert_no_secret(repr(vars(provider).keys()))

    def test_structured_generation_and_budget(self):
        provider = self.provider()
        result = ask(provider)

        data = json.loads(result.text)
        self.assertEqual(set(data), {"status", "answer", "citations"})
        self.assertIn(data["status"], ("answered", "insufficient_context"))
        self.assertIsInstance(data["answer"], str)
        self.assertTrue(set(data["citations"]) <= {"S1"})
        self.assertIsInstance(result.fallback_used, bool)
        if result.output_tokens is not None:
            self.assertLessEqual(result.output_tokens, provider.max_output_tokens)
        self.assert_no_secret(result.text)

    def test_invalid_key_maps_to_authentication_error(self):
        with self.assertRaises(LLMAuthenticationError) as ctx:
            ask(self.provider(api_key=INVALID_ANTHROPIC_KEY, max_retries=0))
        self.assertNotIn(INVALID_ANTHROPIC_KEY, str(ctx.exception))

    def test_unknown_model_maps_to_provider_error(self):
        from services.llm.anthropic_provider import AnthropicLLMProvider

        provider = AnthropicLLMProvider(
            api_key=settings.OSUSU_LLM_API_KEY,
            model="claude-osusu-nonexistent-model",
            max_retries=0,
        )
        with self.assertRaises(LLMProviderError):
            ask(provider)

    def test_timeout_is_enforced(self):
        with self.assertRaises((LLMTimeout, LLMProviderUnavailable)):
            ask(self.provider(timeout=0.001, max_retries=0))


@live
class OpenAIEmbeddingLiveTest(LiveCredentialsMixin, SimpleTestCase):

    required_settings = ("OSUSU_EMBEDDING_API_KEY",)

    def provider(self, **kwargs):
        from services.knowledge.openai_embedding_provider import (
            OpenAIEmbeddingProvider,
        )
        options = {
            "api_key": settings.OSUSU_EMBEDDING_API_KEY,
            "model": settings.OSUSU_EMBEDDING_MODEL,
            "dimension": settings.OSUSU_EMBEDDING_DIMENSIONS,
        }
        options.update(kwargs)
        return OpenAIEmbeddingProvider(**options)

    def test_embeddings_dimension_and_normalization(self):
        provider = self.provider()
        vectors = provider.embed_documents(["treasury balance", "payout window"])

        self.assertEqual([len(v) for v in vectors], [provider.dimension] * 2)
        for vector in vectors:
            self.assertAlmostEqual(math.sqrt(sum(x * x for x in vector)), 1.0,
                                   places=3)
        self.assert_no_secret(repr(provider))

    def test_identity_is_deterministic_and_repeat_embeddings_agree(self):
        provider = self.provider()
        self.assertEqual(
            provider.identity,
            ("openai", settings.OSUSU_EMBEDDING_MODEL,
             settings.OSUSU_EMBEDDING_DIMENSIONS, "1"),
        )
        a, b = provider.embed_documents(["contribution schedule"] * 2)
        cosine = sum(x * y for x, y in zip(a, b))
        self.assertGreater(cosine, 0.99)  # near-, not bit-, deterministic

    def test_shortened_dimension(self):
        (vector,) = self.provider(dimension=256).embed_documents(["payout"])
        self.assertEqual(len(vector), 256)

    def test_invalid_key_maps_without_leaking(self):
        from services.knowledge.embedding_service import (
            EmbeddingProviderUnavailable,
        )

        provider = self.provider(api_key=INVALID_OPENAI_KEY, max_retries=0)
        with self.assertRaises(EmbeddingProviderUnavailable) as ctx:
            provider.embed_documents(["x"])
        self.assertNotIn(INVALID_OPENAI_KEY, str(ctx.exception))
