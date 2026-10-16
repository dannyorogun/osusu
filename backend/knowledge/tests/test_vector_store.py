import math
import uuid

from django.test import SimpleTestCase

from knowledge.models import KnowledgeChunk, KnowledgeEmbedding

from services.knowledge.document_service import KnowledgeDocumentService
from services.knowledge.embedding_service import (
    EmbeddingProvider,
    HashingEmbeddingProvider,
)
from services.knowledge.vector_store import (
    DatabaseVectorStore,
    InMemoryVectorStore,
    SearchScope,
    VectorRecord,
)

from .fixtures import KnowledgeFixture


PROVIDER = HashingEmbeddingProvider(dimension=64)


class HashingEmbeddingProviderTests(SimpleTestCase):

    def test_is_an_embedding_provider(self):
        self.assertIsInstance(PROVIDER, EmbeddingProvider)
        self.assertEqual(PROVIDER.name, "hashing-lexical-v2-d64")
        self.assertEqual(
            PROVIDER.identity,
            ("hashing-lexical-v2-d64", "hashing-lexical-v2", 64, "2"),
        )

    def test_vectors_are_deterministic_unit_length(self):
        first = PROVIDER.embed_text("Treasury balance is £65.00")
        second = HashingEmbeddingProvider(dimension=64).embed_text(
            "Treasury balance is £65.00"
        )

        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)
        self.assertAlmostEqual(math.sqrt(sum(v * v for v in first)), 1.0)

    def test_embed_documents_preserves_order(self):
        texts = ["payout window", "treasury balance", "payout window"]
        vectors = PROVIDER.embed_documents(texts)

        self.assertEqual(vectors[0], vectors[2])
        self.assertNotEqual(vectors[0], vectors[1])

    def test_empty_text_is_zero_vector(self):
        self.assertEqual(PROVIDER.embed_text("!!!"), [0.0] * 64)

    def test_lexical_overlap_scores_higher(self):
        def cosine(a, b):
            return sum(x * y for x, y in zip(a, b))

        query = PROVIDER.embed_query("treasury balance")
        related = PROVIDER.embed_text("The current treasury balance is £65")
        unrelated = PROVIDER.embed_text("Governance quorum is 60%")

        self.assertGreater(cosine(query, related), cosine(query, unrelated))

    def test_rejects_tiny_dimension(self):
        with self.assertRaises(ValueError):
            HashingEmbeddingProvider(dimension=4)


def record(chunk_id, text, circle_id="c1", document_type="circle_summary",
           entity_type="circle", entity_id="c1"):
    return VectorRecord(
        chunk_id=chunk_id,
        vector=tuple(PROVIDER.embed_text(text)),
        circle_id=circle_id,
        document_type=document_type,
        entity_type=entity_type,
        entity_id=entity_id,
    )


class SearchScopeTests(SimpleTestCase):

    def test_circle_scope_is_mandatory(self):
        for circle_ids in (None, frozenset(), []):
            with self.subTest(circle_ids=circle_ids):
                with self.assertRaises(ValueError):
                    SearchScope(circle_ids=circle_ids)

    def test_entity_filter_needs_both_parts(self):
        with self.assertRaises(ValueError):
            SearchScope(circle_ids={"c1"}, entity_type="circle")


