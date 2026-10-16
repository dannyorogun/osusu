from django.db import transaction

from circles.models import Circle, CircleStatus
from services.circles.cash_flow_engine import CashFlowEngine

from services.circles.formation_engine import (
    CircleFormationEngine
)

from services.circles.mathematical_integrity import (
    MathematicalIntegrityEngine
)

from services.audit.audit_service import AuditService


EVALUABLE_STATUSES = (
    CircleStatus.DRAFT,
    CircleStatus.RECRUITING,
    CircleStatus.READY,
)


class CircleFormationService:

    @staticmethod
    @transaction.atomic
    def evaluate(circle):

        circle = Circle.objects.select_for_update().get(pk=circle.pk)

        # A passing evaluation sets READY; it must never move a locked,
        # active or completed circle back to READY.
        if circle.status not in EVALUABLE_STATUSES:
            raise ValueError(
                "Formation can only be evaluated before the financial lock."
            )

        formation = CircleFormationEngine.validate(circle)

        if not formation.passed:
            return {
                "ready": False,
                "formation_checks": formation.checks,
                "financial_checks": None,
            }
        financial = MathematicalIntegrityEngine.validate(circle)

        if not financial["passed"]:
            return {
            "ready": False,
            "formation_checks": formation.checks,
            "financial_checks": financial,
            "cash_flow": None,
        }

        cash_flow = CashFlowEngine.simulate(circle)

        if not cash_flow["passed"]:
            return {
                "ready": False,
                "formation_checks": formation.checks,
                "financial_checks": financial,
                "cash_flow": cash_flow,
    }
       
        if circle.status == CircleStatus.READY:
            # Re-evaluating a READY circle reports, but does not re-record.
            return {
                "ready": True,
                "formation_checks": formation.checks,
                "financial_checks": financial,
                "cash_flow": cash_flow,
            }

        circle.status = CircleStatus.READY

        circle.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )

        AuditService.record(
            action="CIRCLE_READY",
            entity_type="Circle",
            entity_id=circle.id,
            user=circle.creator,
            metadata={
                "formation_checks": formation.checks,
                "financial_checks": {
                    "passed": financial["passed"],
                    "member_count": financial["member_count"],
                    "total_contributions": str(
                        financial["total_contributions"]
                    ),
                    "total_payouts": str(
                        financial["total_payouts"]
                    ),
                    "reserve": str(
                        financial["reserve"]
                    ),
                    "required_funds": str(
                        financial["required_funds"]
                    ),
                    "surplus": str(
                        financial["surplus"]
                    ),
                },
            },
        )

        return {
                   "ready": True,
                   "formation_checks": formation.checks,
                   "financial_checks": financial,
                   "cash_flow": cash_flow,
               }
    