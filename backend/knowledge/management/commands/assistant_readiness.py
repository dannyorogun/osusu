from django.core.management.base import BaseCommand, CommandError

from services.llm.readiness import assess_readiness


class Command(BaseCommand):
    help = (
        "Report whether the paid explanation assistant may be served "
        "(every production gate). Prints gate names and requirements, "
        "never configuration values. Exits non-zero when NOT READY."
    )

    def handle(self, *args, **options):
        readiness = assess_readiness()

        for check in readiness.checks:
            mark = "PASS" if check.ok else "FAIL"
            self.stdout.write(f"[{mark}] {check.name}: {check.detail}")

        if not readiness.ready:
            raise CommandError(
                f"NOT READY: {len(readiness.failures)} of "
                f"{len(readiness.checks)} gates failed."
            )

        self.stdout.write(self.style.SUCCESS("READY"))
