from decimal import Decimal

from rest_framework import serializers

from circles.models import (
    Circle,
    CircleConstitution,
    CircleMembership,
)
from finance.models import (
    ContributionObligation,
    Payout,
)
from services.circles.circle_read_service import display_name


class CircleConstitutionSerializer(serializers.ModelSerializer):

    class Meta:
        model = CircleConstitution
        fields = [
            "member_limit",
            "contribution_amount",
            "contribution_frequency",
            "payout_amount",
            "payout_frequency",
            "cycle_length",
            "quorum_percentage",
            "grace_period_days",
            "reserve_enabled",
            "reserve_amount",
            "allow_replacement_before_lock",
        ]


class CircleSerializer(serializers.ModelSerializer):

    constitution = CircleConstitutionSerializer(
        read_only=True
    )

    class Meta:
        model = Circle
        fields = [
            "id",
            "name",
            "description",
            "status",
            "created_at",
            "updated_at",
            "financial_locked_at",
            "constitution",
        ]


class CreateCircleSerializer(serializers.Serializer):

    name = serializers.CharField(
        max_length=120
    )

    description = serializers.CharField(
        required=False,
        allow_blank=True
    )

    member_limit = serializers.IntegerField(
        min_value=2,
        max_value=100
    )

    contribution_amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.01")
    )

    payout_amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.01")
    )

    contribution_frequency = serializers.CharField(
        default="weekly"
    )

    payout_frequency = serializers.CharField(
        default="biweekly"
    )

    cycle_length = serializers.IntegerField(
        min_value=1
    )

    quorum_percentage = serializers.IntegerField(
        min_value=1,
        max_value=100
    )

    grace_period_days = serializers.IntegerField(
        min_value=0
    )

    reserve_enabled = serializers.BooleanField(
        default=False
    )

    reserve_amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0")
    )

    allow_replacement_before_lock = serializers.BooleanField(
        default=True
    )

class CircleConstitutionSummarySerializer(serializers.ModelSerializer):

    class Meta:
        model = CircleConstitution
        fields = [
            "member_limit",
            "contribution_amount",
            "contribution_frequency",
            "payout_amount",
            "payout_frequency",
            "cycle_length",
        ]


class MyCircleSerializer(serializers.ModelSerializer):
    """GET /api/circles/ item (circles where the requester is ACTIVE)."""

    constitution = CircleConstitutionSummarySerializer(
        read_only=True
    )

    member_count = serializers.IntegerField(
        source="active_member_count",
        read_only=True
    )

    class Meta:
        model = Circle
        fields = [
            "id",
            "name",
            "description",
            "status",
            "created_at",
            "member_count",
            "constitution",
        ]


class CircleMemberSerializer(serializers.ModelSerializer):
    """
    What one circle member may see about another. Deliberately no email,
    user id, profile details or risk data.
    """

    display_name = serializers.SerializerMethodField()
    username = serializers.CharField(source="user.username")
    is_creator = serializers.SerializerMethodField()
    is_you = serializers.SerializerMethodField()

    class Meta:
        model = CircleMembership
        fields = [
            "id",
            "display_name",
            "username",
            "status",
            "joined_at",
            "constitution_accepted",
            "constitution_accepted_at",
            "is_creator",
            "is_you",
        ]

    def get_display_name(self, membership):
        return display_name(membership.user)

    def get_is_creator(self, membership):
        return membership.user_id == membership.circle.creator_id

    def get_is_you(self, membership):
        return membership.user_id == self.context["request"].user.pk


class ObligationSerializer(serializers.ModelSerializer):

    class Meta:
        model = ContributionObligation
        fields = [
            "id",
            "period_number",
            "amount_due",
            "due_date",
            "status",
            "paid_at",
        ]


