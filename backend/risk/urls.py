from django.urls import path

from .views import MemberDefaultRiskView


urlpatterns = [
    path(
        "circles/<uuid:circle_id>/members/<uuid:member_id>/default-risk/",
        MemberDefaultRiskView.as_view(),
        name="member-default-risk",
    ),
]
