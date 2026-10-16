"""
READ-ONLY report of ledger rows that need human review. Writes nothing.

Checks:
- payout_negative_amount: PAYOUT rows with amount < 0 (pre-Sprint 28 sign
  bug: each inflated the balance by twice its magnitude)
- non_positive_amount: any other row with amount <= 0
- payout_without_paid_payout: PAYOUT rows whose metadata.payout_id does not
  name a PAID or RETURNED payout of the same circle
- paid_payout_without_ledger: PAID/RETURNED payouts with no PAYOUT row
- paid_payout_multiple_ledger: PAID/RETURNED payouts named by more than one
  PAYOUT row

Payout attempts: see report_payout_reconciliation.
"""

import json
from collections import Counter

from django.core.management.base import BaseCommand

from finance.models import (
    LedgerTransaction,
    Payout,
    PayoutStatus,
    TransactionType,
)


class Command(BaseCommand):
    help = "Read-only report of suspicious ledger and payout rows."

    def add_arguments(self, parser):
        parser.add_argument("--circle", help="Limit to one circle id")
        parser.add_argument("--json", action="store_true", help="Machine-readable output")

    def handle(self, *args, **options):
        ledger = LedgerTransaction.objects.all()
        payouts = Payout.objects.all()
        if options["circle"]:
            ledger = ledger.filter(circle_id=options["circle"])
            payouts = payouts.filter(circle_id=options["circle"])

        findings = []

        def add(kind, **fields):
            findings.append({"kind": kind, **{k: str(v) for k, v in fields.items()}})

        payout_rows = list(ledger.filter(transaction_type=TransactionType.PAYOUT))
        for row in payout_rows:
            if row.amount < 0:
                add("payout_negative_amount", ledger_id=row.id, circle_id=row.circle_id,
                    amount=row.amount, created_at=row.created_at)

        for row in ledger.exclude(transaction_type=TransactionType.PAYOUT).filter(amount__lte=0):
            add("non_positive_amount", ledger_id=row.id, circle_id=row.circle_id,
                type=row.transaction_type, amount=row.amount)

        # A RETURNED payout was paid: its PAYOUT row stays (compensated by
        # a PAYOUT_RETURN row, never edited).
        paid = {
            str(p.id): p
            for p in payouts.filter(status__in=[PayoutStatus.PAID, PayoutStatus.RETURNED])
        }
        named = Counter()
        for row in payout_rows:
            payout_id = (row.metadata or {}).get("payout_id")
            named[payout_id] += 1
            target = paid.get(payout_id)
            if target is None or target.circle_id != row.circle_id:
                add("payout_without_paid_payout", ledger_id=row.id,
                    circle_id=row.circle_id, payout_id=payout_id)

        for payout_id, payout in paid.items():
            if named[payout_id] == 0:
                add("paid_payout_without_ledger", payout_id=payout_id,
                    circle_id=payout.circle_id, amount=payout.amount)
            elif named[payout_id] > 1:
                add("paid_payout_multiple_ledger", payout_id=payout_id,
                    circle_id=payout.circle_id, rows=named[payout_id])

        if options["json"]:
            self.stdout.write(json.dumps(findings, indent=2))
            return

        if not findings:
            self.stdout.write("No anomalies found.")
            return

        for finding in findings:
            self.stdout.write(json.dumps(finding))
        self.stdout.write(f"{len(findings)} finding(s). Nothing was changed.")
