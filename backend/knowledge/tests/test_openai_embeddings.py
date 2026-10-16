"""
OpenAIEmbeddingProvider unit tests, mocked at the SDK boundary.

No network and no credentials. We never assert specific vector values:
the provider does not guarantee them.
"""

import math
from types import SimpleNamespace

import openai
from django.test import SimpleTestCase, override_settings

from services.knowledge.embedding_service import (
    EmbeddingInputError,
    EmbeddingProviderError,
    EmbeddingProviderUnavailable,
    HashingEmbeddingProvider,
    get_default_embedding_provider,
    get_min_similarity,
)
from services.knowledge.openai_embedding_provider import (
    MAX_BATCH_SIZE,
    MAX_INPUT_CHARACTERS,
    OpenAIEmbeddingProvider,
)


SECRET = "sk-openai-test-secret-DO-NOT-LEAK-0123456789"
DIM = 16  # the provider rejects < 16 dimensions as meaningless


def vector_for(text, dim=DIM):
    # Deterministic fake: the provider under test only passes vectors on.
    return [float((len(text) + i) % 7) for i in range(dim)]


class FakeEmbeddings:

    def __init__(self, dim=DIM, error=None, mutate=None):
        self.dim = dim
        self.error = error
        self.mutate = mutate
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        data = [
            SimpleNamespace(index=i, embedding=vector_for(text, self.dim))
            for i, text in enumerate(kwargs["input"])
        ]
        data = list(reversed(data))  # providers may return any order
        if self.mutate:
            data = self.mutate(data)
        return SimpleNamespace(data=data)


def provider_with(**kwargs):
    embeddings = FakeEmbeddings(**kwargs)
    provider = OpenAIEmbeddingProvider(
        api_key=None,
        dimension=DIM,
        client=SimpleNamespace(embeddings=embeddings),
    )
    return provider, embeddings


def http_error(cls, status):
    return cls(
        f"upstream said {SECRET}",
        response=SimpleNamespace(status_code=status, headers={},
                                 request=SimpleNamespace()),
        body=None,
    )


