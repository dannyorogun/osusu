from django.contrib import admin

from .models import (
    Circle,
    CircleConstitution,
    CircleMembership,
    CircleInvitation
)


@admin.register(Circle)
class CircleAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "creator",
        "status",
        "created_at",
    )

    list_filter = ("status",)


@admin.register(CircleConstitution)
class CircleConstitutionAdmin(admin.ModelAdmin):
    list_display = (
        "circle",
        "member_limit",
        "contribution_amount",
    )


@admin.register(CircleMembership)
class CircleMembershipAdmin(admin.ModelAdmin):
    list_display = (
        "circle",
        "user",
        "status",
    )

@admin.register(CircleInvitation)
class CircleInvitationAdmin(admin.ModelAdmin):
    list_display = (
        "email",
        "circle",
        "inviter",
        "status",
        "expires_at",
    )

    list_filter = (
        "status",
    )