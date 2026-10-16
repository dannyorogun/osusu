"""
Grounded, read-only explanations of Osusu data.

    user + circle_id + question
      -> validate question
      -> CircleAccessService authorization
      -> LLM provider resolved (disabled / not production-ready fails
         here, BEFORE any paid embedding call)
      -> KnowledgeAccessService (authorization again, then circle-scoped
         retrieval)                          [the LLM never chooses data]
      -> no evidence: controlled "I don't know" (the LLM is NOT called)
      -> prompt with retrieved evidence only
      -> LLMProvider (no tools, no database, no write access)
      -> strict JSON parsing
      -> citation validation (only sources retrieved for THIS request)
      -> numeric grounding (amounts, percentages, dates must appear in
         the cited sources, outside user-authored free text)
      -> structured result

Every validation failure FAILS CLOSED: no unverified answer is returned.
"""

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from services.circles.circle_access_service import CircleAccessService
from services.knowledge.access_service import KnowledgeAccessService
from services.knowledge.embedding_service import EmbeddingError
from services.knowledge.retriever import KnowledgeRetriever
from services.knowledge.schema import KNOWLEDGE_SCHEMA_VERSION, USER_TEXT_PREFIX
from services.llm.config import get_llm_provider
from services.llm.prompts import (
    INSUFFICIENT_CONTEXT_ANSWER,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_user_prompt,
)
from services.llm.provider import (
    ContextItem,
    LLMError,
    LLMMalformedResponse,
    LLMProviderUnavailable,
)


logger = logging.getLogger(__name__)

MAX_QUESTION_LENGTH = 1000
MAX_ANSWER_LENGTH = 4000
RETRIEVAL_TOP_K = 5

STATUS_ANSWERED = "answered"
STATUS_INSUFFICIENT = "insufficient_context"

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Narrow, explainable numeric grounding: money, percentages, ISO dates.
_MONEY = re.compile(r"£\s?(\d[\d,]*(?:\.\d+)?)|\b(\d[\d,]*\.\d{2})\b")
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s?%")
_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


class QuestionValidationError(ValueError):
    pass


class RetrievalUnavailable(LLMProviderUnavailable):
    """Embedding/retrieval failed or is misconfigured (maps to 503)."""


class UngroundedAnswerError(LLMError):
    """The model's answer could not be verified against the evidence."""


@dataclass(frozen=True)
class ExplanationCitation:
    document_id: str
    document_type: str
    document_version: int
    schema_version: str
    chunk_id: str
    title: str


@dataclass(frozen=True)
class ExplanationResult:
    request_id: str
    status: str
    answer: str
    citations: tuple = ()
    retrieval_count: int = 0
    prompt_version: str = PROMPT_VERSION
    knowledge_schema_version: str = KNOWLEDGE_SCHEMA_VERSION
    provider: str | None = None
    model: str | None = None


@dataclass
class _Evidence:
    item: ContextItem
    chunk: object  # RetrievedChunk
    amounts: set = field(default_factory=set)
    percents: set = field(default_factory=set)
    dates: set = field(default_factory=set)


def normalize_question(question):
    if not isinstance(question, str):
        raise QuestionValidationError("question must be a string.")

    if _CONTROL_CHARS.search(question):
        raise QuestionValidationError("question contains invalid characters.")

    normalized = " ".join(question.split())

    if not normalized:
        raise QuestionValidationError("question must not be empty.")

    if len(normalized) > MAX_QUESTION_LENGTH:
        raise QuestionValidationError(
            f"question must be at most {MAX_QUESTION_LENGTH} characters."
        )

    return normalized


def _decimal(text):
    try:
        return Decimal(text.replace(",", "")).normalize()
    except InvalidOperation:
        return None


def supported_figures(content):
    """
    Figures a source can vouch for: everything except user-authored free
    text (a circle description could otherwise "ground" an invented
    balance via prompt injection).
    """
    return extract_figures("\n".join(
        line for line in content.split("\n")
        if not line.lstrip().startswith(USER_TEXT_PREFIX)
    ))


def extract_figures(text):
    amounts = {
        _decimal(a or b) for a, b in _MONEY.findall(text)
    } - {None}
    percents = {_decimal(p) for p in _PERCENT.findall(text)} - {None}
    dates = set(_DATE.findall(text))
    return amounts, percents, dates


