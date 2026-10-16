from django.core.management.base import BaseCommand, CommandError

from circles.models import Circle

from services.knowledge.index_service import KnowledgeIndexService


class Command(BaseCommand):
    help = (
        "Generate knowledge documents, chunks and embeddings from existing "
        "circle data (read-only on domain tables; idempotent)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--circle",
            help="Only index this circle id.",
        )

    def handle(self, *args, **options):
        circles = Circle.objects.order_by("created_at", "id")

        if options["circle"]:
            circles = circles.filter(id=options["circle"])
            if not circles.exists():
                raise CommandError("Circle not found.")

        count = 0
        for circle in circles:
            result = KnowledgeIndexService.index_circle(circle)
            sync = result.sync
            count += 1
            self.stdout.write(
                f"{circle.id}: created={len(sync.created)} "
                f"updated={len(sync.updated)} "
                f"unchanged={len(sync.unchanged)} "
                f"deleted={len(sync.deleted)} "
                f"embedded={result.embedded} removed={result.removed}"
            )

        self.stdout.write(self.style.SUCCESS(f"Indexed {count} circle(s)."))
