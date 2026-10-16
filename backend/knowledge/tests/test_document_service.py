from unittest import mock

from django.db import connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext

from knowledge.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentType as T,
)

from services.knowledge.chunker import chunk_text
from services.knowledge.document_service import KnowledgeDocumentService
from services.knowledge.schema import KNOWLEDGE_SCHEMA_VERSION, sha256_hex

from .fixtures import KnowledgeFixture, written_tables


# Any version other than the current one (independent of its value).
NEXT_SCHEMA_VERSION = f"{KNOWLEDGE_SCHEMA_VERSION}-next"


DOCUMENT_COUNT = 9  # 5 circle-level + 4 member contribution documents


class DocumentSyncTests(KnowledgeFixture):

    def sync(self, **kwargs):
        return KnowledgeDocumentService.sync_circle(self.circle, **kwargs)

    def doc(self, document_type):
        return KnowledgeDocument.objects.get(
            circle=self.circle,
            document_type=document_type,
        )

    def test_first_sync_creates_versioned_documents_and_chunks(self):
        result = self.sync()

        self.assertEqual(len(result.created), DOCUMENT_COUNT)
        self.assertEqual(
            KnowledgeDocument.objects.filter(circle=self.circle).count(),
            DOCUMENT_COUNT,
        )

        for document in KnowledgeDocument.objects.all():
            with self.subTest(document=document.document_type):
                self.assertEqual(document.version, 1)
                self.assertEqual(
                    document.schema_version,
                    KNOWLEDGE_SCHEMA_VERSION,
                )
                self.assertEqual(
                    document.metadata["schema_version"],
                    KNOWLEDGE_SCHEMA_VERSION,
                )
                self.assertEqual(document.metadata["document_version"], 1)
                self.assertEqual(
                    document.metadata["content_hash"],
                    document.content_hash,
                )
                self.assertIn("generated_at", document.metadata)
                self.assertGreaterEqual(document.chunks.count(), 1)

    def test_resync_of_unchanged_data_writes_nothing(self):
        self.sync()
        before = list(
            KnowledgeDocument.objects.order_by("id").values_list(
                "id", "version", "content_hash", "updated_at",
            )
        )
        chunk_ids = set(KnowledgeChunk.objects.values_list("id", flat=True))

        with CaptureQueriesContext(connection) as queries:
            result = self.sync()

        self.assertFalse(result.changed)
        self.assertEqual(len(result.unchanged), DOCUMENT_COUNT)
        self.assertEqual(written_tables(queries), set())
        self.assertEqual(
            list(
                KnowledgeDocument.objects.order_by("id").values_list(
                    "id", "version", "content_hash", "updated_at",
                )
            ),
            before,
        )
        self.assertEqual(
            set(KnowledgeChunk.objects.values_list("id", flat=True)),
            chunk_ids,
        )

    def test_changed_source_bumps_version_and_regenerates_chunks(self):
        self.sync()
        summary = self.doc(T.CIRCLE_SUMMARY)
        old_hash = summary.content_hash
        old_chunks = set(summary.chunks.values_list("id", flat=True))
        payout_hash = self.doc(T.PAYOUT_SUMMARY).content_hash

        self.constitution.quorum_percentage = 75
        self.constitution.save()

        result = self.sync()
        summary.refresh_from_db()

        self.assertIn(summary.id, result.updated)
        self.assertEqual(summary.version, 2)
        self.assertEqual(summary.metadata["document_version"], 2)
        self.assertNotEqual(summary.content_hash, old_hash)
        self.assertIn("Governance quorum is 75%.", summary.content)
        self.assertTrue(
            old_chunks.isdisjoint(
                summary.chunks.values_list("id", flat=True)
            )
        )
        self.assertEqual(
            summary.chunks.first().metadata["document_version"],
            2,
        )
        # Unrelated documents untouched.
        self.assertEqual(
            self.doc(T.PAYOUT_SUMMARY).content_hash,
            payout_hash,
        )
        self.assertEqual(self.doc(T.PAYOUT_SUMMARY).version, 1)

    def test_schema_version_change_regenerates_everything(self):
        self.sync()

        with mock.patch(
            "services.knowledge.schema.KNOWLEDGE_SCHEMA_VERSION",
            NEXT_SCHEMA_VERSION,
        ), mock.patch(
            "services.knowledge.document_service.KNOWLEDGE_SCHEMA_VERSION",
            NEXT_SCHEMA_VERSION,
        ):
            result = self.sync()

        self.assertEqual(len(result.updated), DOCUMENT_COUNT)
        self.assertEqual(
            set(
                KnowledgeDocument.objects.values_list(
                    "schema_version", flat=True,
                )
            ),
            {NEXT_SCHEMA_VERSION},
        )

    def test_documents_for_vanished_sources_are_removed(self):
        self.sync()
        carol_doc = KnowledgeDocument.objects.get(
            entity_type="circle_membership",
            entity_id=str(self.m_carol.id),
        )

        # Carol leaves and has no obligations -> no contribution document.
        self.m_carol.status = "left"
        self.m_carol.save()

        result = self.sync()

        self.assertIn(carol_doc.id, result.deleted)
        self.assertFalse(
            KnowledgeDocument.objects.filter(pk=carol_doc.pk).exists()
        )
        self.assertFalse(
            KnowledgeChunk.objects.filter(document_id=carol_doc.pk).exists()
        )

    def test_chunks_preserve_document_traceability(self):
        self.sync(chunk_size=300, chunk_overlap=50)
        summary = self.doc(T.CIRCLE_SUMMARY)
        chunks = list(summary.chunks.order_by("chunk_index"))

        self.assertGreater(len(chunks), 1)
        self.assertEqual(
            [c.chunk_index for c in chunks],
            list(range(len(chunks))),
        )

        for chunk in chunks:
            with self.subTest(chunk=chunk.chunk_index):
                self.assertEqual(chunk.chunk_count, len(chunks))
                self.assertTrue(chunk.content.startswith(summary.title))
                self.assertEqual(chunk.content_hash, sha256_hex(chunk.content))
                self.assertEqual(
                    chunk.metadata,
                    {
                        "document_id": str(summary.id),
                        "document_type": T.CIRCLE_SUMMARY,
                        "document_version": 1,
                        "schema_version": KNOWLEDGE_SCHEMA_VERSION,
                        "circle_id": str(self.circle.id),
                        "source_entity_type": "circle",
                        "source_entity_id": str(self.circle.id),
                        "subject_user_id": None,
                        "title": summary.title,
                        "chunk_index": chunk.chunk_index,
                        "chunk_count": len(chunks),
                    },
                )