class PayoutSerializer(serializers.ModelSerializer):

    recipient = serializers.SerializerMethodField()
    is_you = serializers.SerializerMethodField()
    # Latest attempt state (prepared / submitted / unknown / succeeded /
    # failed / returned), or null before any attempt. No provider data.
    attempt_state = serializers.SerializerMethodField()

    class Meta:
        model = Payout
        fields = [
            "id",
            "payout_window",
            "amount",
            "status",
            "recipient",
            "is_you",
            "created_at",
            "approved_at",
            "paid_at",
            "attempt_state",
        ]

    def get_attempt_state(self, payout):
        latest = max(
            payout.attempts.all(),
            key=lambda attempt: attempt.attempt_number,
            default=None,
        )
        return latest.state if latest else None

    def get_recipient(self, payout):
        return display_name(payout.member)

    def get_is_you(self, payout):
        return payout.member_id == self.context["request"].user.pk


class OpenPayoutWindowSerializer(serializers.Serializer):

    payout_window = serializers.IntegerField()
    candidate_count = serializers.IntegerField()


class LedgerTypeTotalSerializer(serializers.Serializer):

    total = serializers.DecimalField(max_digits=14, decimal_places=2)
    count = serializers.IntegerField()


class TreasurySummarySerializer(serializers.Serializer):

    balance = serializers.DecimalField(max_digits=14, decimal_places=2)
    reserved_for_payouts = serializers.DecimalField(max_digits=14, decimal_places=2)
    available_balance = serializers.DecimalField(max_digits=14, decimal_places=2)
    completed_transaction_count = serializers.IntegerField()
    totals = serializers.DictField(child=LedgerTypeTotalSerializer())
    pending_transaction_count = serializers.IntegerField()
    failed_transaction_count = serializers.IntegerField()


class ActivityEventSerializer(serializers.Serializer):

    id = serializers.UUIDField()
    event = serializers.CharField()
    occurred_at = serializers.DateTimeField()
    member = serializers.CharField(allow_null=True)
    payout_window = serializers.IntegerField(allow_null=True)


class CircleRefSerializer(serializers.ModelSerializer):

    class Meta:
        model = Circle
        fields = ["id", "name"]


class MyObligationSerializer(ObligationSerializer):
    """Cross-circle item: the circle-scoped fields plus the circle."""

    circle = CircleRefSerializer(read_only=True)

    class Meta(ObligationSerializer.Meta):
        fields = ObligationSerializer.Meta.fields + ["circle"]


class ObligationRecordSerializer(serializers.Serializer):

    total = serializers.IntegerField()
    pending = serializers.IntegerField()
    paid = serializers.IntegerField()
    overdue = serializers.IntegerField()
    waived = serializers.IntegerField()


class TrustHistorySerializer(serializers.Serializer):

    completed_circles = serializers.IntegerField()
    paid_contributions = serializers.IntegerField()
    overdue_contributions = serializers.IntegerField()


class TrustCircleSerializer(serializers.Serializer):

    active_members = serializers.IntegerField()
    invitation_connections = serializers.IntegerField()


class TrustSummarySerializer(serializers.Serializer):

    data_status = serializers.ChoiceField(
        choices=["available", "insufficient_data"]
    )
    your_record_in_circle = ObligationRecordSerializer()
    your_history = TrustHistorySerializer()
    circle = TrustCircleSerializer()
    score = serializers.ReadOnlyField()
    score_unavailable_reasons = serializers.ListField(
        child=serializers.CharField()
    )


class PayoutCandidateSerializer(serializers.Serializer):

    id = serializers.UUIDField()
    display_name = serializers.CharField()
    is_you = serializers.BooleanField()
    status = serializers.CharField()


class PayoutWindowSerializer(serializers.Serializer):
    """One payout window as a member may see it (no vote attribution)."""

    payout_window = serializers.IntegerField()
    state = serializers.ChoiceField(
        choices=["open", "approved", "paid", "failed", "closed"]
    )
    candidates = PayoutCandidateSerializer(many=True)
    votes_cast = serializers.IntegerField(allow_null=True)
    votes_required = serializers.IntegerField(allow_null=True)
    your_vote = serializers.UUIDField(allow_null=True)
    payout = PayoutSerializer(allow_null=True)
    can_vote = serializers.BooleanField()
    can_approve = serializers.BooleanField()
    can_execute = serializers.BooleanField()


class PayoutVoteRequestSerializer(serializers.Serializer):

    candidate_id = serializers.UUIDField()
