import uuid

from django.db import connection
from django.test.utils import CaptureQueriesContext

from circles.models import MembershipStatus
from knowledge.models import (
    KnowledgeChunk,
    KnowledgeDocumentType as T,
    KnowledgeEmbedding,
)

from services.circles.circle_access_service import (
    CircleAccessForbidden,
    CircleNotFound,
)
from services.knowledge.access_service import KnowledgeAccessService
from services.knowledge.embedding_service import HashingEmbeddingProvider
from services.knowledge.index_service import KnowledgeIndexService
from services.knowledge.retriever import KnowledgeRetriever
from services.knowledge.vector_store import (
    DatabaseVectorStore,
    InMemoryVectorStore,
    SearchScope,
)

from .fixtures import KnowledgeFixture, written_tables


class IndexedFixture(KnowledgeFixture):

    def setUp(self):
        super().setUp()
        self.provider = HashingEmbeddingProvider()
        self.store = DatabaseVectorStore.for_provider(self.provider)
        for circle in (self.circle, self.other_circle):
            KnowledgeIndexService.index_circle(
                circle,
                provider=self.provider,
                store=self.store,
            )
        self.retriever = KnowledgeRetriever(
            provider=self.provider,
            store=self.store,
        )

    def retrieve(self, query, circle=None, **kwargs):
        return self.retriever.retrieve(
            query,
            circle_ids={(circle or self.circle).id},
            **kwargs,
        )


class IndexingTests(IndexedFixture):

    def test_every_chunk_is_embedded_once(self):
        self.assertEqual(
            KnowledgeEmbedding.objects.filter(
                chunk__document__circle=self.circle,
            ).count(),
            len(self.store.chunk_ids(self.circle.id)),
        )

    def test_reindexing_unchanged_data_embeds_nothing(self):
        result = KnowledgeIndexService.index_circle(
            self.circle,
            provider=self.provider,
            store=self.store,
        )

        self.assertEqual((result.embedded, result.removed), (0, 0))
        self.assertFalse(result.sync.changed)

    def test_changed_document_is_reembedded(self):
        self.constitution.quorum_percentage = 80
        self.constitution.save()

        result = KnowledgeIndexService.index_circle(
            self.circle,
            provider=self.provider,
            store=self.store,
        )

        self.assertGreater(result.embedded, 0)
        (top,) = self.retrieve(
            "governance quorum",
            top_k=1,
            document_types={T.CIRCLE_SUMMARY},
        )
        self.assertIn("Governance quorum is 80%.", top.content)
        self.assertNotIn("Governance quorum is 60%.", top.content)

    def test_in_memory_store_stays_in_sync(self):
        store = InMemoryVectorStore()
        KnowledgeIndexService.index_circle(
            self.circle, provider=self.provider, store=store,
        )
        self.m_carol.status = "left"
        self.m_carol.save()

        result = KnowledgeIndexService.index_circle(
            self.circle, provider=self.provider, store=store,
        )

        self.assertGreater(result.removed, 0)
        self.assertEqual(
            store.chunk_ids(self.circle.id),
            {
                str(c) for c in KnowledgeChunk.objects.filter(
                    document__circle=self.circle,
                ).values_list("id", flat=True)
            },
        )


class RetrieverTests(IndexedFixture):

    def test_relevant_result_is_returned(self):
        top = self.retrieve("current treasury balance", top_k=1)[0]

        self.assertEqual(top.document_type, T.CIRCLE_FINANCIAL_SUMMARY)
        self.assertIn("£65.00", top.content)

    def test_top_k_is_respected(self):
        for k in (1, 3, 5):
            with self.subTest(top_k=k):
                self.assertLessEqual(
                    len(self.retrieve("member contribution", top_k=k)),
                    k,
                )

    def test_scores_are_descending(self):
        scores = [r.score for r in self.retrieve("payout", top_k=10)]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_document_type_filter(self):
        # Every document mentions the circle name, so only the filter
        # can be narrowing the results.
        unfiltered = self.retrieve("Manchester Developers", top_k=20)
        self.assertGreater(len({r.document_type for r in unfiltered}), 1)

        results = self.retrieve(
            "Manchester Developers",
            document_types={T.PAYOUT_SUMMARY},
        )

        self.assertTrue(results)
        self.assertEqual({r.document_type for r in results}, {T.PAYOUT_SUMMARY})

    def test_irrelevant_query_returns_nothing_rather_than_padding(self):
        self.assertEqual(
            self.retrieve(
                "treasury balance",
                document_types={T.PAYOUT_SUMMARY},
            ),
            [],
        )

    def test_entity_filter(self):
        results = self.retrieve(
            "contribution obligations",
            entity_type="circle_membership",
            entity_id=self.m_bob.id,
        )

        self.assertTrue(results)
        for result in results:
            self.assertEqual(
                result.citation["source_entity_id"],
                str(self.m_bob.id),
            )

    def test_citation_is_traceable_and_carries_no_vectors(self):
        result = self.retrieve("payout window", top_k=1)[0]

        self.assertEqual(
            set(result.citation),
            {
                "document_id",
                "document_type",
                "document_version",
                "schema_version",
                "circle_id",
                "source_entity_type",
                "source_entity_id",
                "chunk_index",
                "chunk_count",
                "generated_at",
            },
        )
        self.assertEqual(result.citation["circle_id"], str(self.circle.id))
        self.assertFalse(hasattr(result, "vector"))

    def test_query_validation(self):
        for kwargs in (
            {"query": ""},
            {"query": "   "},
            {"query": "x" * 2001},
            {"query": "ok", "top_k": 0},
            {"query": "ok", "top_k": 21},
        ):
            with self.subTest(**{k: str(v)[:10] for k, v in kwargs.items()}):
                query = kwargs.pop("query")
                with self.assertRaises(ValueError):
                    self.retrieve(query, **kwargs)

    def test_unscoped_search_is_impossible(self):
        for circle_ids in (None, set(), []):
            with self.subTest(circle_ids=circle_ids):
                with self.assertRaises(ValueError):
                    self.retriever.retrieve("treasury", circle_ids=circle_ids)

    def test_retrieval_is_read_only(self):
        with CaptureQueriesContext(connection) as queries:
            self.retrieve("treasury balance payouts risk", top_k=10)

        self.assertEqual(written_tables(queries), set())


