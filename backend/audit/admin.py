from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "action",
        "entity_type",
        "entity_id",
        "user",
        "created_at",
    )

    list_filter = (
        "action",
        "entity_type",
    )

    search_fields = (
        "entity_id",
        "user__email",
    )

    readonly_fields = (
        "id",
        "user",
        "action",
        "entity_type",
        "entity_id",
        "metadata",
        "created_at",
    )