"""
Read-only retrieval of knowledge chunks.

The retriever requires an explicit circle scope and cannot search across
all circles. It does NOT check who is asking: user-facing callers must go
through KnowledgeAccessService, which authorizes the user first.
"""

from dataclasses import dataclass

from knowledge.models import KnowledgeChunk

from services.knowledge.embedding_service import (
    get_default_embedding_provider,
    get_min_similarity,
)
from services.knowledge.index_service import get_default_vector_store
from services.knowledge.vector_store import SearchScope, VectorRecord


MAX_TOP_K = 20
MAX_QUERY_LENGTH = 2000


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    document_id: str
    document_type: str
    title: str
    content: str
    score: float
    # Enough for an answer to cite its source; no vectors, no user ids.
    citation: dict


class KnowledgeRetriever:
    """
    `min_similarity`: chunks scoring at or below it are not evidence.
    Defaults to OSUSU_RAG_MIN_SIMILARITY or the provider's measured value
    (get_min_similarity), and fails closed if neither exists. An empty
    result is a normal, expected outcome ("I don't know").
    """

    def __init__(self, *, provider=None, store=None, min_similarity=None):
        self.provider = provider or get_default_embedding_provider()
        self.store = store or get_default_vector_store(self.provider)
        self.min_similarity = (
            get_min_similarity(self.provider)
            if min_similarity is None
            else float(min_similarity)
        )

    def retrieve(
        self,
        query,
        *,
        circle_ids,
        document_types=None,
        entity_type=None,
        entity_id=None,
        top_k=5,
        min_score=None,
    ) -> list[RetrievedChunk]:

        if min_score is None:
            min_score = self.min_similarity

        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string.")

        if len(query) > MAX_QUERY_LENGTH:
            raise ValueError(
                f"query must be at most {MAX_QUERY_LENGTH} characters."
            )

        if not 1 <= top_k <= MAX_TOP_K:
            raise ValueError(f"top_k must be between 1 and {MAX_TOP_K}.")

        scope = SearchScope(
            circle_ids=frozenset(circle_ids or ()),
            document_types=(
                frozenset(document_types) if document_types else None
            ),
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
        )

        matches = [
            m for m in self.store.similarity_search(
                self.provider.embed_query(query),
                scope=scope,
                top_k=top_k,
            )
            if m.score > min_score
        ]

        chunks = {
            str(c.id): c
            for c in KnowledgeChunk.objects
            .select_related("document")
            .filter(id__in=[m.chunk_id for m in matches])
        }

        results = []
        for match in matches:
            chunk = chunks.get(match.chunk_id)
            if chunk is None:
                continue  # stale vector; chunk was regenerated

            document = chunk.document

            # Defence in depth: re-check scope against the database row,
            # never trusting the vector store's copy of the metadata.
            if not scope.matches(VectorRecord(
                chunk_id=match.chunk_id,
                vector=(),
                circle_id=str(document.circle_id),
                document_type=document.document_type,
                entity_type=document.entity_type,
                entity_id=document.entity_id,
            )):
                continue

            results.append(RetrievedChunk(
                chunk_id=str(chunk.id),
                document_id=str(document.id),
                document_type=document.document_type,
                title=document.title,
                content=chunk.content,
                score=match.score,
                citation={
                    "document_id": str(document.id),
                    "document_type": document.document_type,
                    "document_version": document.version,
                    "schema_version": document.schema_version,
                    "circle_id": str(document.circle_id),
                    "source_entity_type": document.entity_type,
                    "source_entity_id": document.entity_id,
                    "chunk_index": chunk.chunk_index,
                    "chunk_count": chunk.chunk_count,
                    "generated_at": document.generated_at.isoformat(),
                },
            ))

        return results
