from knowledge.models import KnowledgeChunk, KnowledgeDocument, KnowledgeEmbedding

from services.knowledge.embedding_service import (
    EmbeddingProviderUnavailable,
    HashingEmbeddingProvider,
)
from services.knowledge.index_service import (
    KnowledgeIndexingError,
    KnowledgeIndexService,
)
from services.knowledge.retriever import KnowledgeRetriever
from services.knowledge.vector_store import (
    DatabaseVectorStore,
    InMemoryVectorStore,
    SearchScope,
)

from .fixtures import KnowledgeFixture


class OtherModelProvider(HashingEmbeddingProvider):
    """Same provider family, different model version."""

    model = "hashing-lexical-v9"
    embedding_version = "9"


class FailingProvider(HashingEmbeddingProvider):

    def embed_documents(self, texts):
        raise EmbeddingProviderUnavailable("down")


class WrongCountProvider(HashingEmbeddingProvider):

    def embed_documents(self, texts):
        return super().embed_documents(texts)[:-1]


def knowledge_snapshot():
    return {
        "documents": list(KnowledgeDocument.objects.order_by("id").values_list(
            "id", "version", "content_hash")),
        "chunks": sorted(KnowledgeChunk.objects.values_list("id", flat=True)),
        "embeddings": list(KnowledgeEmbedding.objects.order_by("id").values_list(
            "id", "chunk_id", "provider", "model", "dimension",
            "embedding_version")),
    }


class EmbeddingIdentityTests(KnowledgeFixture):

    def setUp(self):
        super().setUp()
        self.v2 = HashingEmbeddingProvider()
        self.store_v2 = DatabaseVectorStore.for_provider(self.v2)
        KnowledgeIndexService.index_circle(self.circle, provider=self.v2,
                                           store=self.store_v2)

    def test_identity_is_persisted_with_every_vector(self):
        self.assertEqual(
            set(KnowledgeEmbedding.objects.values_list(
                "provider", "model", "dimension", "embedding_version")),
            {("hashing-lexical-v2-d4096", "hashing-lexical-v2", 4096, "2")},
        )

    def test_vectors_from_another_model_are_invisible(self):
        other = OtherModelProvider()
        other_store = DatabaseVectorStore.for_provider(other)

        self.assertEqual(other_store.chunk_ids(self.circle.id), set())
        self.assertEqual(
            other_store.similarity_search(
                other.embed_query("treasury balance"),
                scope=SearchScope(circle_ids={self.circle.id}),
                top_k=5,
            ),
            [],
        )

    def test_vectors_of_another_dimension_are_invisible(self):
        small = HashingEmbeddingProvider(dimension=64)
        store = DatabaseVectorStore(
            provider_name=self.v2.name,  # same name, different dimension
            dimension=64,
            model=self.v2.model,
            embedding_version=self.v2.embedding_version,
        )

        self.assertEqual(store.chunk_ids(self.circle.id), set())
        self.assertEqual(
            store.similarity_search(
                small.embed_query("treasury"),
                scope=SearchScope(circle_ids={self.circle.id}),
                top_k=5,
            ),
            [],
        )

    def test_legacy_rows_without_identity_are_stale(self):
        KnowledgeEmbedding.objects.update(model="", embedding_version="")

        retriever = KnowledgeRetriever(provider=self.v2, store=self.store_v2)
        self.assertEqual(
            retriever.retrieve("current treasury balance",
                               circle_ids={self.circle.id}),
            [],
        )

        result = KnowledgeIndexService.index_circle(
            self.circle, provider=self.v2, store=self.store_v2,
        )

        self.assertEqual(result.embedded, KnowledgeChunk.objects.filter(
            document__circle=self.circle).count())
        self.assertEqual(
            set(KnowledgeEmbedding.objects.values_list("model", flat=True)),
            {"hashing-lexical-v2"},
        )
        self.assertTrue(retriever.retrieve("current treasury balance",
                                           circle_ids={self.circle.id}))

    def test_model_change_reembeds_and_replaces_in_place(self):
        chunk_count = KnowledgeChunk.objects.filter(document__circle=self.circle).count()
        other = OtherModelProvider()

        result = KnowledgeIndexService.index_circle(
            self.circle, provider=other,
            store=DatabaseVectorStore.for_provider(other),
        )

        self.assertEqual(result.embedded, chunk_count)
        # One row per (chunk, provider): replaced, not duplicated.
        self.assertEqual(KnowledgeEmbedding.objects.count(), chunk_count)
        self.assertEqual(
            set(KnowledgeEmbedding.objects.values_list("model", flat=True)),
            {"hashing-lexical-v9"},
        )
        self.assertEqual(self.store_v2.chunk_ids(self.circle.id), set())

    def test_store_requires_complete_identity(self):
        for kwargs in (
            {"provider_name": "p", "dimension": 8, "model": "", "embedding_version": "1"},
            {"provider_name": "p", "dimension": 8, "model": "m", "embedding_version": ""},
            {"provider_name": "", "dimension": 8, "model": "m", "embedding_version": "1"},
        ):
            with self.subTest(**kwargs):
                with self.assertRaises(ValueError):
                    DatabaseVectorStore(**kwargs)


class IndexingFailureTests(KnowledgeFixture):

    def setUp(self):
        super().setUp()
        self.v2 = HashingEmbeddingProvider()
        self.store = DatabaseVectorStore.for_provider(self.v2)
        KnowledgeIndexService.index_circle(self.circle, provider=self.v2,
                                           store=self.store)

        # Change source data so the next index would rewrite documents.
        self.constitution.quorum_percentage = 90
        self.constitution.save()
        self.m_carol.status = "left"
        self.m_carol.save()

    def assert_failure_changes_nothing(self, provider, store=None):
        before = knowledge_snapshot()

        with self.assertRaises(KnowledgeIndexingError):
            KnowledgeIndexService.index_circle(
                self.circle,
                provider=provider,
                store=store or DatabaseVectorStore.for_provider(provider),
            )

        self.assertEqual(knowledge_snapshot(), before)

    def test_provider_outage_rolls_back_everything(self):
        self.assert_failure_changes_nothing(FailingProvider())

    def test_wrong_vector_count_rolls_back_everything(self):
        self.assert_failure_changes_nothing(WrongCountProvider())

    def test_existing_answers_still_retrievable_after_failure(self):
        self.assert_failure_changes_nothing(FailingProvider())

        (top,) = KnowledgeRetriever(provider=self.v2, store=self.store).retrieve(
            "governance quorum", circle_ids={self.circle.id}, top_k=1,
        )
        self.assertIn("Governance quorum is 60%.", top.content)

    def test_in_memory_store_untouched_by_failure(self):
        memory = InMemoryVectorStore()
        KnowledgeIndexService.index_circle(self.circle, provider=self.v2, store=memory)
        before = set(memory.chunk_ids(self.circle.id))

        # Something must need embedding, or the provider is (correctly)
        # never called.
        self.constitution.grace_period_days = 14
        self.constitution.save()

        with self.assertRaises(KnowledgeIndexingError):
            KnowledgeIndexService.index_circle(
                self.circle, provider=FailingProvider(), store=memory,
            )

        self.assertEqual(memory.chunk_ids(self.circle.id), before)

    def test_successful_retry_after_failure(self):
        self.assert_failure_changes_nothing(FailingProvider())

        result = KnowledgeIndexService.index_circle(
            self.circle, provider=self.v2, store=self.store,
        )

        self.assertTrue(result.sync.changed)
        self.assertGreater(result.embedded, 0)
