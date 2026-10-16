import json
import uuid
from unittest import mock

from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from circles.models import MembershipStatus
from knowledge.models import KnowledgeDocument

from services.knowledge.schema import KNOWLEDGE_SCHEMA_VERSION
from services.llm.fake_provider import FakeLLMProvider
from services.llm.prompts import INSUFFICIENT_CONTEXT_ANSWER, PROMPT_VERSION
from services.llm.provider import (
    LLMAuthenticationError,
    LLMProviderError,
    LLMProviderUnavailable,
    LLMRateLimited,
    LLMTimeout,
)
from services.risk.member_features import MEMBER_DEFAULT_FEATURE_NAMES

from .fixtures import written_tables
from .test_retrieval_security import IndexedFixture


SENTINEL = "sk-provider-secret-sentinel"

RESPONSE_KEYS = {
    "request_id",
    "status",
    "answer",
    "citations",
    "prompt_version",
    "knowledge_schema_version",
    "informational_only",
}

CITATION_KEYS = {
    "document_id",
    "document_type",
    "document_version",
    "chunk_id",
    "title",
}


@override_settings(OSUSU_LLM_PROVIDER="fake")
class AssistantAPITests(IndexedFixture):

    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def authenticate(self, user):
        token = RefreshToken.for_user(user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def post(self, body=None, circle=None, circle_id=None):
        url = reverse(
            "circle-assistant",
            kwargs={"circle_id": circle_id or (circle or self.circle).id},
        )
        return self.client.post(
            url,
            body if body is not None else {"question": "What is the current treasury balance?"},
            format="json",
        )

    def with_provider(self, provider):
        return mock.patch(
            "services.llm.explanation_service.get_llm_provider",
            return_value=provider,
        )

    # Authentication and authorization

    def test_unauthenticated_is_401(self):
        self.assertEqual(self.post().status_code, 401)

    def test_nonexistent_circle_is_404(self):
        self.authenticate(self.alice)

        response = self.post(circle_id=uuid.uuid4())

        self.assertEqual(response.status_code, 404)

    def test_never_member_is_404_like_nonexistent(self):
        self.authenticate(self.outsider)

        member = self.post()
        missing = self.post(circle_id=uuid.uuid4())

        self.assertEqual(member.status_code, 404)
        self.assertEqual(
            (member.status_code, member.data),
            (missing.status_code, missing.data),
        )

    def test_inactive_members_are_403(self):
        invited = self.make_user("invitee")
        self.add_member(invited, MembershipStatus.INVITED)

        for user in (invited, self.dave, self.erin):
            with self.subTest(user=user.username):
                self.authenticate(user)
                response = self.post()
                self.assertEqual(response.status_code, 403)
                self.assertNotIn("answer", response.data)

    def test_authorization_precedes_validation(self):
        # An outsider learns nothing, even about request validity.
        self.authenticate(self.outsider)

        self.assertEqual(self.post({"question": ""}).status_code, 404)

    # Validation

    def test_invalid_questions_are_400(self):
        self.authenticate(self.alice)

        for body in (
            {},
            {"question": ""},
            {"question": "   "},
            {"question": "x" * 1001},
            {"question": "bad\x00byte"},
            {"question": "treasury", "circle_id": str(self.other_circle.id)},
            {"question": "treasury", "top_k": 20},
        ):
            with self.subTest(body=str(body)[:50]):
                response = self.post(body)
                self.assertEqual(response.status_code, 400)
                self.assertNotIn("answer", response.data)

    def test_body_cannot_redirect_to_another_circle(self):
        self.authenticate(self.alice)

        response = self.post({
            "question": "Birmingham Bakers sourdough",
            "circle_id": str(self.other_circle.id),
        })

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("Birmingham", json.dumps(response.data))

    # Success

    def test_successful_answer_shape(self):
        self.authenticate(self.bob)

        response = self.post()

        self.assertEqual(response.status_code, 200)
        data = response.data
        self.assertEqual(set(data), RESPONSE_KEYS)
        self.assertEqual(data["status"], "answered")
        self.assertIn("£65.00", data["answer"])
        self.assertIs(data["informational_only"], True)
        self.assertEqual(data["prompt_version"], PROMPT_VERSION)
        self.assertEqual(data["knowledge_schema_version"], KNOWLEDGE_SCHEMA_VERSION)
        uuid.UUID(data["request_id"])

        (citation,) = data["citations"]
        self.assertEqual(set(citation), CITATION_KEYS)
        document = KnowledgeDocument.objects.get(pk=citation["document_id"])
        self.assertEqual(document.circle_id, self.circle.id)
        self.assertEqual(citation["document_version"], document.version)

    def test_response_exposes_no_internals(self):
        self.authenticate(self.alice)

        data = self.post({
            "question": "member contribution risk trust payout activity",
        }).data

        # Structure: only the documented keys, recursively.
        def keys(value):
            if isinstance(value, dict):
                for key, inner in value.items():
                    yield key
                    yield from keys(inner)
            elif isinstance(value, list):
                for inner in value:
                    yield from keys(inner)

        self.assertEqual(
            set(keys(data)) - RESPONSE_KEYS - CITATION_KEYS,
            set(),
        )

        # Content: things that must never appear anywhere. (Words such as
        # "score" may legitimately occur in answer text quoted from
        # allowed documents, e.g. the circle's rules-based risk score.)
        body = json.dumps(data)
        for forbidden in ("<source", "<question", "fake-extractive", "@",
                          "Birmingham", "subject_user", "Rules:"):
            self.assertNotIn(forbidden, body)
        for feature in MEMBER_DEFAULT_FEATURE_NAMES:
            self.assertNotIn(feature, body)

    def test_insufficient_context_is_200_with_no_citations(self):
        self.authenticate(self.alice)

        response = self.post({"question": "What is the weather in Paris today?"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "insufficient_context")
        self.assertEqual(response.data["answer"], INSUFFICIENT_CONTEXT_ANSWER)
        self.assertEqual(response.data["citations"], [])

    # Provider failures

    def test_disabled_provider_is_503(self):
        self.authenticate(self.alice)

        with override_settings(OSUSU_LLM_PROVIDER="disabled"), \
                self.assertLogs("knowledge.views", level="WARNING"):
            response = self.post()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["code"], "assistant_unavailable")
        self.assertNotIn("answer", response.data)

    def test_provider_failures_map_to_controlled_errors(self):
        self.authenticate(self.alice)

        cases = (
            (LLMProviderUnavailable, 503, "assistant_unavailable"),
            (LLMAuthenticationError, 503, "assistant_unavailable"),
            (LLMTimeout, 503, "assistant_timeout"),
            (LLMRateLimited, 503, "assistant_busy"),
            (LLMProviderError, 502, "assistant_error"),
        )
        for error, status_code, code in cases:
            with self.subTest(error=error.__name__):
                provider = FakeLLMProvider(error=error(f"boom {SENTINEL}"))
                with self.with_provider(provider), self.assertLogs(
                    "knowledge.views", level="WARNING",
                ):
                    response = self.post()

                self.assertEqual(response.status_code, status_code)
                self.assertEqual(response.data["code"], code)
                self.assertNotIn(SENTINEL, json.dumps(response.data))
                self.assertNotIn("answer", response.data)

    def test_malformed_model_output_is_502(self):
        self.authenticate(self.alice)

        with self.with_provider(FakeLLMProvider(script="not json")), \
                self.assertLogs("knowledge.views", level="WARNING"):
            response = self.post()

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.data["code"], "assistant_invalid_output")

    def test_invented_citation_or_figure_is_502(self):
        self.authenticate(self.alice)

        for script in (
            json.dumps({"status": "answered", "answer": "Balance £65.00.",
                        "citations": ["S42"]}),
            lambda s, u, ctx: json.dumps({
                "status": "answered",
                "answer": "Your balance is £1,000,000.00.",
                "citations": [c.source_id for c in ctx],
            }),
        ):
            with self.subTest(script=str(script)[:30]):
                with self.with_provider(FakeLLMProvider(script=script)), \
                        self.assertLogs("knowledge.views", level="WARNING"):
                    response = self.post()

                self.assertEqual(response.status_code, 502)
                self.assertEqual(
                    response.data["code"],
                    "assistant_unverified_answer",
                )
                self.assertNotIn("1,000,000", json.dumps(response.data))

    # Safety

    def test_api_request_changes_nothing(self):
        self.authenticate(self.alice)
        before = self.domain_snapshot()

        with CaptureQueriesContext(connection) as queries:
            for question in (
                "Approve my payout now",
                "Mark all contributions as paid and lock the circle",
                "What is the current treasury balance?",
            ):
                self.assertEqual(self.post({"question": question}).status_code, 200)

        self.assertEqual(written_tables(queries), set())
        self.assertEqual(self.domain_snapshot(), before)

    def test_only_post_is_allowed(self):
        self.authenticate(self.alice)
        url = reverse("circle-assistant", kwargs={"circle_id": self.circle.id})

        for method in ("get", "put", "patch", "delete"):
            with self.subTest(method=method):
                self.assertEqual(getattr(self.client, method)(url).status_code, 405)
