from django.contrib import admin
from django.urls import include, path

from rest_framework_simplejwt.views import (
    TokenBlacklistView,
    TokenRefreshView,
)

from users.views import LoginView


urlpatterns = [
    path("admin/", admin.site.urls),

    path(
        "api/users/",
        include("users.urls"),
    ),

    path(
        "api/circles/",
        include("circles.urls"),
    ),

    path(
        "api/payments/",
        include("payments.urls"),
    ),

    path(
        "api/risk/",
        include("risk.urls"),
    ),

    path(
        "api/",
        include("knowledge.urls"),
    ),

    path(
        "api/auth/login/",
        LoginView.as_view(),
        name="token_obtain_pair",
    ),

    path(
        "api/auth/refresh/",
        TokenRefreshView.as_view(),
        name="token_refresh",
    ),

    # Revokes a refresh token (token_blacklist); TokenRefreshView then
    # rejects it. No access token needed: it may already have expired.
    path(
        "api/auth/logout/",
        TokenBlacklistView.as_view(),
        name="token_blacklist",
    ),
]