from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from circles.access import (
    authorize_creator,
    authorize_member,
)

from services.circles.circle_service import CircleService
from services.circles.formation_service import CircleFormationService
from services.circles.financial_lock_engine import FinancialLockEngine
from services.circles.constitution_service import ConstitutionService

from services.circles.circle_read_service import CircleReadService

from .serializers import (
    ActivityEventSerializer,
    CircleMemberSerializer,
    CircleSerializer,
    CreateCircleSerializer,
    MyCircleSerializer,
    MyObligationSerializer,
    ObligationSerializer,
    OpenPayoutWindowSerializer,
    PayoutSerializer,
    TreasurySummarySerializer,
    TrustSummarySerializer,
    PayoutVoteRequestSerializer,
    PayoutWindowSerializer,
)
from circles.models import CircleStatus
from finance.models import Payout, PayoutStatus
from finance.models import UNRESOLVED_PAYOUT_STATUSES as UNRESOLVED_STATUSES
from services.payouts.execute_payout_service import (
    ExecutePayoutService,
    PayoutProviderUnavailable,
)
from services.payouts.payout_approval_service import (
    DECIDED_STATUSES,
    PayoutApprovalService,
)
from services.payouts.payout_engine import PayoutEngine
from services.payouts.payout_vote_service import PayoutVoteService
from circles.models import CircleInvitation
from services.circles.invitation_service import InvitationService


