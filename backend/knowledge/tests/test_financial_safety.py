import ast
import inspect
import io

from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext

import services.knowledge.access_service
import services.knowledge.chunker
import services.knowledge.document_builder
import services.knowledge.document_service
import services.knowledge.embedding_service
import services.knowledge.index_service
import services.knowledge.retriever
import services.knowledge.schema
import services.knowledge.vector_store
from knowledge.models import KnowledgeDocument

from services.knowledge.access_service import KnowledgeAccessService
from services.knowledge.document_builder import KnowledgeDocumentBuilder
from services.knowledge.embedding_service import HashingEmbeddingProvider
from services.knowledge.index_service import KnowledgeIndexService
from services.knowledge.retriever import KnowledgeRetriever
from services.knowledge.vector_store import DatabaseVectorStore

from .fixtures import KnowledgeFixture, written_tables


KNOWLEDGE_TABLES = {
    "knowledge_knowledgedocument",
    "knowledge_knowledgechunk",
    "knowledge_knowledgeembedding",
}


class FinancialSafetyTests(KnowledgeFixture):

    def setUp(self):
        super().setUp()
        self.provider = HashingEmbeddingProvider()
        self.store = DatabaseVectorStore.for_provider(self.provider)

    def test_document_generation_changes_no_domain_state(self):
        before = self.domain_snapshot()

        with CaptureQueriesContext(connection) as queries:
            KnowledgeDocumentBuilder.build_circle_documents(self.circle)

        self.assertEqual(written_tables(queries), set())
        self.assertEqual(self.domain_snapshot(), before)

    def test_indexing_writes_only_knowledge_tables(self):
        before = self.domain_snapshot()

        with CaptureQueriesContext(connection) as queries:
            KnowledgeIndexService.index_circle(
                self.circle,
                provider=self.provider,
                store=self.store,
            )

        self.assertTrue(written_tables(queries))
        self.assertLessEqual(written_tables(queries), KNOWLEDGE_TABLES)
        self.assertEqual(self.domain_snapshot(), before)

    def test_retrieval_changes_nothing(self):
        KnowledgeIndexService.index_circle(
            self.circle,
            provider=self.provider,
            store=self.store,
        )
        before = self.domain_snapshot()
        documents = list(KnowledgeDocument.objects.values_list(
            "id", "version", "content_hash",
        ))

        with CaptureQueriesContext(connection) as queries:
            KnowledgeAccessService.retrieve_for_user(
                user=self.alice,
                circle_id=self.circle.id,
                query="pay the payout approve vote complete payment ledger",
                top_k=20,
                retriever=KnowledgeRetriever(
                    provider=self.provider,
                    store=self.store,
                ),
            )

        self.assertEqual(written_tables(queries), set())
        self.assertEqual(self.domain_snapshot(), before)
        self.assertEqual(
            list(KnowledgeDocument.objects.values_list(
                "id", "version", "content_hash",
            )),
            documents,
        )

    def test_management_command_writes_only_knowledge_tables(self):
        before = self.domain_snapshot()

        with CaptureQueriesContext(connection) as queries:
            call_command("build_knowledge", stdout=io.StringIO())

        self.assertLessEqual(written_tables(queries), KNOWLEDGE_TABLES)
        self.assertEqual(self.domain_snapshot(), before)
        self.assertEqual(
            set(KnowledgeDocument.objects.values_list(
                "circle_id", flat=True,
            )),
            {self.circle.id, self.other_circle.id},
        )


class KnowledgeImportBoundaryTests(SimpleTestCase):
    """The knowledge layer may read engines, never call mutating services."""

    MODULES = (
        services.knowledge.access_service,
        services.knowledge.chunker,
        services.knowledge.document_builder,
        services.knowledge.document_service,
        services.knowledge.embedding_service,
        services.knowledge.index_service,
        services.knowledge.retriever,
        services.knowledge.schema,
        services.knowledge.vector_store,
    )

    FORBIDDEN = (
        "services.payments",
        "services.payouts",
        "services.finance.ledger_service",
        "services.finance.contribution_service",
        "services.finance.obligation_service",
        "services.finance.overdue_service",
        "services.governance",
        "services.circles.circle_service",
        "services.circles.financial_lock_engine",
        "services.circles.formation_service",
        "services.circles.invitation_service",
        "services.circles.constitution_service",
        "services.risk.assessment_service",
        "services.risk.feature_snapshot_service",
        "services.risk.outcome_service",
        "services.audit",
    )

    def test_no_mutating_service_is_imported(self):
        for module in self.MODULES:
            tree = ast.parse(inspect.getsource(module))
            imported = {
                node.module
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module
            } | {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            }

            with self.subTest(module=module.__name__):
                self.assertEqual(
                    [m for m in imported if m.startswith(self.FORBIDDEN)],
                    [],
                )
