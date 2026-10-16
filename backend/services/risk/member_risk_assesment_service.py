from django.db import transaction

from risk.models import (
    MemberRiskAssessment,
    MemberRiskSignal,
)

from services.risk.member_risk_engine import (
    MemberRiskEngine,
)


class MemberRiskAssessmentService:

    @staticmethod
    @transaction.atomic
    def assess_member(
        *,
        circle,
        member,
    ):

        result = MemberRiskEngine.analyze_member(
            circle=circle,
            member=member,
        )

        assessment = (
            MemberRiskAssessment.objects.create(
                circle=circle,
                member=member,
                risk_level=result["risk_level"],
                payment_rate=result["payment_rate"],
                overdue_rate=result["overdue_rate"],
                completed_cycles=(
                    result["completed_cycles"]
                ),
                payments_made=(
                    result["payments_made"]
                ),
                late_payments=(
                    result["late_payments"]
                ),
                defaults=result["defaults"],
                votes_participated=(
                    result["votes_participated"]
                ),
                model_version="rules-v1",
            )
        )

        for signal in result["signals"]:

            MemberRiskSignal.objects.create(
                assessment=assessment,
                signal_type=signal["type"],
                severity=signal["severity"],
                message=signal["message"],
                value=signal.get(
                    "value",
                    "",
                ),
            )

        return assessment