class ExplanationService:

    @classmethod
    def answer_question(
        cls,
        *,
        user,
        circle_id,
        question,
        provider=None,
        retriever=None,
        request_id=None,
    ) -> ExplanationResult:

        request_id = request_id or str(uuid.uuid4())
        started = time.monotonic()
        question = normalize_question(question)

        # 1. Authorization FIRST (raises CircleNotFound /
        #    CircleAccessForbidden), before any provider or threshold
        #    configuration is touched, so misconfiguration can never be
        #    observed by an unauthorized user.
        CircleAccessService.require_active_member(
            circle_id=circle_id,
            user=user,
        )

        # 2. The provider is resolved before retrieval so a disabled or
        #    not-production-ready assistant never spends an embedding
        #    call. Resolving it does not call the model.
        try:
            provider = provider or get_llm_provider()
        except LLMError as exc:
            cls._log(
                started, circle_id, {},
                request_id=request_id,
                status=f"error:{type(exc).__name__}",
            )
            raise

        # 3. Circle-scoped retrieval with the configured embedding model
        #    and similarity threshold. Any embedding failure is a service
        #    outage, never a reason to fall back to another provider.
        meta = {}
        try:
            retriever = retriever or KnowledgeRetriever()
            meta = {
                "embedding_provider": retriever.provider.name,
                "embedding_model": retriever.provider.model,
                "min_similarity": retriever.min_similarity,
            }
            chunks = KnowledgeAccessService.retrieve_for_user(
                user=user,
                circle_id=circle_id,
                query=question,
                top_k=RETRIEVAL_TOP_K,
                retriever=retriever,
            )
        except EmbeddingError as exc:
            cls._log(
                started, circle_id, meta,
                request_id=request_id,
                status=f"error:{type(exc).__name__}",
            )
            raise RetrievalUnavailable(
                "Knowledge retrieval is unavailable."
            ) from exc

        if not chunks:
            return cls._finish(
                started,
                circle_id,
                meta,
                ExplanationResult(
                    request_id=request_id,
                    status=STATUS_INSUFFICIENT,
                    answer=INSUFFICIENT_CONTEXT_ANSWER,
                ),
            )

        evidence = {}
        for index, chunk in enumerate(chunks, start=1):
            item = ContextItem(
                source_id=f"S{index}",
                title=chunk.title,
                document_type=chunk.document_type,
                document_version=chunk.citation["document_version"],
                content=chunk.content,
            )
            amounts, percents, dates = supported_figures(chunk.content)
            evidence[item.source_id] = _Evidence(
                item=item,
                chunk=chunk,
                amounts=amounts,
                percents=percents,
                dates=dates,
            )

        context = tuple(e.item for e in evidence.values())

        try:
            raw = provider.generate(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=build_user_prompt(
                    question=question,
                    context=context,
                ),
                context=context,
            )
            status, answer, cited = cls._parse(raw.text)
            citations = cls._validate(status, answer, cited, evidence)

        except LLMError as exc:
            cls._log(
                started,
                circle_id,
                meta,
                request_id=request_id,
                retrieval_count=len(chunks),
                provider=getattr(provider, "name", None),
                model=getattr(provider, "model", None),
                status=f"error:{type(exc).__name__}",
            )
            raise

        if status == STATUS_INSUFFICIENT:
            answer = INSUFFICIENT_CONTEXT_ANSWER

        return cls._finish(
            started,
            circle_id,
            meta,
            ExplanationResult(
                request_id=request_id,
                status=status,
                answer=answer,
                citations=citations,
                retrieval_count=len(chunks),
                provider=raw.provider,
                model=raw.model,
            ),
        )

    # Output handling

    @staticmethod
    def _parse(text):
        try:
            data = json.loads(text)
        except (TypeError, ValueError) as exc:
            raise LLMMalformedResponse("Model output is not JSON.") from exc

        if not isinstance(data, dict):
            raise LLMMalformedResponse("Model output must be a JSON object.")

        status = data.get("status")
        answer = data.get("answer")
        citations = data.get("citations")

        if status not in (STATUS_ANSWERED, STATUS_INSUFFICIENT):
            raise LLMMalformedResponse("Model output has an invalid status.")

        if not isinstance(answer, str) or not answer.strip():
            raise LLMMalformedResponse("Model output has no answer text.")

        if len(answer) > MAX_ANSWER_LENGTH:
            raise LLMMalformedResponse("Model answer is too long.")

        if not isinstance(citations, list) or not all(
            isinstance(c, str) for c in citations
        ):
            raise LLMMalformedResponse("Model citations must be a list of ids.")

        return status, answer.strip(), citations

    @staticmethod
    def _validate(status, answer, cited, evidence):
        if status == STATUS_INSUFFICIENT:
            return ()

        unknown = [c for c in cited if c not in evidence]
        if unknown:
            raise UngroundedAnswerError(
                "The answer cited sources that were not retrieved."
            )

        cited_ids = list(dict.fromkeys(cited))  # de-duplicate, keep order
        if not cited_ids:
            raise UngroundedAnswerError("The answer cited no sources.")

        amounts, percents, dates = extract_figures(answer)
        supported_amounts = set().union(
            *(evidence[c].amounts for c in cited_ids)
        )
        supported_percents = set().union(
            *(evidence[c].percents for c in cited_ids)
        )
        supported_dates = set().union(*(evidence[c].dates for c in cited_ids))

        if (
            not amounts <= supported_amounts
            or not percents <= supported_percents
            or not dates <= supported_dates
        ):
            raise UngroundedAnswerError(
                "The answer contains figures that are not in its cited "
                "sources."
            )

        return tuple(
            ExplanationCitation(
                document_id=evidence[c].chunk.document_id,
                document_type=evidence[c].chunk.document_type,
                document_version=evidence[c].chunk.citation[
                    "document_version"
                ],
                schema_version=evidence[c].chunk.citation["schema_version"],
                chunk_id=evidence[c].chunk.chunk_id,
                title=evidence[c].chunk.title,
            )
            for c in cited_ids
        )

    # Observability

    @classmethod
    def _finish(cls, started, circle_id, meta, result):
        cls._log(
            started,
            circle_id,
            meta,
            request_id=result.request_id,
            retrieval_count=result.retrieval_count,
            provider=result.provider,
            model=result.model,
            status=result.status,
        )
        return result

    @staticmethod
    def _log(started, circle_id, meta, **fields):
        # Never log the question, prompt, context, answer or credentials.
        logger.info(
            "explanation",
            extra={
                **meta,
                "circle_id": str(circle_id),
                "prompt_version": PROMPT_VERSION,
                "knowledge_schema_version": KNOWLEDGE_SCHEMA_VERSION,
                "latency_ms": round((time.monotonic() - started) * 1000),
                **fields,
            },
        )
