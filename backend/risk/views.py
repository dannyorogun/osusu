import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from circles.access import (
    authorize_member,
    get_active_target_member,
)

from services.ml.model_registry import (
    ModelArtifactError,
    ModelArtifactNotFound,
)
from services.ml.predict_default_risk import DefaultRiskPredictor

from .serializers import DefaultRiskPredictionSerializer


logger = logging.getLogger(__name__)


class MemberDefaultRiskView(APIView):
    """
    GET /api/risk/circles/<circle_id>/members/<member_id>/default-risk/

    Predicted probability that the member defaults during the next
    prediction horizon (positive class: DEFAULTED).

    This prediction is informational only and does not approve or reject
    payouts, move money, alter obligations, or override governance. The
    endpoint is strictly read-only.

    Authentication: JWT required (401 otherwise).

    Authorization: the requester must be an ACTIVE member of the circle,
    and the target must be an ACTIVE member of the same circle.
    - 404 if the circle does not exist or the requester has no membership
      in it (does not reveal whether the circle exists);
    - 403 if the requester's membership is not active;
    - 404 if the target user does not exist or is not an active member of
      this circle (does not reveal whether the user exists).

    Privacy: the response carries the probability and model metadata
    only. The model's input features (some of which summarize the member's
    history across other circles) are used internally and never returned.

    Model availability: 503 with code "model_unavailable" when no trained
    model exists, or "model_incompatible" when the stored model does not
    match the current feature definition. No prediction is fabricated and
    nothing is trained or substituted automatically.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, circle_id, member_id):

        requester_membership = authorize_member(request, circle_id)

        target_membership = get_active_target_member(
            circle_id,
            member_id,
        )

        try:
            prediction = DefaultRiskPredictor.predict(
                circle=requester_membership.circle,
                member=target_membership.user,
            )

        except ModelArtifactNotFound:
            logger.warning("Default-risk model artifact is missing.")

            return Response(
                {
                    "detail": (
                        "Default-risk prediction is unavailable: "
                        "no trained model exists."
                    ),
                    "code": "model_unavailable",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        except ModelArtifactError:
            logger.exception(
                "Default-risk model artifact is incompatible."
            )

            return Response(
                {
                    "detail": (
                        "Default-risk prediction is unavailable: the "
                        "trained model is incompatible and must be "
                        "retrained."
                    ),
                    "code": "model_incompatible",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            DefaultRiskPredictionSerializer(prediction).data,
            status=status.HTTP_200_OK,
        )
