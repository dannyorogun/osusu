"""
Read-only queries behind the member-facing circle endpoints.

Every method here only SELECTs. Authorization is NOT done here: callers
must first pass circles.access.authorize_member (ACTIVE membership) for
any circle-scoped method. Money stays Decimal; balances come only from
TreasuryEngine (completed ledger rows).
"""

from django.db.models import Count, Q

from audit.models import AuditLog
from circles.models import (
    Circle,
    CircleMembership,
    CircleRestructure,
    MembershipStatus,
)
from finance.models import (
    DECIDED_PAYOUT_STATUSES,
    ContributionObligation,
    PayoutVote,
    LedgerTransaction,
    ObligationStatus,
    Payout,
    PayoutStatus,
    TransactionStatus,
)
from services.circles.eligibility_engine import EligibilityEngine
from services.finance.treasury_engine import TreasuryEngine
from services.payouts.payout_approval_service import (
    DECIDED_STATUSES,
    required_votes,
)
from services.trust.feature_engine import TrustFeatureEngine
from services.trust.trust_graph_service import TrustGraphService


# Memberships shown on a circle's member list. LEFT / REMOVED are former
# members and are not listed.
LISTED_MEMBER_STATUSES = (
    MembershipStatus.ACTIVE,
    MembershipStatus.INVITED,
)

# Payout rows created by PayoutEngine start PENDING for EVERY eligible
# candidate of a window; only the approved winner becomes a payout and
# the others are CANCELLED when the window is decided. PENDING and
# CANCELLED rows are therefore candidates, not payouts, and are never
# listed as payouts.

ACTIVITY_LIMIT = 50

# Why no trust or health score is returned (see CircleReadService.trust).
SCORE_UNAVAILABLE_REASONS = [
    "No validated trust score exists: the reliability and circle-health "
    "formulas use fixed weights that have not been validated against "
    "real outcomes.",
    "Circle health treats missing data as perfect (a circle with no "
    "contributions yet counts as a 100% payment rate), so it would "
    "overstate health.",
    "Successful cycles completed together are not recorded yet, so the "
    "quality of connections between members is unknown.",
]

# AuditLog action -> public event code. Anything not listed here is never
# returned by the activity feed.
ACTIVITY_EVENTS = {
    "CIRCLE_CREATED": "circle_created",
    "CIRCLE_READY": "circle_ready",
    "CIRCLE_LOCKED": "circle_locked",
    "INVITATION_CREATED": "invitation_sent",
    "INVITATION_ACCEPTED": "member_joined",
    "CONSTITUTION_ACCEPTED": "constitution_accepted",
    "PAYOUT_WINDOW_CREATED": "payout_window_opened",
    "PAYOUT_APPROVED": "payout_approved",
    "PAYOUT_COMPLETED": "payout_completed",
    "RESTRUCTURE_PROPOSED": "restructure_proposed",
}


def display_name(user):
    """Name shown to other circle members: full name, else username."""
    if user is None:
        return None
    full = f"{user.first_name} {user.last_name}".strip()
    return full or user.username


