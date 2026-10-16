"""
Deterministic knowledge documents built from Osusu domain data.

Rules:
- READ-ONLY: only SELECT queries. Financial figures come from the domain
  engines (TreasuryEngine) or directly from stored records; nothing here
  computes or decides financial outcomes.
- DETERMINISTIC: no clocks, randomness or LLMs. Same data -> same text ->
  same content_hash. Every collection is explicitly ordered.
- ALLOWLISTED: only fields chosen below enter a document. Never emails,
  credentials, raw audit metadata, raw ML features, or cross-circle
  member history (see Sprint 22.5 privacy boundary).
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Count, Q

from audit.models import AuditLog
from circles.models import CircleMembership, MembershipStatus
from finance.models import (
    ContributionObligation,
    ObligationStatus,
    Payout,
    TransactionType,
)
from knowledge.models import KnowledgeDocumentType
from risk.models import RiskAssessment

from services.finance.treasury_engine import TreasuryEngine
from services.knowledge.schema import (
    KNOWLEDGE_SCHEMA_VERSION,
    MAX_USER_TEXT_LENGTH,
    USER_TEXT_PREFIX,
    display_name,
    document_hash,
    humanize,
    money,
    plural,
    sort_name,
    timestamp,
    with_article,
)
from services.ml.model_registry import ModelArtifactError, ModelRegistry
from services.ml.predict_default_risk import DefaultRiskPredictor
from services.trust.trust_graph_service import TrustGraphService


AUDIT_EVENT_LIMIT = 50

# Allowlisted audit actions -> fixed wording. Audit metadata is never
# copied wholesale (it can contain emails); only the integer payout window
# is read for PAYOUT_WINDOW_CREATED.
AUDIT_TEMPLATES = {
    "CIRCLE_CREATED": "Circle created",
    "CIRCLE_READY": "Circle passed formation checks and became ready",
    "INVITATION_CREATED": "An invitation to join was sent",
    "INVITATION_ACCEPTED": "An invitation to join was accepted",
    "CONSTITUTION_ACCEPTED": "The circle constitution was accepted",
}

OBLIGATION_ORDER = [
    ObligationStatus.PAID,
    ObligationStatus.PENDING,
    ObligationStatus.OVERDUE,
    ObligationStatus.WAIVED,
]


@dataclass(frozen=True)
class BuiltDocument:
    document_type: str
    entity_type: str
    entity_id: str
    circle_id: str
    subject_user_id: str | None
    title: str
    content: str
    metadata: dict = field(default_factory=dict)

    @property
    def content_hash(self):
        return document_hash(
            document_type=self.document_type,
            entity_type=self.entity_type,
            entity_id=self.entity_id,
            title=self.title,
            content=self.content,
        )


@dataclass
class CircleKnowledgeContext:
    """Everything the templates need, loaded with a fixed number of queries."""

    circle: object
    constitution: object | None
    memberships: list
    obligations_by_member: dict
    treasury_balance: Decimal
    treasury_transaction_count: int
    ledger_totals: dict
    payouts: list
    trust_connections: int
    successful_trust_connections: int
    risk_assessment: object | None
    audit_events: list
    member_ids: set


class KnowledgeDocumentBuilder:

    @classmethod
    def build_circle_documents(cls, circle):
        context = cls.load_context(circle)

        documents = [
            cls.circle_summary(context),
            cls.circle_financial_summary(context),
            *cls.member_contribution_summaries(context),
            cls.payout_summary(context),
            cls.risk_summary(context),
            cls.audit_summary(context),
        ]

        return sorted(
            documents,
            key=lambda d: (d.document_type, d.entity_id),
        )

    # Loading

    @staticmethod
    def load_context(circle):
        circle = (
            type(circle).objects
            .select_related("constitution", "creator")
            .get(pk=circle.pk)
        )

        try:
            constitution = circle.constitution
        except type(circle).constitution.RelatedObjectDoesNotExist:
            constitution = None

        memberships = sorted(
            CircleMembership.objects
            .filter(circle=circle)
            .select_related("user", "invited_by"),
            key=lambda m: sort_name(m.user),
        )

        obligations_by_member = defaultdict(list)
        for obligation in (
            ContributionObligation.objects
            .filter(circle=circle)
            .order_by("member_id", "period_number")
        ):
            obligations_by_member[obligation.member_id].append(obligation)

        treasury = TreasuryEngine.summary(circle)

        payouts = list(
            Payout.objects
            .filter(circle=circle)
            .select_related("member")
            .annotate(vote_count=Count("votes"))
            .order_by("payout_window", "member_id")
        )

        edges = TrustGraphService.get_graph_for_circle(circle)

        risk_assessment = (
            RiskAssessment.objects
            .filter(circle=circle)
            .prefetch_related("signals")
            .order_by("-created_at", "-id")
            .first()
        )

        circle_id = str(circle.id)
        audit_events = list(
            AuditLog.objects
            .filter(
                Q(entity_type="Circle", entity_id=circle_id)
                | Q(metadata__circle_id=circle_id)
            )
            .select_related("user")
            .order_by("-created_at", "-id")[:AUDIT_EVENT_LIMIT]
        )
        audit_events.reverse()

        return CircleKnowledgeContext(
            circle=circle,
            constitution=constitution,
            memberships=memberships,
            obligations_by_member=obligations_by_member,
            treasury_balance=treasury["balance"],
            treasury_transaction_count=treasury["transactions"],
            ledger_totals=TreasuryEngine.ledger_totals(circle),
            payouts=payouts,
            trust_connections=edges.count(),
            successful_trust_connections=edges.filter(
                successful_cycles_together__gt=0,
            ).count(),
            risk_assessment=risk_assessment,
            audit_events=audit_events,
            member_ids={m.user_id for m in memberships},
        )

    # Helpers

    @staticmethod
    def _document(context, *, document_type, title, lines,
                  entity_type="circle", entity_id=None, subject_user=None):
        circle = context.circle
        entity_id = str(entity_id or circle.id)

        return BuiltDocument(
            document_type=document_type,
            entity_type=entity_type,
            entity_id=entity_id,
            circle_id=str(circle.id),
            subject_user_id=str(subject_user.pk) if subject_user else None,
            title=title,
            content="\n".join(lines).strip() + "\n",
            metadata={
                "schema_version": KNOWLEDGE_SCHEMA_VERSION,
                "document_type": document_type,
                "source_entity_type": entity_type,
                "source_entity_id": entity_id,
                "circle_id": str(circle.id),
                "subject_user_id": (
                    str(subject_user.pk) if subject_user else None
                ),
            },
        )

    @staticmethod
    def _active(context):
        return [
            m for m in context.memberships
            if m.status == MembershipStatus.ACTIVE
        ]

    # Documents

    @classmethod
    def circle_summary(cls, context):
        circle = context.circle
        c = context.constitution
        active = cls._active(context)
        status_counts = Counter(m.status for m in context.memberships)

        lines = [
            f"Circle {circle.name} is currently {humanize(circle.status)}.",
        ]
        if circle.description:
            # User-authored: one line, never structure (see schema.py).
            text = " ".join(circle.description.split())
            if len(text) > MAX_USER_TEXT_LENGTH:
                text = text[:MAX_USER_TEXT_LENGTH].rstrip() + "..."
            lines.append(USER_TEXT_PREFIX + text)
        lines += [
            f"Created: {timestamp(circle.created_at)}.",
            "Financially locked: "
            + (
                f"{timestamp(circle.financial_locked_at)}."
                if circle.financial_locked_at
                else "not locked."
            ),
            "",
            "## Membership",
            f"The circle has {plural(len(active), 'active member')}.",
        ]

        inactive_parts = [
            f"{status_counts[s]} {humanize(s)}"
            for s in (
                MembershipStatus.INVITED,
                MembershipStatus.LEFT,
                MembershipStatus.REMOVED,
            )
            if status_counts[s]
        ]
        if inactive_parts:
            lines.append(
                "Inactive memberships: " + ", ".join(inactive_parts) + "."
            )

        for m in context.memberships:
            accepted = (
                f"accepted the constitution on "
                f"{timestamp(m.constitution_accepted_at)}"
                if m.constitution_accepted
                else "has not accepted the constitution"
            )

            # Only name inviters who belong to this circle.
            if m.invited_by_id and m.invited_by_id in context.member_ids:
                origin = f"invited by {display_name(m.invited_by)}"
            elif m.user_id == circle.creator_id:
                origin = "circle creator"
            else:
                origin = "joined without a recorded inviter in this circle"

            lines.append(
                f"- {display_name(m.user)}: {humanize(m.status)} member, "
                f"joined {timestamp(m.joined_at)}, {accepted}, {origin}."
            )

        lines += ["", "## Constitution"]
        if c is None:
            lines.append("No constitution has been recorded.")
        else:
            reserve = (
                f"enabled with {money(c.reserve_amount)}"
                if c.reserve_enabled
                else "disabled"
            )
            lines += [
                f"Members contribute {money(c.contribution_amount)} "
                f"{c.contribution_frequency}.",
                f"The configured payout amount is {money(c.payout_amount)} "
                f"{c.payout_frequency}.",
                f"The cycle length is {c.cycle_length} periods.",
                f"The member limit is {c.member_limit}.",
                f"Governance quorum is {c.quorum_percentage}%.",
                f"The grace period is {c.grace_period_days} days.",
                f"The reserve is {reserve}.",
                "Replacing members before the financial lock is "
                + (
                    "allowed."
                    if c.allow_replacement_before_lock
                    else "not allowed."
                ),
            ]

        lines += [
            "",
            "## Trust",
            f"There are {context.trust_connections} trust connections "
            f"between members of this circle; "
            f"{context.successful_trust_connections} of them have completed "
            f"at least one successful cycle together.",
        ]

        return cls._document(
            context,
            document_type=KnowledgeDocumentType.CIRCLE_SUMMARY,
            title=f"Circle: {circle.name}",
            lines=lines,
        )

    @classmethod
    def circle_financial_summary(cls, context):
        circle = context.circle
        totals = context.ledger_totals

        def total_line(label, transaction_type):
            entry = totals[transaction_type]
            return (
                f"- {label}: {money(entry['total'])} across "
                f"{plural(entry['count'], 'transaction')}."
            )

        lines = [
            f"The current treasury balance of {circle.name} is "
            f"{money(context.treasury_balance)}, based on "
            f"{plural(context.treasury_transaction_count, 'completed ledger transaction')}.",
            "Balances come from the immutable ledger via the treasury "
            "engine.",
            "",
            "## Completed ledger totals",
            total_line("Contributions", TransactionType.CONTRIBUTION),
            total_line("Payouts", TransactionType.PAYOUT),
            total_line("Reserve", TransactionType.RESERVE),
            total_line("Refunds", TransactionType.REFUND),
            total_line("Adjustments (incoming)", TransactionType.ADJUSTMENT),
            total_line("Adjustments (outgoing)", TransactionType.ADJUSTMENT_OUT),
            total_line("Payout returns", TransactionType.PAYOUT_RETURN),
            "",
            "## Contribution obligations",
        ]

        all_obligations = [
            o
            for member_obligations in context.obligations_by_member.values()
            for o in member_obligations
        ]

        if not all_obligations:
            lines.append("No contribution obligations have been created.")
        else:
            lines.append(
                f"Contribution obligations in total: {len(all_obligations)}."
            )
            for status in OBLIGATION_ORDER:
                matching = [o for o in all_obligations if o.status == status]
                amount = sum(
                    (o.amount_due for o in matching),
                    Decimal("0"),
                )
                lines.append(
                    f"- {humanize(status).capitalize()}: {len(matching)} "
                    f"totalling {money(amount)}."
                )

        return cls._document(
            context,
            document_type=KnowledgeDocumentType.CIRCLE_FINANCIAL_SUMMARY,
            title=f"Treasury: {circle.name}",
            lines=lines,
        )

    @classmethod
    def member_contribution_summaries(cls, context):
        circle = context.circle
        documents = []

        for m in context.memberships:
            obligations = context.obligations_by_member.get(m.user_id, [])

            if m.status != MembershipStatus.ACTIVE and not obligations:
                continue

            name = display_name(m.user)
            counts = Counter(o.status for o in obligations)

            lines = [
                f"{name} is {with_article(humanize(m.status))} member of "
                f"{circle.name}.",
            ]

            if not obligations:
                lines.append(
                    f"{name} has no contribution obligations yet."
                )
            else:
                summary = ", ".join(
                    f"{counts[s]} {humanize(s)}" for s in OBLIGATION_ORDER
                )
                lines += [
                    f"{name} has "
                    f"{plural(len(obligations), 'contribution obligation')}: "
                    f"{summary}.",
                    "",
                    "## Obligations",
                ]
                for o in obligations:
                    paid = (
                        f", paid {timestamp(o.paid_at)}"
                        if o.status == ObligationStatus.PAID
                        else ""
                    )
                    lines.append(
                        f"- Period {o.period_number}: {money(o.amount_due)} "
                        f"due {timestamp(o.due_date)}, status "
                        f"{humanize(o.status)}{paid}."
                    )

            documents.append(
                cls._document(
                    context,
                    document_type=(
                        KnowledgeDocumentType.MEMBER_CONTRIBUTION_SUMMARY
                    ),
                    title=f"Contributions: {name} in {circle.name}",
                    lines=lines,
                    entity_type="circle_membership",
                    entity_id=m.id,
                    subject_user=m.user,
                )
            )

        return documents

    @classmethod
    def payout_summary(cls, context):
        circle = context.circle
        lines = []

        if context.constitution is not None:
            lines.append(
                f"The constitution sets payouts of "
                f"{money(context.constitution.payout_amount)} "
                f"{context.constitution.payout_frequency}."
            )

        if not context.payouts:
            lines.append("No payouts have been scheduled for this circle yet.")
        else:
            windows = defaultdict(list)
            for payout in context.payouts:
                windows[payout.payout_window].append(payout)

            for window in sorted(windows):
                lines += ["", f"## Payout window {window}"]
                for p in sorted(
                    windows[window],
                    key=lambda p: sort_name(p.member),
                ):
                    lines.append(
                        f"- {display_name(p.member)}: {money(p.amount)}, "
                        f"status {humanize(p.status)}, approved "
                        f"{timestamp(p.approved_at)}, paid "
                        f"{timestamp(p.paid_at)}, "
                        f"{plural(p.vote_count, 'member vote')}."
                    )

        return cls._document(
            context,
            document_type=KnowledgeDocumentType.PAYOUT_SUMMARY,
            title=f"Payouts: {circle.name}",
            lines=lines,
        )

    @classmethod
    def risk_summary(cls, context):
        circle = context.circle
        assessment = context.risk_assessment

        lines = ["## Circle risk assessment"]

        if assessment is None:
            lines.append("No circle risk assessment has been recorded.")
        else:
            score = (
                f", score {assessment.risk_score}"
                if assessment.risk_score is not None
                else ""
            )
            lines.append(
                f"The latest circle risk assessment "
                f"({timestamp(assessment.created_at)}, "
                f"{assessment.model_version}) rated the circle "
                f"{assessment.risk_level} risk{score}."
            )
            for signal in sorted(
                assessment.signals.all(),
                key=lambda s: (s.signal_type, s.severity, s.message),
            ):
                lines.append(
                    f"- {humanize(signal.signal_type).lower()} "
                    f"({signal.severity}): {signal.message}"
                )

        lines += ["", "## Member default-risk signals"]
        lines += cls._member_risk_lines(context)

        return cls._document(
            context,
            document_type=KnowledgeDocumentType.RISK_SUMMARY,
            title=f"Risk: {circle.name}",
            lines=lines,
        )

    @classmethod
    def _member_risk_lines(cls, context):
        """
        Same exposure as the default-risk API: probability and model
        version for ACTIVE members only; never the raw features.
        """
        try:
            artifact = ModelRegistry.load()
        except ModelArtifactError:
            return [
                "No trained default-risk model is available, so member "
                "default-risk signals are not included."
            ]

        lines = [
            f"Probabilities come from model {artifact.model_version} "
            f"({artifact.feature_version}). They are informational risk "
            f"signals only: they do not approve or reject payouts, move "
            f"money, or override governance.",
        ]

        for m in cls._active(context):
            prediction = DefaultRiskPredictor.predict(
                circle=context.circle,
                member=m.user,
                model_version=artifact.model_version,
            )
            lines.append(
                f"- {display_name(m.user)}: estimated default probability "
                f"{prediction['default_probability'] * 100:.2f}%."
            )

        return lines

    @classmethod
    def audit_summary(cls, context):
        circle = context.circle
        events = context.audit_events

        if not events:
            lines = ["No activity has been recorded for this circle."]
        else:
            lines = [
                f"The {len(events)} most recent recorded events, oldest "
                f"first:",
            ]
            for event in events:
                actor = (
                    display_name(event.user)
                    if event.user_id in context.member_ids
                    else "the system"
                )
                lines.append(
                    f"- {timestamp(event.created_at)}: "
                    f"{cls._describe_audit(event)} by {actor}."
                )

        return cls._document(
            context,
            document_type=KnowledgeDocumentType.AUDIT_SUMMARY,
            title=f"Activity: {circle.name}",
            lines=lines,
        )

    @staticmethod
    def _describe_audit(event):
        if event.action == "PAYOUT_WINDOW_CREATED":
            window = (event.metadata or {}).get("window")
            if isinstance(window, int):
                return f"Payout window {window} was opened"
            return "A payout window was opened"

        return AUDIT_TEMPLATES.get(
            event.action,
            humanize(event.action).capitalize(),
        )