class OpenAIEmbeddingProviderTests(SimpleTestCase):

    def test_configuration_and_metadata(self):
        with self.assertRaises(EmbeddingProviderUnavailable):
            OpenAIEmbeddingProvider(api_key="")

        with self.assertRaises(EmbeddingProviderUnavailable):
            OpenAIEmbeddingProvider(api_key=SECRET, model="text-embedding-ada-002")

        provider = OpenAIEmbeddingProvider(api_key=SECRET)
        self.assertEqual(
            provider.identity,
            ("openai", "text-embedding-3-small", 1536, "1"),
        )
        self.assertNotIn(SECRET, repr(provider))
        self.assertIsNone(provider.default_min_similarity)

    def test_output_dimension_order_and_request(self):
        provider, embeddings = provider_with()

        vectors = provider.embed_documents(["alpha", "beta beta", "c"])

        self.assertEqual([len(v) for v in vectors], [DIM, DIM, DIM])
        self.assertEqual(vectors[0], vector_for("alpha"))
        self.assertEqual(vectors[1], vector_for("beta beta"))
        (call,) = embeddings.calls
        self.assertEqual(call["model"], "text-embedding-3-small")
        self.assertEqual(call["dimensions"], DIM)

    def test_repeated_input_is_passed_through_consistently(self):
        provider, _ = provider_with()

        self.assertEqual(provider.embed_text("same"), provider.embed_text("same"))
        self.assertEqual(provider.embed_query("same"), provider.embed_text("same"))

    def test_batching(self):
        provider, embeddings = provider_with()
        texts = [f"text {i}" for i in range(2 * MAX_BATCH_SIZE + 5)]

        vectors = provider.embed_documents(texts)

        self.assertEqual(len(vectors), len(texts))
        self.assertEqual(
            [len(c["input"]) for c in embeddings.calls],
            [MAX_BATCH_SIZE, MAX_BATCH_SIZE, 5],
        )
        self.assertEqual(vectors[-1], vector_for(texts[-1]))

    def test_empty_and_invalid_input_rejected_before_any_call(self):
        provider, embeddings = provider_with()

        for bad in ("", "   ", None, 42):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(EmbeddingInputError):
                    provider.embed_documents(["ok", bad])

        self.assertEqual(embeddings.calls, [])

    def test_long_text(self):
        provider, _ = provider_with()

        self.assertEqual(len(provider.embed_text("x" * MAX_INPUT_CHARACTERS)), DIM)
        with self.assertRaises(EmbeddingInputError):
            provider.embed_text("x" * (MAX_INPUT_CHARACTERS + 1))

    def test_provider_errors_map_without_leaking(self):
        cases = (
            (http_error(openai.AuthenticationError, 401), EmbeddingProviderUnavailable),
            (http_error(openai.PermissionDeniedError, 403), EmbeddingProviderUnavailable),
            (http_error(openai.RateLimitError, 429), EmbeddingProviderUnavailable),
            (openai.APITimeoutError(request=SimpleNamespace()), EmbeddingProviderUnavailable),
            (openai.APIConnectionError(message=SECRET, request=SimpleNamespace()),
             EmbeddingProviderUnavailable),
            (http_error(openai.InternalServerError, 503), EmbeddingProviderUnavailable),
            (http_error(openai.BadRequestError, 400), EmbeddingProviderError),
        )
        for error, expected in cases:
            with self.subTest(error=type(error).__name__):
                provider, _ = provider_with(error=error)
                with self.assertRaises(expected) as ctx:
                    provider.embed_text("hello")
                self.assertNotIn(SECRET, str(ctx.exception))
                self.assertIsNone(ctx.exception.__cause__)

    def test_malformed_responses_rejected(self):
        mutations = {
            "missing vector": lambda data: data[:-1],
            "wrong dimension": lambda data: [
                SimpleNamespace(index=d.index, embedding=d.embedding[:-1]) for d in data
            ],
            "non-finite": lambda data: [
                SimpleNamespace(index=d.index, embedding=[math.nan] * DIM) for d in data
            ],
            "duplicate index": lambda data: [
                SimpleNamespace(index=0, embedding=d.embedding) for d in data
            ],
            "not a list": lambda data: None,
        }
        for label, mutate in mutations.items():
            with self.subTest(case=label):
                provider, _ = provider_with(mutate=mutate)
                with self.assertRaises(EmbeddingProviderError):
                    provider.embed_documents(["a", "b"])


class EmbeddingConfigurationTests(SimpleTestCase):

    def test_default_is_the_local_hashing_provider(self):
        self.assertIsInstance(get_default_embedding_provider(), HashingEmbeddingProvider)

    def test_openai_selection_requires_key_and_never_falls_back(self):
        with override_settings(OSUSU_EMBEDDING_PROVIDER="openai",
                               OSUSU_EMBEDDING_API_KEY=""):
            with self.assertRaises(EmbeddingProviderUnavailable):
                get_default_embedding_provider()

        with override_settings(OSUSU_EMBEDDING_PROVIDER="openai",
                               OSUSU_EMBEDDING_API_KEY=SECRET,
                               OSUSU_EMBEDDING_DIMENSIONS=512):
            provider = get_default_embedding_provider()
        self.assertEqual(provider.identity[2], 512)

        for name in ("voyage", "", "unknown"):
            with self.subTest(name=name):
                with override_settings(OSUSU_EMBEDDING_PROVIDER=name):
                    with self.assertRaises(EmbeddingProviderUnavailable):
                        get_default_embedding_provider()

    def test_similarity_threshold_rules(self):
        hashing = HashingEmbeddingProvider()
        openai_provider = OpenAIEmbeddingProvider(api_key=SECRET)

        self.assertEqual(get_min_similarity(hashing), 0.03)

        # The production model has no measured default: fail closed.
        with self.assertRaises(EmbeddingProviderUnavailable):
            get_min_similarity(openai_provider)

        with override_settings(OSUSU_RAG_MIN_SIMILARITY="0.42"):
            self.assertEqual(get_min_similarity(openai_provider), 0.42)
            self.assertEqual(get_min_similarity(hashing), 0.42)

        for bad in ("1.5", "-2"):
            with self.subTest(value=bad):
                with override_settings(OSUSU_RAG_MIN_SIMILARITY=bad):
                    with self.assertRaises(EmbeddingProviderUnavailable):
                        get_min_similarity(hashing)
