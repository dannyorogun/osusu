from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Profile



@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User

    list_display = (
        "email",
        "username",
        "first_name",
        "last_name",
        "is_staff",
        "is_active",
    )

    ordering = ("email",)

    fieldsets = UserAdmin.fieldsets + (
        ("Osusu Information", {
            "fields": (
                "created_at",
                "updated_at",
            ),
        }),
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "display_name",
        "country",
        "created_at",
    )

    search_fields = (
        "user__email",
        "display_name",
    )