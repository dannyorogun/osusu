from django.apps import AppConfig


class KnowledgeConfig(AppConfig):
    name = "knowledge"

    def ready(self):
        from knowledge import checks  # noqa: F401  (registers system checks)
