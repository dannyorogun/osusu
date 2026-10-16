import logging
import uuid

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from circles.access import authorize_member

from services.circles.circle_access_service import (
    CircleAccessForbidden,
    CircleNotFound,
)
from services.llm.explanation_service import (
    ExplanationService,
    QuestionValidationError,
    UngroundedAnswerError,
)
from services.llm.rate_limiter import (
    AssistantRateLimiter,
    RateLimiterUnavailable,
    RateLimitExceeded,
)
from services.llm.provider import (
    LLMAuthenticationError,
    LLMMalformedResponse,
    LLMProviderError,
    LLMProviderUnavailable,
    LLMRateLimited,
    LLMTimeout,
)

from .serializers import AssistantAnswerSerializer, AssistantQuestionSerializer


logger = logging.getLogger(__name__)

# (status code, public code, public message). Messages are fixed strings:
# provider exception text is never returned to clients.
_ERRORS = {
    LLMProviderUnavailable: (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "assistant_unavailable",
        "The explanation assistant is currently unavailable.",
    ),
    LLMAuthenticationError: (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "assistant_unavailable",
        "The explanation assistant is currently unavailable.",
    ),
    LLMTimeout: (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "assistant_timeout",
        "The explanation assistant did not respond in time.",
    ),
    LLMRateLimited: (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "assistant_busy",
        "The explanation assistant is busy. Please try again later.",
    ),
    LLMMalformedResponse: (
        status.HTTP_502_BAD_GATEWAY,
        "assistant_invalid_output",
        "The explanation assistant returned an invalid response.",
    ),
    UngroundedAnswerError: (
        status.HTTP_502_BAD_GATEWAY,
        "assistant_unverified_answer",
        "The explanation assistant produced an answer that could not be "
        "verified against Osusu records.",
    ),
    LLMProviderError: (
        status.HTTP_502_BAD_GATEWAY,
        "assistant_error",
        "The explanation assistant failed to answer.",
    ),
}


class CircleAssistantView(APIView):
    """
    POST /api/circles/<circle_id>/assistant/  {"question": "..."}

    Explains this circle's Osusu records. Informational only: it cannot
    change payments, payouts, contributions, governance or any other
    state, and the model has no tools or database access.

    Auth: JWT (401). Circle access is identical to other circle endpoints:
    404 if the circle does not exist or the user was never a member, 403
    for invited/left/removed members. The URL circle is authoritative;
    the body may contain only "question" (400 otherwise).

    Errors: 400 invalid question; 503 assistant unavailable (including
    when disabled by configuration); 502 invalid or unverifiable model
    output. No fabricated answer is ever returned on failure.

    Rate limit: OSUSU_ASSISTANT_RATE_LIMIT requests per user per
    OSUSU_ASSISTANT_RATE_WINDOW_SECONDS (429 + Retry-After). Shared across
    instances with OSUSU_RATE_LIMIT_REDIS_URL; with the paid provider and
    no Redis (or Redis down) requests are refused with 503 (check W001).
    The paid provider is served only when every production gate passes
    (services/llm/readiness.py, check W002); otherwise 503.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, circle_id):
        request_id = str(uuid.uuid4())

        authorize_member(request, circle_id)

        # Metered after authorization (outsiders cannot consume or probe a
        # member's budget) and before validation (malformed requests count).
        try:
            AssistantRateLimiter().hit(request.user.pk)
        except RateLimitExceeded as exc:
            return Response(
                {
                    "detail": "Too many assistant requests. Please try again later.",
                    "code": "assistant_rate_limited",
                    "request_id": request_id,
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": str(exc.retry_after)},
            )
        except RateLimiterUnavailable:
            logger.error(
                "assistant rate limiter unavailable",
                extra={"request_id": request_id},
            )
            return Response(
                {
                    "detail": "The explanation assistant is currently unavailable.",
                    "code": "assistant_unavailable",
                    "request_id": request_id,
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        serializer = AssistantQuestionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = ExplanationService.answer_question(
                user=request.user,
                circle_id=circle_id,
                question=serializer.validated_data["question"],
                request_id=request_id,
            )

        except QuestionValidationError as exc:
            return Response(
                {"detail": str(exc), "request_id": request_id},
                status=status.HTTP_400_BAD_REQUEST,
            )

        except CircleNotFound:
            # Membership changed between the view check and the service.
            return Response(
                {"detail": "Circle not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        except CircleAccessForbidden:
            return Response(
                {"detail": "Only active circle members can access this circle."},
                status=status.HTTP_403_FORBIDDEN,
            )

        except tuple(_ERRORS) as exc:
            http_status, code, message = next(
                v for k, v in _ERRORS.items() if isinstance(exc, k)
            )
            logger.warning(
                "assistant request failed",
                extra={
                    "request_id": request_id,
                    "circle_id": str(circle_id),
                    "error": type(exc).__name__,
                },
            )
            return Response(
                {"detail": message, "code": code, "request_id": request_id},
                status=http_status,
            )

        return Response(
            AssistantAnswerSerializer(result).data,
            status=status.HTTP_200_OK,
        )
