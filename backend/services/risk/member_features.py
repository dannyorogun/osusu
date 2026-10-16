"""
Single source of truth for the member default-risk feature definition.

Training (via RiskDatasetBuilder over stored snapshots) and prediction
(via MemberFeatureService over current state) both build vectors with
to_feature_vector(), so column order can never drift between them.
"""

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal

from finance.models import (
    ContributionObligation,
    ObligationStatus,
)

from risk.models import MemberRiskFeatureSnapshot

from services.trust.feature_engine import TrustFeatureEngine
from services.trust.trust_graph_service import TrustGraphService

from trust.models import TrustProfile


FEATURE_VERSION = "features-v1"

MEMBER_DEFAULT_FEATURE_NAMES = (
    "payment_rate",
    "overdue_rate",
    "completed_cycles",
    "payments_made",
    "late_payments",
    "defaults",
    "votes_participated",
    "trust_connections",
    "successful_trust_connections",
)


def to_feature_vector(source):
    """
    Convert a snapshot (attribute access) or a mapping of feature values
    into a float vector in MEMBER_DEFAULT_FEATURE_NAMES order.

    Floats are used only here, at the ML boundary; upstream financial
    values stay Decimal.
    """
    if isinstance(source, Mapping):
        missing = [
            name
            for name in MEMBER_DEFAULT_FEATURE_NAMES
            if name not in source
        ]
        values = [source.get(name) for name in MEMBER_DEFAULT_FEATURE_NAMES]
    else:
        missing = [
            name
            for name in MEMBER_DEFAULT_FEATURE_NAMES
            if not hasattr(source, name)
        ]
        values = [
            getattr(source, name, None)
            for name in MEMBER_DEFAULT_FEATURE_NAMES
        ]

    if missing:
        raise ValueError(f"Missing feature values: {missing}")

    if any(value is None for value in values):
        raise ValueError("Feature values must not be None.")

    return [float(value) for value in values]


def _quantize_like_snapshot(field_name, value):
    """
    Round a rate the same way the snapshot DecimalField stores it, so
    prediction sees the same precision the model was trained on.
    """
    places = MemberRiskFeatureSnapshot._meta.get_field(
        field_name
    ).decimal_places

    return value.quantize(
        Decimal(1).scaleb(-places),
        rounding=ROUND_HALF_UP,
    )


class MemberFeatureService:

    @staticmethod
    def compute_current(*, circle, member):
        """
        Current feature state for a member in a circle.

        Strictly read-only: produces the same values a
        MemberRiskFeatureSnapshot would store for the same state, without
        writing a snapshot, TrustProfile, or anything else.
        """

        obligations = ContributionObligation.objects.filter(
            circle=circle,
            member=member,
        )

        total_obligations = obligations.count()

        if total_obligations > 0:
            paid = obligations.filter(
                status=ObligationStatus.PAID,
            ).count()

            overdue = obligations.filter(
                status=ObligationStatus.OVERDUE,
            ).count()

            payment_rate = Decimal(paid) / Decimal(total_obligations)
            overdue_rate = Decimal(overdue) / Decimal(total_obligations)
        else:
            payment_rate = Decimal("1")
            overdue_rate = Decimal("0")

        trust_counts = TrustFeatureEngine.compute(member)

        votes_participated = (
            TrustProfile.objects
            .filter(user=member)
            .values_list("votes_participated", flat=True)
            .first()
        ) or 0

        trust_edges = TrustGraphService.get_graph_for_circle(circle)

        member_connections = (
            trust_edges.filter(inviter=member)
            | trust_edges.filter(invited=member)
        )

        trust_connections = member_connections.count()

        successful_trust_connections = member_connections.filter(
            successful_cycles_together__gt=0,
        ).count()

        return {
            "payment_rate": _quantize_like_snapshot(
                "payment_rate",
                payment_rate,
            ),
            "overdue_rate": _quantize_like_snapshot(
                "overdue_rate",
                overdue_rate,
            ),
            "completed_cycles": trust_counts["completed_cycles"],
            "payments_made": trust_counts["payments_made"],
            "late_payments": trust_counts["late_payments"],
            "defaults": trust_counts["defaults"],
            "votes_participated": votes_participated,
            "trust_connections": trust_connections,
            "successful_trust_connections": successful_trust_connections,
        }