class CreateCircleView(APIView):
    """
    GET  /api/circles/ -> circles where the requester is an ACTIVE member.
    POST /api/circles/ -> create a circle.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):

        circles = CircleReadService.circles_for_user(
            request.user
        )

        return Response(
            MyCircleSerializer(circles, many=True).data
        )

    def post(self, request):

        serializer = CreateCircleSerializer(
            data=request.data
        )

        serializer.is_valid(
            raise_exception=True
        )

        data = serializer.validated_data

        circle = CircleService.create_circle(
            creator=request.user,
            name=data["name"],
            description=data.get(
                "description",
                ""
            ),
            member_limit=data["member_limit"],
            contribution_amount=data[
                "contribution_amount"
            ],
        )

        constitution = circle.constitution

        constitution.payout_amount = data[
            "payout_amount"
        ]

        constitution.contribution_frequency = data[
            "contribution_frequency"
        ]

        constitution.payout_frequency = data[
            "payout_frequency"
        ]

        constitution.cycle_length = data[
            "cycle_length"
        ]

        constitution.quorum_percentage = data[
            "quorum_percentage"
        ]

        constitution.grace_period_days = data[
            "grace_period_days"
        ]

        constitution.reserve_enabled = data[
            "reserve_enabled"
        ]

        constitution.reserve_amount = data[
            "reserve_amount"
        ]

        constitution.allow_replacement_before_lock = data[
            "allow_replacement_before_lock"
        ]

        constitution.save()

        return Response(
            CircleSerializer(circle).data,
            status=status.HTTP_201_CREATED
        )


class CircleDetailView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request, circle_id):

        # Active members only; outsiders get the same 404 as a
        # nonexistent circle.
        circle = authorize_member(request, circle_id).circle

        return Response(
            CircleSerializer(circle).data
        )


class EvaluateFormationView(APIView):

    permission_classes = [IsAuthenticated]

    def post(self, request, circle_id):

        # Creator only: a passing evaluation moves the circle to READY and
        # is audited as the creator's action.
        circle = authorize_creator(request, circle_id).circle

        try:

            result = CircleFormationService.evaluate(
                circle
            )

        except ValueError as error:

            return Response(
                {
                    "ready": False,
                    "error": str(error),
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(result)


class FinancialLockView(APIView):

    permission_classes = [IsAuthenticated]

    def post(self, request, circle_id):

        # Creator only: financial lock is an irreversible commitment.
        circle = authorize_creator(request, circle_id).circle

        try:

            circle = FinancialLockEngine.lock(
                circle,
                user=request.user,
            )

        except ValueError as error:

            # Report which requirements failed (booleans only), as
            # FinancialLockEngine evaluated them.
            return Response(
                {
                    "locked": False,
                    "error": str(error),
                    "checks": FinancialLockEngine.validate(
                        circle
                    )["checks"],
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {
                "locked": True,
                "circle": CircleSerializer(
                    circle
                ).data,
            }
        )


class AcceptConstitutionView(APIView):

    permission_classes = [IsAuthenticated]

    def post(self, request, circle_id):

        circle = authorize_member(request, circle_id).circle

        try:
            membership = ConstitutionService.accept(
                circle=circle,
                user=request.user,
            )

        except ValueError as error:

            return Response(
                {
                    "accepted": False,
                    "error": str(error),
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {
                "accepted": True,
                "circle_id": str(circle.id),
                "membership_id": str(membership.id),
                "accepted_at": (
                    membership.constitution_accepted_at
                ),
            },
            status=status.HTTP_200_OK
        )


class CreateInvitationView(APIView):

    permission_classes = [IsAuthenticated]

    def post(self, request, circle_id):

        # Any active member may invite (InvitationService's existing
        # rule). Checked here first so outsiders cannot learn the circle's
        # existence or status from the service's error messages.
        circle = authorize_member(request, circle_id).circle

        email = request.data.get("email")

        if not email:
            return Response(
                {
                    "invited": False,
                    "error": "Email is required."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        try:

            invitation = InvitationService.create_invitation(
                circle=circle,
                inviter=request.user,
                email=email,
            )

        except ValueError as error:

            return Response(
                {
                    "invited": False,
                    "error": str(error),
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {
                "invited": True,
                "invitation_id": str(invitation.id),
                "email": invitation.email,
                "expires_at": invitation.expires_at,
                "token": invitation.token,
            },
            status=status.HTTP_201_CREATED
        )


class AcceptInvitationView(APIView):

    permission_classes = [IsAuthenticated]

    def post(self, request, token):

        invitation = get_object_or_404(
            CircleInvitation,
            token=token
        )

        try:

            membership = InvitationService.accept_invitation(
                invitation=invitation,
                user=request.user,
            )

        except ValueError as error:

            return Response(
                {
                    "accepted": False,
                    "error": str(error),
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {
                "accepted": True,
                "circle_id": str(
                    membership.circle.id
                ),
                "membership_id": str(
                    membership.id
                ),
                "status": membership.status,
            },
            status=status.HTTP_200_OK
        )

class CircleMembersView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request, circle_id):

        circle = authorize_member(request, circle_id).circle

        return Response(
            CircleMemberSerializer(
                CircleReadService.members(circle),
                many=True,
                context={"request": request},
            ).data
        )


class MyObligationsView(APIView):
    """The requester's own obligations in this circle; nobody else's."""

    permission_classes = [IsAuthenticated]

    def get(self, request, circle_id):

        circle = authorize_member(request, circle_id).circle

        return Response(
            ObligationSerializer(
                CircleReadService.obligations_for_member(
                    circle,
                    request.user,
                ),
                many=True,
            ).data
        )


class CirclePayoutsView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request, circle_id):

        circle = authorize_member(request, circle_id).circle

        result = CircleReadService.payouts(circle)

        return Response(
            {
                "payouts": PayoutSerializer(
                    result["payouts"],
                    many=True,
                    context={"request": request},
                ).data,
                "open_windows": OpenPayoutWindowSerializer(
                    result["open_windows"],
                    many=True,
                ).data,
            }
        )


class CircleTreasuryView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request, circle_id):

        circle = authorize_member(request, circle_id).circle

        return Response(
            TreasurySummarySerializer(
                CircleReadService.treasury(circle)
            ).data
        )


class CircleActivityView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request, circle_id):

        circle = authorize_member(request, circle_id).circle

        return Response(
            ActivityEventSerializer(
                CircleReadService.activity(circle),
                many=True,
            ).data
        )


class CircleTrustView(APIView):
    """Factual trust information for the requester; no score."""

    permission_classes = [IsAuthenticated]

    def get(self, request, circle_id):

        circle = authorize_member(request, circle_id).circle

        return Response(
            TrustSummarySerializer(
                CircleReadService.trust(circle, request.user)
            ).data
        )


class MyObligationsAcrossCirclesView(APIView):
    """
    GET /api/users/me/obligations/ - the requester's own obligations in
    every circle where they are ACTIVE. Takes no user parameter.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):

        return Response(
            MyObligationSerializer(
                CircleReadService.obligations_for_user(request.user),
                many=True,
            ).data
        )


# Payout windows can only be opened once members are financially
# committed (after the financial lock).
PAYOUT_CIRCLE_STATUSES = (
    CircleStatus.LOCKED,
    CircleStatus.ACTIVE,
)

UNRESOLVED_PAYOUT_STATUSES = (PayoutStatus.PENDING, *UNRESOLVED_STATUSES)


def _window_response(request, membership, window, status_code=200, **extra):
    detail = CircleReadService.payout_window(
        membership.circle,
        window,
        request.user,
        is_creator=membership.circle.creator_id == request.user.pk,
    )
    body = {
        "window": (
            PayoutWindowSerializer(detail, context={"request": request}).data
            if detail else None
        ),
        **extra,
    }
    return Response(body, status=status_code)


def _error(message, status_code=status.HTTP_400_BAD_REQUEST, **extra):
    return Response({"error": message, **extra}, status=status_code)


