from django.db import transaction

from risk.models import (
    RiskAssessment,
    RiskLevel,
    RiskSignal,
)

from services.risk.risk_engine import (
    RiskEngine,
)


class RiskAssessmentService:

    @staticmethod
    @transaction.atomic
    def assess_circle(circle):

        result = RiskEngine.analyze_circle(
            circle
        )

        assessment = RiskAssessment.objects.create(
            circle=circle,
            risk_level=result["overall_risk"],
            payment_rate=(
                result["payment_rate"] / 100
            ),
            overdue_rate=(
                result["overdue_obligations"]
                / max(
                    1,
                    result["total_obligations"],
                )
),
            funding_ratio=result[
                "funding_ratio"
            ],
            trust_connection_count=result[
                "trust_connections"
            ],
            successful_connection_ratio=(
                result[
                    "successful_connections"
                ]
                / max(
                    1,
                    result[
                        "trust_connections"
                    ],
                )
            ),
            model_version="rules-v1",
        )

        for signal in result["signals"]:

            RiskSignal.objects.create(
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