class ChunkerTests(SimpleTestCase):

    CONTENT = "\n".join([
        "Intro paragraph line one.",
        "Intro paragraph line two.",
        "",
        "## Section A",
        *[f"- Item A{i}: some descriptive text about item {i}." for i in range(12)],
        "",
        "## Section B",
        "Short section B.",
    ])

    def chunks(self, **kwargs):
        return chunk_text(title="Doc Title", content=self.CONTENT, **kwargs)

    def test_deterministic(self):
        self.assertEqual(
            self.chunks(chunk_size=300, chunk_overlap=60),
            self.chunks(chunk_size=300, chunk_overlap=60),
        )

    def test_indexes_counts_and_title_prefix(self):
        chunks = self.chunks(chunk_size=300, chunk_overlap=60)

        self.assertGreater(len(chunks), 2)
        self.assertEqual([c.index for c in chunks], list(range(len(chunks))))
        for chunk in chunks:
            self.assertEqual(chunk.count, len(chunks))
            self.assertTrue(chunk.content.startswith("Doc Title\n\n"))
            self.assertLessEqual(len(chunk.content), 300)

    def test_no_content_is_lost_and_lines_are_never_cut(self):
        chunks = self.chunks(chunk_size=300, chunk_overlap=60)
        chunk_lines = {
            line for c in chunks for line in c.content.split("\n")
        }

        for line in self.CONTENT.split("\n"):
            if line.strip():
                self.assertIn(line, chunk_lines)

    def test_split_sections_repeat_their_heading(self):
        chunks = self.chunks(chunk_size=300, chunk_overlap=0)
        with_a_items = [c for c in chunks if "- Item A" in c.content]

        self.assertGreater(len(with_a_items), 1)
        for chunk in with_a_items:
            self.assertIn("## Section A", chunk.content)

    def test_small_document_is_one_chunk(self):
        (chunk,) = chunk_text(title="T", content="Just one line.")

        self.assertEqual(chunk.content, "T\n\nJust one line.")
        self.assertEqual((chunk.index, chunk.count), (0, 1))

    def test_overlap_repeats_trailing_lines(self):
        no_overlap = self.chunks(chunk_size=300, chunk_overlap=0)
        overlap = self.chunks(chunk_size=300, chunk_overlap=90)

        def body_lines(chunks):
            return sum(len(c.content.split("\n")) for c in chunks)

        self.assertGreater(body_lines(overlap), body_lines(no_overlap))

    def test_invalid_parameters(self):
        for kwargs in (
            {"chunk_size": 100},
            {"chunk_size": 300, "chunk_overlap": 150},
            {"chunk_size": 300, "chunk_overlap": -1},
        ):
            with self.subTest(**kwargs):
                with self.assertRaises(ValueError):
                    self.chunks(**kwargs)
