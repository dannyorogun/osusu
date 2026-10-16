from django.db import transaction
from django.utils import timezone

from circles.models import Circle, CircleStatus
from services.audit.audit_service import AuditService
from services.circles.formation_engine import CircleFormationEngine
from services.circles.mathematical_integrity import MathematicalIntegrityEngine
from services.circles.cash_flow_engine import CashFlowEngine

class FinancialLockEngine:

    @staticmethod
    def validate(circle):
        checks = {}
        cash_flow = CashFlowEngine.simulate(circle)
        checks["cash_flow_valid"] = cash_flow["passed"]

        # Circle must be READY
        checks["circle_ready"] = (
            circle.status == CircleStatus.READY
        )

        # Run formation checks again
        formation = CircleFormationEngine.validate(circle)

        checks["formation_valid"] = formation.passed

        # Run financial integrity checks again
        if formation.passed:
            financial = MathematicalIntegrityEngine.validate(circle)
            checks["financial_integrity"] = financial["passed"]
        else:
            financial = None
            checks["financial_integrity"] = False

        passed = all(checks.values())

        return {
            "passed": passed,
            "checks": checks,
            "formation": formation.checks,
            "financial": financial,
            "cash_flow": cash_flow,
}

    @staticmethod
    @transaction.atomic
    def lock(circle, *, user=None):
        # Row lock: two concurrent lock requests cannot both pass.
        circle = Circle.objects.select_for_update().get(pk=circle.pk)

        validation = FinancialLockEngine.validate(circle)

        if not validation["passed"]:
            raise ValueError(
                "Circle cannot be financially locked."
            )

        circle.status = CircleStatus.LOCKED
        circle.financial_locked_at = timezone.now()

        circle.save(
            update_fields=[
                "status",
                "financial_locked_at",
                "updated_at",
            ]
        )

        AuditService.record(
            action="CIRCLE_LOCKED",
            entity_type="Circle",
            entity_id=circle.id,
            user=user or circle.creator,
            metadata={"checks": validation["checks"]},
        )

        return circle