class InMemoryVectorStoreTests(SimpleTestCase):

    def setUp(self):
        self.store = InMemoryVectorStore()
        self.store.upsert([
            record("a", "treasury balance ledger"),
            record("b", "payout window votes", document_type="payout_summary"),
            record("c", "treasury balance ledger", circle_id="c2",
                   entity_id="c2"),
        ])

    def search(self, text, top_k=5, **scope):
        scope.setdefault("circle_ids", {"c1"})
        return self.store.similarity_search(
            PROVIDER.embed_query(text),
            scope=SearchScope(**scope),
            top_k=top_k,
        )

    def test_similarity_ranking(self):
        matches = self.search("treasury balance")

        self.assertEqual([m.chunk_id for m in matches], ["a", "b"])
        self.assertGreater(matches[0].score, matches[1].score)

    def test_circle_scope_excludes_other_circles(self):
        self.assertNotIn(
            "c",
            [m.chunk_id for m in self.search("treasury balance ledger")],
        )
        self.assertEqual(
            [m.chunk_id for m in self.search("treasury", circle_ids={"c2"})],
            ["c"],
        )

    def test_document_type_filter(self):
        matches = self.search(
            "treasury balance",
            document_types={"payout_summary"},
        )
        self.assertEqual([m.chunk_id for m in matches], ["b"])

    def test_top_k(self):
        self.assertEqual(len(self.search("treasury", top_k=1)), 1)

    def test_update_and_delete(self):
        self.store.upsert([record("a", "governance quorum")])
        top = self.search("governance quorum", top_k=1)[0]
        self.assertEqual(top.chunk_id, "a")
        self.assertAlmostEqual(top.score, 1.0)

        self.store.delete(["a"])
        self.assertEqual(self.store.chunk_ids("c1"), {"b"})


class DatabaseVectorStoreTests(KnowledgeFixture):

    def setUp(self):
        super().setUp()
        KnowledgeDocumentService.sync_circle(self.circle)
        KnowledgeDocumentService.sync_circle(self.other_circle)
        self.store = DatabaseVectorStore.for_provider(PROVIDER)

    def records_for(self, circle):
        return [
            VectorRecord(
                chunk_id=str(chunk.id),
                vector=tuple(PROVIDER.embed_text(chunk.content)),
                circle_id=str(circle.id),
                document_type=chunk.document.document_type,
                entity_type=chunk.document.entity_type,
                entity_id=chunk.document.entity_id,
            )
            for chunk in KnowledgeChunk.objects.filter(
                document__circle=circle,
            ).select_related("document")
        ]

    def test_upsert_update_delete_and_search(self):
        records = self.records_for(self.circle)
        self.store.upsert(records)
        self.store.upsert(self.records_for(self.other_circle))

        ids = {r.chunk_id for r in records}
        self.assertEqual(self.store.chunk_ids(self.circle.id), ids)

        # Update in place: still one row per (chunk, provider).
        self.store.upsert(records[:1])
        self.assertEqual(
            KnowledgeEmbedding.objects.filter(
                chunk_id=records[0].chunk_id,
            ).count(),
            1,
        )

        matches = self.store.similarity_search(
            PROVIDER.embed_query("treasury balance ledger"),
            scope=SearchScope(circle_ids={self.circle.id}),
            top_k=3,
        )
        self.assertEqual(len(matches), 3)
        self.assertTrue(all(m.chunk_id in ids for m in matches))

        self.store.delete([records[0].chunk_id])
        self.assertNotIn(
            records[0].chunk_id,
            self.store.chunk_ids(self.circle.id),
        )

    def test_rejects_wrong_dimension(self):
        with self.assertRaises(ValueError):
            self.store.upsert([
                VectorRecord(
                    chunk_id=str(uuid.uuid4()),
                    vector=(1.0, 0.0),
                    circle_id=str(self.circle.id),
                    document_type="circle_summary",
                    entity_type="circle",
                    entity_id=str(self.circle.id),
                )
            ])

    def test_other_providers_are_ignored(self):
        self.store.upsert(self.records_for(self.circle))
        other = DatabaseVectorStore(
            provider_name="another-model",
            dimension=PROVIDER.dimension,
            model="another-model",
            embedding_version="1",
        )

        self.assertEqual(other.chunk_ids(self.circle.id), set())
        self.assertEqual(
            other.similarity_search(
                PROVIDER.embed_query("treasury"),
                scope=SearchScope(circle_ids={self.circle.id}),
                top_k=5,
            ),
            [],
        )