class CircleReadService:

    @staticmethod
    def circles_for_user(user):
        """
        Circles in which `user` is an ACTIVE member, newest first, with
        `active_member_count`. Invitations do not create memberships
        (InvitationService creates an ACTIVE one on acceptance), so pending
        invitations are not circles of the user yet.
        """
        return (
            Circle.objects
            # A subquery, not a join: filtering through the memberships
            # join would also restrict the count below to this user's row.
            .filter(
                id__in=CircleMembership.objects
                .filter(user_id=user.pk, status=MembershipStatus.ACTIVE)
                .values("circle_id")
            )
            .select_related("constitution")
            .annotate(
                active_member_count=Count(
                    "memberships",
                    filter=Q(memberships__status=MembershipStatus.ACTIVE),
                    distinct=True,
                )
            )
            .order_by("-created_at")
        )

    @staticmethod
    def members(circle):
        return (
            CircleMembership.objects
            .filter(circle=circle, status__in=LISTED_MEMBER_STATUSES)
            .select_related("user", "circle")
            .order_by("joined_at", "user__username")
        )

    @staticmethod
    def obligations_for_member(circle, user):
        """Only the requester's own obligations."""
        return (
            ContributionObligation.objects
            .filter(circle=circle, member_id=user.pk)
            .order_by("period_number")
        )

    @staticmethod
    def obligations_for_user(user):
        """
        The user's own obligations across every circle in which they are
        an ACTIVE member (the same boundary as the circle-scoped read),
        soonest due first.
        """
        active_circles = CircleMembership.objects.filter(
            user_id=user.pk,
            status=MembershipStatus.ACTIVE,
        ).values("circle_id")

        return (
            ContributionObligation.objects
            .filter(member_id=user.pk, circle_id__in=active_circles)
            .select_related("circle")
            .order_by("due_date", "period_number")
        )

    @staticmethod
    def trust(circle, user):
        """
        Factual trust information only: the requester's own contribution
        record (this circle, and across their circles via
        TrustFeatureEngine), and how many invitation connections exist
        among the circle's members. No score: see
        SCORE_UNAVAILABLE_REASONS. Other members' records and who invited
        whom are never returned.
        """
        in_circle = {
            row["status"]: row["count"]
            for row in (
                ContributionObligation.objects
                .filter(circle=circle, member_id=user.pk)
                .values("status")
                .annotate(count=Count("id"))
            )
        }
        record = {
            status: in_circle.get(status, 0)
            for status in ObligationStatus.values
        }
        record["total"] = sum(in_circle.values())

        counts = TrustFeatureEngine.compute(user)
        history = {
            "completed_circles": counts["completed_cycles"],
            "paid_contributions": counts["payments_made"],
            "overdue_contributions": counts["late_payments"],
        }

        # An outcome (paid or overdue) is needed before a record says
        # anything; pending obligations alone are not evidence.
        has_outcomes = (
            history["paid_contributions"] + history["overdue_contributions"]
        ) > 0

        return {
            "data_status": "available" if has_outcomes else "insufficient_data",
            "your_record_in_circle": record,
            "your_history": history,
            "circle": {
                "active_members": CircleMembership.objects.filter(
                    circle=circle,
                    status=MembershipStatus.ACTIVE,
                ).count(),
                # Invitation relationships among people who are or were
                # members of this circle (TrustGraphService).
                "invitation_connections": (
                    TrustGraphService.get_graph_for_circle(circle).count()
                ),
            },
            "score": None,
            "score_unavailable_reasons": SCORE_UNAVAILABLE_REASONS,
        }

    @staticmethod
    def payouts(circle):
        """
        Decided payouts (approved or paid), newest window first, plus the
        windows that have candidates but no approved recipient yet.
        Votes and candidate identities are never returned.
        """
        decided = list(
            Payout.objects
            .filter(circle=circle, status__in=DECIDED_PAYOUT_STATUSES)
            .select_related("member")
            .prefetch_related("attempts")
            .order_by("-payout_window", "-created_at")
        )

        decided_windows = {payout.payout_window for payout in decided}

        open_windows = [
            row
            for row in (
                Payout.objects
                .filter(circle=circle, status=PayoutStatus.PENDING)
                .values("payout_window")
                .annotate(candidate_count=Count("id"))
                .order_by("-payout_window")
            )
            if row["payout_window"] not in decided_windows
        ]

        return {
            "payouts": decided,
            "open_windows": open_windows,
        }

    @staticmethod
    def latest_payout_window(circle):
        return (
            Payout.objects
            .filter(circle=circle)
            .order_by("-payout_window")
            .values_list("payout_window", flat=True)
            .first()
        )

    @staticmethod
    def payout_window(circle, window, user, *, is_creator):
        """
        One window as the requester may see it, or None if it has no rows.

        Candidates are listed (display name only) because members vote for
        them. Votes are never attributed: only the total cast, the quorum
        needed, and the requester's OWN choice are returned. `can_*` are
        hints for the UI; every action is re-checked by its service.
        """
        rows = list(
            Payout.objects
            .filter(circle=circle, payout_window=window)
            .select_related("member")
            .prefetch_related("attempts")
            .order_by("created_at", "id")
        )
        if not rows:
            return None

        decided = next((r for r in rows if r.status in DECIDED_STATUSES), None)
        pending = [r for r in rows if r.status == PayoutStatus.PENDING]
        is_open = decided is None and bool(pending)

        own_vote = (
            PayoutVote.objects
            .filter(payout__in=rows, member_id=user.pk)
            .values_list("payout_id", flat=True)
            .first()
        )
        votes_cast = PayoutVote.objects.filter(
            payout_id__in=[r.pk for r in pending]
        ).count() if is_open else None

        eligible_ids = {u.pk for u in EligibilityEngine.eligible_members(circle)}

        if decided is not None:
            # approved | processing | paid | failed | returned
            state = decided.status
        elif is_open:
            state = "open"
        else:
            state = "closed"

        return {
            "payout_window": window,
            "state": state,
            "candidates": [
                {
                    "id": r.id,
                    "display_name": display_name(r.member),
                    "is_you": r.member_id == user.pk,
                    "status": r.status,
                }
                for r in rows
                if r.status in (PayoutStatus.PENDING, PayoutStatus.CANCELLED)
                or r is decided
            ],
            "votes_cast": votes_cast,
            "votes_required": required_votes(circle) if is_open else None,
            "your_vote": own_vote,
            "payout": decided,
            "can_vote": is_open and own_vote is None and user.pk in eligible_ids,
            "can_approve": is_open and is_creator,
            "can_execute": (
                is_creator
                and decided is not None
                # Never while PROCESSING: an attempt may be moving money.
                and decided.status in (PayoutStatus.APPROVED, PayoutStatus.FAILED)
            ),
        }

    @staticmethod
    def treasury(circle):
        """
        Balance and totals from COMPLETED ledger rows only (TreasuryEngine),
        and the amount reserved for payouts in progress.
        Pending and failed rows are counted separately and never added to
        any balance or total.
        """
        summary = TreasuryEngine.summary(circle)

        uncounted = (
            LedgerTransaction.objects
            .filter(
                circle=circle,
                status__in=[
                    TransactionStatus.PENDING,
                    TransactionStatus.FAILED,
                ],
            )
            .values("status")
            .annotate(count=Count("id"))
        )
        counts = {row["status"]: row["count"] for row in uncounted}

        reserved = TreasuryEngine.reserved_for_payouts(circle)

        return {
            "balance": summary["balance"],
            # Payouts whose money may be moving have no ledger row yet:
            # their amount is reserved, not available.
            "reserved_for_payouts": reserved,
            "available_balance": summary["balance"] - reserved,
            "completed_transaction_count": summary["transactions"],
            "totals": TreasuryEngine.ledger_totals(circle),
            "pending_transaction_count": counts.get(
                TransactionStatus.PENDING, 0
            ),
            "failed_transaction_count": counts.get(
                TransactionStatus.FAILED, 0
            ),
        }

    @staticmethod
    def activity(circle, limit=ACTIVITY_LIMIT):
        """
        Allowlisted audit events for this circle, newest first.

        AuditLog has no circle foreign key; each supported action is
        matched through the way its writer encodes the circle:
        - entity_type "Circle" + entity_id = circle id
        - metadata["circle_id"] (constitution / invitation events)
        - entity_id of this circle's Payout / CircleRestructure rows
        Ledger events are excluded (they carry individual members'
        amounts and payment references).
        """
        circle_id = str(circle.id)

        payout_windows = {
            str(pk): window
            for pk, window in Payout.objects
            .filter(circle=circle)
            .values_list("id", "payout_window")
        }
        restructure_ids = [
            str(pk)
            for pk in CircleRestructure.objects
            .filter(circle=circle)
            .values_list("id", flat=True)
        ]

        match = (
            Q(
                action__in=[
                    "CIRCLE_CREATED",
                    "CIRCLE_READY",
                    "CIRCLE_LOCKED",
                    "PAYOUT_WINDOW_CREATED",
                ],
                entity_type="Circle",
                entity_id=circle_id,
            )
            | Q(
                action__in=["CONSTITUTION_ACCEPTED", "INVITATION_CREATED", "INVITATION_ACCEPTED"],
                metadata__circle_id=circle_id,
            )
            | Q(
                action__in=["PAYOUT_APPROVED", "PAYOUT_COMPLETED"],
                entity_type="Payout",
                entity_id__in=list(payout_windows),
            )
            | Q(
                action="RESTRUCTURE_PROPOSED",
                entity_type="CircleRestructure",
                entity_id__in=restructure_ids,
            )
        )

        logs = (
            AuditLog.objects
            .filter(match)
            .select_related("user")
            .order_by("-created_at")[:limit]
        )

        # A fixed, reviewed schema: metadata is never passed through. The
        # only metadata value read is the integer payout window.
        events = []
        for log in logs:
            window = None
            if log.action == "PAYOUT_WINDOW_CREATED":
                value = log.metadata.get("window")
                window = value if isinstance(value, int) else None
            elif log.action in ("PAYOUT_APPROVED", "PAYOUT_COMPLETED"):
                window = payout_windows.get(log.entity_id)

            events.append({
                "id": log.id,
                "event": ACTIVITY_EVENTS[log.action],
                "occurred_at": log.created_at,
                "member": display_name(log.user),
                "payout_window": window,
            })

        return events
