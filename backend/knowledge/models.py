"""
Read-only knowledge layer for retrieval (RAG).

These tables hold DERIVED, human-readable representations of Osusu data.
They are never a source of truth: financial and governance state lives in
the domain apps and is only ever read by the knowledge builder. Nothing in
the knowledge layer writes to domain tables.
"""

import uuid

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models


class KnowledgeDocumentType(models.TextChoices):
    CIRCLE_SUMMARY = "circle_summary", "Circle summary"
    CIRCLE_FINANCIAL_SUMMARY = (
        "circle_financial_summary",
        "Circle financial summary",
    )
    MEMBER_CONTRIBUTION_SUMMARY = (
        "member_contribution_summary",
        "Member contribution summary",
    )
    PAYOUT_SUMMARY = "payout_summary", "Payout summary"
    RISK_SUMMARY = "risk_summary", "Risk summary"
    AUDIT_SUMMARY = "audit_summary", "Audit summary"


class KnowledgeDocument(models.Model):
    """
    The current knowledge document for one source entity.

    `circle` is a real column (not just metadata) so retrieval can scope
    by circle in SQL, which is the authorization boundary. `subject_user`
    is set for documents about one member.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    circle = models.ForeignKey(
        "circles.Circle",
        on_delete=models.CASCADE,
        related_name="knowledge_documents",
    )

    subject_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="knowledge_documents",
    )

    document_type = models.CharField(
        max_length=50,
        choices=KnowledgeDocumentType.choices,
    )

    # Traceability to the source record, e.g. ("circle", <circle id>) or
    # ("circle_membership", <membership id>).
    entity_type = models.CharField(max_length=50)
    entity_id = models.CharField(max_length=64)

    title = models.CharField(max_length=255)
    content = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)

    # Format of the generated text (bumped when templates change) versus
    # revision of this document (bumped when its content changes).
    schema_version = models.CharField(max_length=30)
    version = models.PositiveIntegerField(default=1)

    content_hash = models.CharField(max_length=64)

    generated_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["circle_id", "document_type", "entity_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["document_type", "entity_type", "entity_id"],
                name="unique_knowledge_document_per_entity",
            ),
        ]
        indexes = [
            models.Index(
                fields=["circle", "document_type"],
                name="knowledge_doc_circle_type_idx",
            ),
        ]

    def __str__(self):
        return f"{self.document_type} v{self.version} - {self.title}"


class KnowledgeChunk(models.Model):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    document = models.ForeignKey(
        KnowledgeDocument,
        on_delete=models.CASCADE,
        related_name="chunks",
    )

    chunk_index = models.PositiveIntegerField()
    chunk_count = models.PositiveIntegerField()

    content = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    content_hash = models.CharField(max_length=64)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["document_id", "chunk_index"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "chunk_index"],
                name="unique_knowledge_chunk_index",
            ),
        ]

    def __str__(self):
        return f"{self.document_id}#{self.chunk_index}"


class KnowledgeEmbedding(models.Model):
    """
    One vector per (chunk, embedding provider). Stored as a PostgreSQL
    float array; a pgvector column can replace it when the extension is
    available (see services.knowledge.vector_store).
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    chunk = models.ForeignKey(
        KnowledgeChunk,
        on_delete=models.CASCADE,
        related_name="embeddings",
    )

    # Identity of the model that produced the vector. Search only ever
    # compares vectors whose (provider, model, dimension,
    # embedding_version) match the active provider exactly; rows from a
    # previous model are stale and get replaced on re-index.
    provider = models.CharField(max_length=100)
    model = models.CharField(max_length=100, default="")
    dimension = models.PositiveIntegerField()
    embedding_version = models.CharField(max_length=30, default="")
    vector = ArrayField(models.FloatField())

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["chunk", "provider"],
                name="unique_knowledge_embedding_per_provider",
            ),
        ]

    def __str__(self):
        return f"{self.provider}:{self.chunk_id}"