class PayoutWindowsView(APIView):
    """
    GET  -> the circle's latest payout window (or null) + whether the
            requester may open the next one.
    POST -> creator opens the next window (PayoutEngine). The window
            number is chosen by the server, never the client.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, circle_id):

        membership = authorize_member(request, circle_id)
        circle = membership.circle
        latest = CircleReadService.latest_payout_window(circle)

        can_open = (
            circle.creator_id == request.user.pk
            and circle.status in PAYOUT_CIRCLE_STATUSES
            and not Payout.objects.filter(
                circle=circle,
                status__in=UNRESOLVED_PAYOUT_STATUSES,
            ).exists()
        )

        return _window_response(
            request,
            membership,
            latest,
            can_open_window=can_open,
        ) if latest else Response({"window": None, "can_open_window": can_open})

    def post(self, request, circle_id):

        membership = authorize_creator(request, circle_id)
        circle = membership.circle

        if circle.status not in PAYOUT_CIRCLE_STATUSES:
            return _error(
                "Payout windows open only after the financial lock."
            )

        window = (CircleReadService.latest_payout_window(circle) or 0) + 1

        try:
            PayoutEngine.create_payout_window(
                circle=circle,
                payout_window=window,
            )
        except ValueError as error:
            return _error(str(error))

        return _window_response(
            request, membership, window, status.HTTP_201_CREATED,
        )


class PayoutWindowDetailView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request, circle_id, window):

        membership = authorize_member(request, circle_id)

        response = _window_response(request, membership, window)
        if response.data["window"] is None:
            return Response(
                {"detail": "Payout window not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return response


class PayoutVoteView(APIView):
    """Any ACTIVE member; PayoutVoteService decides eligibility."""

    permission_classes = [IsAuthenticated]

    def post(self, request, circle_id, window):

        membership = authorize_member(request, circle_id)

        serializer = PayoutVoteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Looked up inside this circle's window only: an id from any other
        # window or circle is indistinguishable from a nonexistent one.
        candidate = Payout.objects.filter(
            circle=membership.circle,
            payout_window=window,
            pk=serializer.validated_data["candidate_id"],
        ).first()

        if candidate is None:
            return _error("Candidate is not in this payout window.")

        try:
            PayoutVoteService.cast_vote(
                payout=candidate,
                voter=request.user,
            )
        except ValueError as error:
            return _error(str(error))

        return _window_response(request, membership, window)


class PayoutApproveView(APIView):
    """Creator only; PayoutApprovalService enforces the quorum."""

    permission_classes = [IsAuthenticated]

    def post(self, request, circle_id, window):

        membership = authorize_creator(request, circle_id)

        if not Payout.objects.filter(
            circle=membership.circle, payout_window=window,
        ).exists():
            return Response(
                {"detail": "Payout window not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            PayoutApprovalService.approve(membership.circle, window)
        except ValueError as error:
            detail = _window_response(request, membership, window).data
            return _error(str(error), window=detail["window"])

        return _window_response(request, membership, window)


# Execute outcomes other than paid / already_paid: (HTTP status, message).
# Only "failed" is a confirmed failure; "submitted", "unknown" and
# "in_progress" mean money may be moving and the payout must not be
# executed again until its attempt is resolved.
EXECUTE_OUTCOMES = {
    "failed": (
        status.HTTP_502_BAD_GATEWAY,
        "The payout provider confirmed the payment failed. Nothing was "
        "paid; it can be executed again.",
    ),
    "submitted": (
        status.HTTP_202_ACCEPTED,
        "The payout provider accepted the payment. It is not paid until "
        "settlement is confirmed.",
    ),
    "unknown": (
        status.HTTP_202_ACCEPTED,
        "The payment outcome could not be confirmed. It has not been "
        "marked failed and will not be retried until its status is "
        "resolved.",
    ),
    "in_progress": (
        status.HTTP_409_CONFLICT,
        "A payment attempt for this payout is still being confirmed. It "
        "will not be sent again until its status is resolved.",
    ),
}


class PayoutExecuteView(APIView):
    """
    Creator only. ExecutePayoutService enforces approval, funds and
    idempotency: repeating the request after success returns the same
    paid payout and never pays or debits again.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, circle_id, window):

        membership = authorize_creator(request, circle_id)

        payout = Payout.objects.filter(
            circle=membership.circle,
            payout_window=window,
            status__in=DECIDED_STATUSES,
        ).first()

        if payout is None:
            return _error("This payout window has no approved payout.")

        try:
            result = ExecutePayoutService.execute(payout)
        except ValueError as error:
            return _error(str(error))
        except PayoutProviderUnavailable as error:
            # Nothing was sent or recorded; the payout stays approved.
            return _window_response(
                request,
                membership,
                window,
                status.HTTP_503_SERVICE_UNAVAILABLE,
                result="unavailable",
                error=str(error),
            )

        outcome = result["status"]
        if outcome in EXECUTE_OUTCOMES:
            code, message = EXECUTE_OUTCOMES[outcome]
            return _window_response(
                request, membership, window, code,
                result=outcome, error=message,
            )

        return _window_response(
            request, membership, window, result=outcome,
        )
