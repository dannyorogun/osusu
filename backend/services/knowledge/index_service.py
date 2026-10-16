"""
Keeps a vector store in step with a circle's knowledge chunks.

Only chunks without a vector for the ACTIVE embedding identity are
embedded, so re-indexing unchanged data embeds nothing, while switching
model/dimension re-embeds everything.

Three phases, so no database transaction is ever held open across an
external embedding call:

  1. plan   (read-only)   build the documents in memory and collect the
                          text of every chunk that will need a vector;
  2. embed  (no DB lock)  call the provider, then validate EVERY vector
                          (count, dimension, finite) before writing;
  3. write  (one short    sync documents/chunks and replace vectors
             transaction) atomically. Vectors are matched to chunks by
                          content hash; if the data changed after
                          planning, the transaction rolls back and the
                          plan is rebuilt (bounded retries).

All-or-nothing: a provider failure, an invalid vector or data that keeps
changing leaves existing documents, chunks and vectors exactly as they
were - valid production vectors are never partially replaced.

Scheduling: `python manage.py build_knowledge` is the index job (cron or
any scheduler); it is idempotent and safe to re-run. A queue is only
worth adding when knowledge must be re-indexed on every change.
"""

import math
from dataclasses import dataclass

from django.db import transaction

from knowledge.models import KnowledgeChunk, KnowledgeDocument

from services.knowledge.chunker import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    chunk_text,
)
from services.knowledge.document_builder import KnowledgeDocumentBuilder
from services.knowledge.document_service import (
    KnowledgeDocumentService,
    SyncResult,
)
from services.knowledge.embedding_service import (
    EmbeddingError,
    get_default_embedding_provider,
)
from services.knowledge.schema import KNOWLEDGE_SCHEMA_VERSION, sha256_hex
from services.knowledge.vector_store import (
    DatabaseVectorStore,
    VectorRecord,
)


MAX_PLAN_ATTEMPTS = 3


class KnowledgeIndexingError(Exception):
    """Indexing failed; nothing was changed."""


class _PlanOutdated(Exception):
    """Source data changed between planning and writing."""


@dataclass
class IndexResult:
    sync: SyncResult
    embedded: int
    removed: int


def get_default_vector_store(provider):
    return DatabaseVectorStore.for_provider(provider)


class KnowledgeIndexService:

    @classmethod
    def index_circle(cls, circle, *, provider=None, store=None) -> IndexResult:
        provider = provider or get_default_embedding_provider()
        store = store or get_default_vector_store(provider)

        for _ in range(MAX_PLAN_ATTEMPTS):
            texts = cls._plan(circle, store)
            vectors = cls._embed(provider, texts)
            try:
                return cls._write(circle, store, vectors)
            except _PlanOutdated:
                continue

        raise KnowledgeIndexingError(
            "Knowledge kept changing during indexing; no knowledge data "
            "was changed."
        )

    # 1. Plan (read-only)

    @staticmethod
    def _plan(circle, store):
        """{content_hash: text} for every chunk that will need a vector."""
        existing = {
            (d.document_type, d.entity_type, d.entity_id): d
            for d in KnowledgeDocument.objects.filter(circle=circle)
        }
        indexed = store.chunk_ids(circle.id)
        texts = {}

        for doc in KnowledgeDocumentBuilder.build_circle_documents(circle):
            current = existing.get(
                (doc.document_type, doc.entity_type, doc.entity_id)
            )
            unchanged = (
                current is not None
                and current.content_hash == doc.content_hash
                and current.schema_version == KNOWLEDGE_SCHEMA_VERSION
            )

            if unchanged:
                # Chunks are kept as they are; only unindexed ones.
                for chunk in current.chunks.all():
                    if str(chunk.id) not in indexed:
                        texts[chunk.content_hash] = chunk.content
            else:
                # Same chunking as KnowledgeDocumentService.sync_circle.
                for piece in chunk_text(
                    title=doc.title,
                    content=doc.content,
                    chunk_size=DEFAULT_CHUNK_SIZE,
                    chunk_overlap=DEFAULT_CHUNK_OVERLAP,
                ):
                    texts[sha256_hex(piece.content)] = piece.content

        return texts

    # 2. Embed and validate (external call; no transaction, no writes)

    @staticmethod
    def _embed(provider, texts):
        if not texts:
            return {}

        hashes = list(texts)
        try:
            vectors = provider.embed_documents([texts[h] for h in hashes])
        except EmbeddingError as exc:
            raise KnowledgeIndexingError(
                "Indexing failed because the embedding provider failed; "
                "no knowledge data was changed."
            ) from exc

        if len(vectors) != len(hashes) or not all(
            len(v) == provider.dimension
            and all(isinstance(x, (int, float)) and math.isfinite(x) for x in v)
            for v in vectors
        ):
            raise KnowledgeIndexingError(
                "Embedding provider returned invalid vectors; no knowledge "
                "data was changed."
            )

        return {h: tuple(v) for h, v in zip(hashes, vectors)}

    # 3. Write (one short transaction)

    @staticmethod
    def _write(circle, store, vectors):
        with transaction.atomic():
            sync = KnowledgeDocumentService.sync_circle(circle)

            chunks = list(
                KnowledgeChunk.objects
                .filter(document__circle=circle)
                .select_related("document")
                .order_by("document_id", "chunk_index")
            )
            current = {str(c.id) for c in chunks}
            indexed = store.chunk_ids(circle.id)
            missing = [c for c in chunks if str(c.id) not in indexed]

            if any(c.content_hash not in vectors for c in missing):
                raise _PlanOutdated()  # rolls back the sync above

            stale = indexed - current
            store.delete(stale)
            store.upsert([
                VectorRecord(
                    chunk_id=str(chunk.id),
                    vector=vectors[chunk.content_hash],
                    circle_id=str(chunk.document.circle_id),
                    document_type=chunk.document.document_type,
                    entity_type=chunk.document.entity_type,
                    entity_id=chunk.document.entity_id,
                )
                for chunk in missing
            ])

        return IndexResult(
            sync=sync,
            embedded=len(missing),
            removed=len(stale),
        )
