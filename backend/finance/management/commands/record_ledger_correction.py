"""
Record ONE reviewed ledger correction (see backend/OPERATIONS.md).

Dry run by default: prints what would be written and writes nothing.
Pass --confirm to write. The actor must hold the
finance.record_ledger_correction permission.
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from circles.models import Circle
from finance.models import LedgerTransaction
from services.finance.ledger_correction_service import (
    DIRECTIONS,
    CorrectionInvalid,
    CorrectionNotAuthorized,
    LedgerCorrectionService,
    _amount,
)
from services.finance.treasury_engine import TreasuryEngine


class Command(BaseCommand):
    help = "Record one explicit, reviewed ledger correction (dry run unless --confirm)."

    def add_arguments(self, parser):
        parser.add_argument("--circle", required=True, help="Circle id")
        parser.add_argument("--direction", required=True, choices=sorted(DIRECTIONS))
        parser.add_argument("--amount", required=True, help="Positive amount, e.g. 400.00")
        parser.add_argument("--reason", required=True)
        parser.add_argument("--reference", required=True, help="Unique, e.g. reconcile-<row id>")
        parser.add_argument("--actor", required=True, help="Username of the reviewing operator")
        parser.add_argument("--corrects-transaction", help="Ledger transaction id being corrected")
        parser.add_argument("--incident", default="", help="Incident/ticket reference")
        parser.add_argument("--confirm", action="store_true", help="Actually write the entry")

    def handle(self, *args, **options):
        User = get_user_model()

        try:
            circle = Circle.objects.get(pk=options["circle"])
        except (Circle.DoesNotExist, ValidationError, ValueError) as error:
            raise CommandError(f"Unknown circle: {options['circle']}") from error

        actor = User.objects.filter(username=options["actor"]).first()
        if actor is None:
            raise CommandError(f"Unknown actor: {options['actor']}")

        corrected = None
        if options["corrects_transaction"]:
            corrected = LedgerTransaction.objects.filter(
                pk=options["corrects_transaction"]
            ).first()
            if corrected is None:
                raise CommandError("Unknown ledger transaction.")

        try:
            amount = _amount(options["amount"])
        except CorrectionInvalid as error:
            raise CommandError(str(error)) from error

        before = TreasuryEngine.current_balance(circle)
        delta = amount if options["direction"] == "in" else -amount

        self.stdout.write(
            f"Circle {circle.id} ({circle.name})\n"
            f"  direction: {options['direction']}  amount: {amount}\n"
            f"  balance: {before} -> {before + delta}\n"
            f"  corrects: {corrected.id if corrected else '-'}  incident: {options['incident'] or '-'}\n"
            f"  reference: {options['reference']}  actor: {actor.username}\n"
            f"  reason: {options['reason']}"
        )

        if not options["confirm"]:
            self.stdout.write("DRY RUN: nothing written. Re-run with --confirm.")
            return

        try:
            entry, created = LedgerCorrectionService.record(
                circle=circle,
                direction=options["direction"],
                amount=amount,
                reason=options["reason"],
                reference=options["reference"],
                actor=actor,
                corrects_transaction=corrected,
                incident=options["incident"],
            )
        except (CorrectionInvalid, CorrectionNotAuthorized) as error:
            raise CommandError(str(error)) from error

        if created:
            self.stdout.write(f"Recorded correction {entry.id}.")
        else:
            self.stdout.write(f"Already recorded as {entry.id}; nothing written.")
        self.stdout.write(f"Balance now {TreasuryEngine.current_balance(circle)}.")
