"""
Indexing never holds a transaction across the external embedding call,
never partially replaces valid vectors, and re-plans when the source data
changes while embeddings are being computed.
"""

import math

from django.db import connection

from knowledge.models import KnowledgeEmbedding

from services.knowledge.embedding_service import (
    EmbeddingProviderUnavailable,
    HashingEmbeddingProvider,
)
from services.knowledge.index_service import (
    MAX_PLAN_ATTEMPTS,
    KnowledgeIndexingError,
    KnowledgeIndexService,
)
from services.knowledge.retriever import KnowledgeRetriever
from services.knowledge.vector_store import DatabaseVectorStore

from .fixtures import KnowledgeFixture
from .test_embedding_identity import knowledge_snapshot


class RecordingProvider(HashingEmbeddingProvider):

    def __init__(self, on_call=None):
        super().__init__()
        self.on_call = on_call
        self.calls = []

    def embed_documents(self, texts):
        self.calls.append({
            "texts": list(texts),
            # TestCase wraps each test in atomic blocks; the service must
            # not add one around the external call.
            "atomic_depth": len(connection.atomic_blocks),
        })
        if self.on_call:
            self.on_call(len(self.calls))
        return super().embed_documents(texts)


class BackgroundIndexingTests(KnowledgeFixture):

    def setUp(self):
        super().setUp()
        self.provider = HashingEmbeddingProvider()
        self.store = DatabaseVectorStore.for_provider(self.provider)
        KnowledgeIndexService.index_circle(self.circle, provider=self.provider,
                                           store=self.store)

    def index(self, provider):
        return KnowledgeIndexService.index_circle(
            self.circle, provider=provider,
            store=DatabaseVectorStore.for_provider(provider),
        )

    def change_source(self):
        self.constitution.quorum_percentage += 1
        self.constitution.save()

    def assert_fully_indexed(self):
        chunk_ids = set(
            str(c) for c in KnowledgeEmbedding.objects
            .filter(chunk__document__circle=self.circle)
            .values_list("chunk_id", flat=True)
        )
        from knowledge.models import KnowledgeChunk
        self.assertEqual(
            chunk_ids,
            {str(c) for c in KnowledgeChunk.objects.filter(
                document__circle=self.circle).values_list("id", flat=True)},
        )

    def test_embedding_call_runs_outside_any_transaction(self):
        baseline = len(connection.atomic_blocks)
        self.change_source()
        provider = RecordingProvider()

        self.index(provider)

        (call,) = provider.calls
        self.assertEqual(call["atomic_depth"], baseline)
        self.assertGreater(len(call["texts"]), 0)

    def test_nothing_to_embed_makes_no_external_call(self):
        provider = RecordingProvider()
        result = self.index(provider)

        self.assertEqual(provider.calls, [])
        self.assertEqual(result.embedded, 0)

    def test_only_changed_chunks_are_embedded(self):
        self.change_source()
        provider = RecordingProvider()
        self.index(provider)

        (call,) = provider.calls
        self.assertTrue(all("Circle: Manchester Developers" in t for t in call["texts"]))

    def test_source_change_during_embedding_is_replanned(self):
        # The first embedding call races with a further data change.
        self.change_source()
        provider = RecordingProvider(
            on_call=lambda n: self.change_source() if n == 1 else None)

        result = self.index(provider)

        self.assertEqual(len(provider.calls), 2)
        self.assertGreater(result.embedded, 0)
        self.assert_fully_indexed()
        (top,) = KnowledgeRetriever(provider=self.provider, store=self.store).retrieve(
            "governance quorum", circle_ids={self.circle.id}, top_k=1)
        self.assertIn(f"Governance quorum is {self.constitution.quorum_percentage}%.",
                      top.content)

    def test_data_that_never_settles_changes_nothing(self):
        self.change_source()  # something to index
        before = knowledge_snapshot()
        provider = RecordingProvider(on_call=lambda n: self.change_source())

        with self.assertRaises(KnowledgeIndexingError):
            self.index(provider)

        self.assertEqual(len(provider.calls), MAX_PLAN_ATTEMPTS)
        self.assertEqual(knowledge_snapshot(), before)

    def test_invalid_vectors_replace_nothing(self):
        class NaNProvider(HashingEmbeddingProvider):
            def embed_documents(self, texts):
                vectors = super().embed_documents(texts)
                vectors[-1] = [math.nan] * self.dimension
                return vectors

        class ShortProvider(HashingEmbeddingProvider):
            def embed_documents(self, texts):
                return [v[:-1] for v in super().embed_documents(texts)]

        self.change_source()
        for provider in (NaNProvider(), ShortProvider()):
            with self.subTest(provider=type(provider).__name__):
                before = knowledge_snapshot()
                with self.assertRaises(KnowledgeIndexingError):
                    self.index(provider)
                self.assertEqual(knowledge_snapshot(), before)

    def test_partial_provider_failure_keeps_every_existing_vector(self):
        self.change_source()
        before = knowledge_snapshot()

        class FailsMidway(HashingEmbeddingProvider):
            def embed_documents(self, texts):
                raise EmbeddingProviderUnavailable("Embedding provider timed out.")

        with self.assertRaises(KnowledgeIndexingError):
            self.index(FailsMidway())

        self.assertEqual(knowledge_snapshot(), before)
        # Old, valid answers are still served.
        (top,) = KnowledgeRetriever(provider=self.provider, store=self.store).retrieve(
            "governance quorum", circle_ids={self.circle.id}, top_k=1)
        self.assertIn("Governance quorum is 60%.", top.content)

    def test_missing_vector_for_unchanged_chunk_is_backfilled(self):
        victim = KnowledgeEmbedding.objects.filter(
            chunk__document__circle=self.circle).first()
        victim.delete()
        provider = RecordingProvider()

        result = self.index(provider)

        self.assertEqual(result.embedded, 1)
        self.assertEqual(len(provider.calls[0]["texts"]), 1)
        self.assert_fully_indexed()
