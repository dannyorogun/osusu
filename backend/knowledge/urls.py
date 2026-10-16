from django.urls import path

from .views import CircleAssistantView


urlpatterns = [
    path(
        "circles/<uuid:circle_id>/assistant/",
        CircleAssistantView.as_view(),
        name="circle-assistant",
    ),
]
