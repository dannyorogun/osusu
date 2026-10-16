"""
Idempotent synchronisation of a circle's knowledge documents and chunks.

Writes ONLY to knowledge tables. Domain data is read through
KnowledgeDocumentBuilder.
"""

from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from knowledge.models import KnowledgeChunk, KnowledgeDocument

from services.knowledge.chunker import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    chunk_text,
)
from services.knowledge.document_builder import KnowledgeDocumentBuilder
from services.knowledge.schema import KNOWLEDGE_SCHEMA_VERSION, sha256_hex


@dataclass
class SyncResult:
    created: list = field(default_factory=list)
    updated: list = field(default_factory=list)
    unchanged: list = field(default_factory=list)
    deleted: list = field(default_factory=list)

    @property
    def changed(self):
        return bool(self.created or self.updated or self.deleted)


class KnowledgeDocumentService:

    @classmethod
    @transaction.atomic
    def sync_circle(
        cls,
        circle,
        *,
        chunk_size=DEFAULT_CHUNK_SIZE,
        chunk_overlap=DEFAULT_CHUNK_OVERLAP,
    ) -> SyncResult:
        built = KnowledgeDocumentBuilder.build_circle_documents(circle)

        existing = {
            (d.document_type, d.entity_type, d.entity_id): d
            for d in (
                KnowledgeDocument.objects
                .select_for_update()
                .filter(circle=circle)
            )
        }

        result = SyncResult()
        generated_at = timezone.now()
        seen = set()

        for doc in built:
            key = (doc.document_type, doc.entity_type, doc.entity_id)
            seen.add(key)
            current = existing.get(key)
            content_hash = doc.content_hash

            if (
                current is not None
                and current.content_hash == content_hash
                and current.schema_version == KNOWLEDGE_SCHEMA_VERSION
            ):
                result.unchanged.append(current.id)
                continue

            if current is None:
                current = KnowledgeDocument(
                    circle_id=doc.circle_id,
                    document_type=doc.document_type,
                    entity_type=doc.entity_type,
                    entity_id=doc.entity_id,
                    version=1,
                )
                bucket = result.created
            else:
                current.chunks.all().delete()
                current.version += 1
                bucket = result.updated

            current.subject_user_id = doc.subject_user_id
            current.title = doc.title
            current.content = doc.content
            current.schema_version = KNOWLEDGE_SCHEMA_VERSION
            current.content_hash = content_hash
            current.generated_at = generated_at
            current.metadata = {
                **doc.metadata,
                "document_version": current.version,
                "content_hash": content_hash,
                "generated_at": generated_at.isoformat(),
            }
            current.save()

            cls._write_chunks(
                current,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
            bucket.append(current.id)

        for key, stale in existing.items():
            if key not in seen:
                result.deleted.append(stale.id)
                stale.delete()

        return result

    @staticmethod
    def _write_chunks(document, *, chunk_size, chunk_overlap):
        pieces = chunk_text(
            title=document.title,
            content=document.content,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

        KnowledgeChunk.objects.bulk_create([
            KnowledgeChunk(
                document=document,
                chunk_index=piece.index,
                chunk_count=piece.count,
                content=piece.content,
                content_hash=sha256_hex(piece.content),
                metadata={
                    "document_id": str(document.id),
                    "document_type": document.document_type,
                    "document_version": document.version,
                    "schema_version": document.schema_version,
                    "circle_id": str(document.circle_id),
                    "source_entity_type": document.entity_type,
                    "source_entity_id": document.entity_id,
                    "subject_user_id": document.metadata.get(
                        "subject_user_id"
                    ),
                    "title": document.title,
                    "chunk_index": piece.index,
                    "chunk_count": piece.count,
                },
            )
            for piece in pieces
        ])
