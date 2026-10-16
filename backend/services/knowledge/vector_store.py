"""
Vector storage abstraction.

Every search takes a mandatory SearchScope. Scope filters (circle,
document type, entity) are applied BEFORE similarity scoring, so a vector
from another circle is never even a candidate: similarity is never the
authorization boundary.

Implementations:
- DatabaseVectorStore: vectors in PostgreSQL (knowledge_knowledgeembedding,
  float[]), scope filtered in SQL, cosine scored in numpy. Exact search,
  fine for circle-scoped corpora (hundreds of chunks per circle).
- InMemoryVectorStore: process-local, for tests.

Production path: the local PostgreSQL 18 has no pgvector extension
available. Once installed, replace the float[] column with a pgvector
column + HNSW index and push scoring into SQL; the interface is unchanged.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

from knowledge.models import KnowledgeEmbedding


@dataclass(frozen=True)
class SearchScope:
    """
    Required filters for a search. circle_ids must be non-empty: there is
    deliberately no way to search across all circles.
    """

    circle_ids: frozenset
    document_types: frozenset | None = None
    entity_type: str | None = None
    entity_id: str | None = None

    def __post_init__(self):
        circle_ids = frozenset(str(c) for c in (self.circle_ids or ()))
        if not circle_ids:
            raise ValueError("A search must be scoped to at least one circle.")
        object.__setattr__(self, "circle_ids", circle_ids)

        if self.document_types is not None:
            object.__setattr__(
                self,
                "document_types",
                frozenset(str(t) for t in self.document_types),
            )

        if (self.entity_type is None) != (self.entity_id is None):
            raise ValueError(
                "entity_type and entity_id must be given together."
            )

    def matches(self, record):
        return (
            record.circle_id in self.circle_ids
            and (
                self.document_types is None
                or record.document_type in self.document_types
            )
            and (
                self.entity_type is None
                or (
                    record.entity_type == self.entity_type
                    and record.entity_id == str(self.entity_id)
                )
            )
        )


@dataclass(frozen=True)
class VectorRecord:
    chunk_id: str
    vector: tuple
    circle_id: str
    document_type: str
    entity_type: str
    entity_id: str


@dataclass(frozen=True)
class VectorMatch:
    chunk_id: str
    score: float


class VectorStore(ABC):

    @abstractmethod
    def upsert(self, records: list[VectorRecord]) -> None: ...

    @abstractmethod
    def delete(self, chunk_ids) -> None: ...

    @abstractmethod
    def chunk_ids(self, circle_id) -> set[str]: ...

    @abstractmethod
    def similarity_search(
        self,
        query_vector,
        *,
        scope: SearchScope,
        top_k: int,
    ) -> list[VectorMatch]: ...


def _rank(chunk_ids, matrix, query_vector, top_k):
    if not chunk_ids:
        return []

    query = np.asarray(query_vector, dtype=float)
    if matrix.shape[1] != query.shape[0]:
        raise ValueError(
            f"Query dimension {query.shape[0]} does not match stored "
            f"vectors ({matrix.shape[1]})."
        )

    norms = np.linalg.norm(matrix, axis=1) * (np.linalg.norm(query) or 1.0)
    scores = (matrix @ query) / np.where(norms == 0, 1.0, norms)

    ranked = sorted(
        zip(chunk_ids, scores.tolist()),
        key=lambda pair: (-pair[1], pair[0]),  # stable tie-break
    )

    return [VectorMatch(chunk_id=c, score=s) for c, s in ranked[:top_k]]


class InMemoryVectorStore(VectorStore):

    def __init__(self):
        self._records = {}

    def upsert(self, records):
        for record in records:
            self._records[record.chunk_id] = record

    def delete(self, chunk_ids):
        for chunk_id in chunk_ids:
            self._records.pop(str(chunk_id), None)

    def chunk_ids(self, circle_id):
        return {
            r.chunk_id for r in self._records.values()
            if r.circle_id == str(circle_id)
        }

    def similarity_search(self, query_vector, *, scope, top_k):
        candidates = sorted(
            (r for r in self._records.values() if scope.matches(r)),
            key=lambda r: r.chunk_id,
        )
        if not candidates:
            return []

        return _rank(
            [r.chunk_id for r in candidates],
            np.asarray([r.vector for r in candidates], dtype=float),
            query_vector,
            top_k,
        )


class DatabaseVectorStore(VectorStore):
    """
    Vectors for ONE embedding identity (provider, model, dimension,
    embedding_version), persisted in PostgreSQL. Rows written by any other
    identity are invisible to search and count as "not indexed", so a
    model change triggers re-embedding instead of mixing vector spaces.
    """

    def __init__(self, *, provider_name, dimension, model, embedding_version):
        if not (provider_name and model and embedding_version and dimension):
            raise ValueError("A complete embedding identity is required.")
        self.provider_name = provider_name
        self.dimension = dimension
        self.model = model
        self.embedding_version = embedding_version

    @classmethod
    def for_provider(cls, provider):
        return cls(
            provider_name=provider.name,
            dimension=provider.dimension,
            model=provider.model,
            embedding_version=provider.embedding_version,
        )

    def _current(self):
        return KnowledgeEmbedding.objects.filter(
            provider=self.provider_name,
            model=self.model,
            dimension=self.dimension,
            embedding_version=self.embedding_version,
        )

    def upsert(self, records):
        for record in records:
            if len(record.vector) != self.dimension:
                raise ValueError("Vector dimension mismatch.")

            # One row per (chunk, provider): a stale vector from an older
            # model of the same provider is replaced in place.
            KnowledgeEmbedding.objects.update_or_create(
                chunk_id=record.chunk_id,
                provider=self.provider_name,
                defaults={
                    "model": self.model,
                    "dimension": self.dimension,
                    "embedding_version": self.embedding_version,
                    "vector": list(record.vector),
                },
            )

    def delete(self, chunk_ids):
        KnowledgeEmbedding.objects.filter(
            chunk_id__in=[str(c) for c in chunk_ids],
            provider=self.provider_name,
        ).delete()

    def chunk_ids(self, circle_id):
        return {
            str(c) for c in
            self._current().filter(
                chunk__document__circle_id=circle_id,
            ).values_list("chunk_id", flat=True)
        }

    def similarity_search(self, query_vector, *, scope, top_k):
        rows = self._current().filter(
            chunk__document__circle_id__in=scope.circle_ids,
        )

        if scope.document_types is not None:
            rows = rows.filter(
                chunk__document__document_type__in=scope.document_types,
            )

        if scope.entity_type is not None:
            rows = rows.filter(
                chunk__document__entity_type=scope.entity_type,
                chunk__document__entity_id=str(scope.entity_id),
            )

        rows = list(rows.order_by("chunk_id").values_list("chunk_id", "vector"))
        if not rows:
            return []

        return _rank(
            [str(chunk_id) for chunk_id, _ in rows],
            np.asarray([vector for _, vector in rows], dtype=float),
            query_vector,
            top_k,
        )
