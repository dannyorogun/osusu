from django.contrib import admin

from knowledge.models import KnowledgeChunk, KnowledgeDocument


class ReadOnlyAdmin(admin.ModelAdmin):
    """Knowledge is derived data: inspect it, never edit it by hand."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(KnowledgeDocument)
class KnowledgeDocumentAdmin(ReadOnlyAdmin):
    list_display = (
        "title",
        "document_type",
        "version",
        "schema_version",
        "generated_at",
    )
    list_filter = ("document_type", "schema_version")
    search_fields = ("title", "entity_id")


@admin.register(KnowledgeChunk)
class KnowledgeChunkAdmin(ReadOnlyAdmin):
    list_display = ("document", "chunk_index", "chunk_count")