class CircleIsolationTests(IndexedFixture):

    def test_other_circle_never_leaks_even_for_its_own_words(self):
        results = self.retrieve(
            "Birmingham Bakers monthly sourdough fund £75.00",
            top_k=20,
        )

        self.assertTrue(results)
        for result in results:
            self.assertEqual(result.citation["circle_id"], str(self.circle.id))
            self.assertNotIn("Birmingham", result.content)
            self.assertNotIn("sourdough", result.content)

    def test_other_circle_is_reachable_only_in_its_own_scope(self):
        results = self.retrieve(
            "sourdough monthly",
            circle=self.other_circle,
            top_k=3,
        )

        self.assertTrue(results)
        self.assertIn("Birmingham Bakers", results[0].content)

    def test_store_layer_filters_circle_before_scoring(self):
        # First layer on its own (the retriever re-check is the second):
        # even when the other circle's chunks are by far the best match,
        # the store must never return them for this circle's scope.
        other_ids = self.store.chunk_ids(self.other_circle.id)
        self.assertTrue(other_ids)

        matches = self.store.similarity_search(
            self.provider.embed_query(
                "Birmingham Bakers monthly sourdough fund £75.00",
            ),
            scope=SearchScope(circle_ids={self.circle.id}),
            top_k=20,
        )

        self.assertTrue(matches)
        self.assertTrue(
            {m.chunk_id for m in matches}.isdisjoint(other_ids),
            "the vector store returned another circle's chunks",
        )

    def test_tampered_vector_store_metadata_is_rechecked(self):
        # A store that wrongly labels circle B's chunk as circle A's must
        # still not leak it: the retriever re-checks the database row.
        store = InMemoryVectorStore()
        KnowledgeIndexService.index_circle(
            self.other_circle, provider=self.provider, store=store,
        )
        store.upsert([
            record.__class__(**{**record.__dict__, "circle_id": str(self.circle.id)})
            for record in store._records.values()
        ])

        retriever = KnowledgeRetriever(provider=self.provider, store=store)
        results = retriever.retrieve(
            "Birmingham Bakers",
            circle_ids={self.circle.id},
        )

        self.assertEqual(results, [])


class AuthorizedRetrievalTests(IndexedFixture):

    def retrieve_as(self, user, circle=None, query="treasury balance"):
        return KnowledgeAccessService.retrieve_for_user(
            user=user,
            circle_id=(circle or self.circle).id,
            query=query,
            retriever=self.retriever,
        )

    def test_active_members_can_retrieve_their_circle(self):
        for user in (self.alice, self.bob, self.carol):
            with self.subTest(user=user.username):
                results = self.retrieve_as(user)
                self.assertTrue(results)
                self.assertTrue(all(
                    r.citation["circle_id"] == str(self.circle.id)
                    for r in results
                ))

    def test_unrelated_user_gets_not_found(self):
        with self.assertRaises(CircleNotFound):
            self.retrieve_as(self.outsider)

    def test_inactive_members_are_forbidden(self):
        for user in (self.dave, self.erin):
            with self.subTest(user=user.username):
                with self.assertRaises(CircleAccessForbidden):
                    self.retrieve_as(user)

    def test_invited_member_is_forbidden(self):
        invited = self.make_user("invitee")
        self.add_member(invited, MembershipStatus.INVITED)

        with self.assertRaises(CircleAccessForbidden):
            self.retrieve_as(invited)

    def test_random_circle_id_is_not_found(self):
        with self.assertRaises(CircleNotFound):
            KnowledgeAccessService.retrieve_for_user(
                user=self.alice,
                circle_id=uuid.uuid4(),
                query="treasury",
                retriever=self.retriever,
            )

    def test_member_cannot_reach_another_circle_they_are_not_in(self):
        with self.assertRaises(CircleNotFound):
            self.retrieve_as(self.alice, circle=self.other_circle)

    def test_authorization_happens_before_any_search(self):
        with CaptureQueriesContext(connection) as queries:
            with self.assertRaises(CircleNotFound):
                self.retrieve_as(self.outsider)

        self.assertFalse(
            any("knowledge_" in q["sql"] for q in queries),
            "no knowledge table may be queried for an unauthorized user",
        )

    def test_results_expose_no_private_member_information(self):
        results = KnowledgeAccessService.retrieve_for_user(
            user=self.bob,
            circle_id=self.circle.id,
            query="member contribution invited risk trust activity",
            top_k=20,
            retriever=self.retriever,
        )

        for result in results:
            text = result.content + str(result.citation)
            self.assertNotIn("@", text)
            self.assertNotIn("outsider", text)
            self.assertNotIn(str(self.alice.id), text)
