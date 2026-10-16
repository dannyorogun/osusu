"""
READ-ONLY payout reconciliation report (PayoutReconciliationService).
Writes nothing, resolves nothing, marks nothing failed.

Provider-side matching (provider transfers vs local attempts) needs a
provider settlement report; none exists until a provider is selected, so
only local consistency checks run here.
"""

import json

from django.core.management.base import BaseCommand

from circles.models import Circle
from services.payouts.payout_reconciliation_service import (
    PayoutReconciliationService,
)


class Command(BaseCommand):
    help = "Read-only report of payout attempts needing review."

    def add_arguments(self, parser):
        parser.add_argument("--circle", help="Limit to one circle id")
        parser.add_argument("--json", action="store_true", help="Machine-readable output")

    def handle(self, *args, **options):
        circle = (
            Circle.objects.get(pk=options["circle"]) if options["circle"] else None
        )
        findings = PayoutReconciliationService.report(circle=circle)

        if options["json"]:
            self.stdout.write(json.dumps(findings, indent=2))
            return

        self.stdout.write(
            "Provider-side matching not run: no provider settlement report "
            "is configured."
        )
        if not findings:
            self.stdout.write("No payout findings.")
            return

        for finding in findings:
            self.stdout.write(json.dumps(finding))
        self.stdout.write(f"{len(findings)} finding(s). Nothing was changed.")
