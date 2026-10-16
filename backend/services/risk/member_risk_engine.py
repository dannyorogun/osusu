from decimal import Decimal

from finance.models import (
    ContributionObligation,
    ObligationStatus,
)

from services.trust.feature_engine import (
    TrustFeatureEngine,
)


class MemberRiskEngine:

    @staticmethod
    def analyze_member(
        *,
        circle,
        member,
    ):

        obligations = (
            ContributionObligation.objects.filter(
                circle=circle,
                member=member,
            )
        )

        total_obligations = obligations.count()

        paid_obligations = obligations.filter(
            status=ObligationStatus.PAID,
        ).count()

        overdue_obligations = obligations.filter(
            status=ObligationStatus.OVERDUE,
        ).count()

        if total_obligations > 0:

            payment_rate = (
                Decimal(paid_obligations)
                / Decimal(total_obligations)
            )

            overdue_rate = (
                Decimal(overdue_obligations)
                / Decimal(total_obligations)
            )

        else:

            payment_rate = Decimal("1")
            overdue_rate = Decimal("0")

        trust_profile = (
            TrustFeatureEngine.calculate(member)
        )

        signals = []

        # --------------------------------------------------
        # PAYMENT SIGNAL
        # --------------------------------------------------

        if overdue_rate >= Decimal("0.20"):

            signals.append({
                "type": "MEMBER_PAYMENT_RISK",
                "severity": "high",
                "message": (
                    "At least 20% of this member's "
                    "obligations are overdue."
                ),
                "value": str(
                    round(
                        overdue_rate * 100,
                        2,
                    )
                ),
            })

        elif overdue_rate > Decimal("0"):

            signals.append({
                "type": "MEMBER_PAYMENT_RISK",
                "severity": "medium",
                "message": (
                    "This member has overdue "
                    "contribution obligations."
                ),
                "value": str(
                    round(
                        overdue_rate * 100,
                        2,
                    )
                ),
            })

        # --------------------------------------------------
        # DEFAULT SIGNAL
        # --------------------------------------------------

        if trust_profile.defaults > 0:

            signals.append({
                "type": "DEFAULT_HISTORY",
                "severity": "high",
                "message": (
                    "This member has recorded "
                    "overdue/default history."
                ),
                "value": str(
                    trust_profile.defaults
                ),
            })

        # --------------------------------------------------
        # EXPERIENCE SIGNAL
        # --------------------------------------------------

        if trust_profile.completed_cycles == 0:

            signals.append({
                "type": "LIMITED_HISTORY",
                "severity": "medium",
                "message": (
                    "This member has not yet "
                    "completed a circle cycle."
                ),
                "value": "0",
            })

        # --------------------------------------------------
        # OVERALL RISK
        # --------------------------------------------------

        high_count = sum(
            1
            for signal in signals
            if signal["severity"] == "high"
        )

        medium_count = sum(
            1
            for signal in signals
            if signal["severity"] == "medium"
        )

        if high_count > 0:

            risk_level = "high"

        elif medium_count > 0:

            risk_level = "medium"

        else:

            risk_level = "low"

        return {
            "member_id": str(member.id),
            "circle_id": str(circle.id),
            "risk_level": risk_level,
            "payment_rate": payment_rate,
            "overdue_rate": overdue_rate,
            "total_obligations": total_obligations,
            "paid_obligations": paid_obligations,
            "overdue_obligations": overdue_obligations,
            "completed_cycles": (
                trust_profile.completed_cycles
            ),
            "payments_made": (
                trust_profile.payments_made
            ),
            "late_payments": (
                trust_profile.late_payments
            ),
            "defaults": (
                trust_profile.defaults
            ),
            "votes_participated": (
                trust_profile.votes_participated
            ),
            "signals": signals,
        }