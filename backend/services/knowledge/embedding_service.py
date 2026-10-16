"""
Embedding provider abstraction.

Every provider declares an identity - (name, model, dimension,
embedding_version) - that is stored with each vector. Vectors are only
ever compared with vectors of the SAME identity, so switching model or
dimension makes existing vectors stale instead of silently mixing them.

Providers:
- HashingEmbeddingProvider: deterministic LEXICAL stand-in for
  development and tests. Matches shared words, not meaning ("payout"
  will not match "disbursement"). Not a semantic embedding.
- OpenAIEmbeddingProvider (services/knowledge/openai_embedding_provider.py):
  the production embedding model. Only that module imports the SDK.

Selection: settings.OSUSU_EMBEDDING_PROVIDER ("hashing" default, "openai").
"""

import hashlib
import math
import re
from abc import ABC, abstractmethod

from django.conf import settings


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class EmbeddingError(Exception):
    """Base class. Messages are fixed strings; never provider output."""


class EmbeddingProviderUnavailable(EmbeddingError):
    """Not configured, unreachable, unauthorized, throttled or timed out."""


class EmbeddingProviderError(EmbeddingError):
    """The provider answered with an error or an unusable response."""


class EmbeddingInputError(EmbeddingError, ValueError):
    """The text cannot be embedded (empty, not a string, too long)."""


class EmbeddingProvider(ABC):

    name: str
    model: str
    dimension: int
    embedding_version: str

    # Minimum cosine similarity for a retrieved chunk to count as evidence.
    # None means "never measured for this provider": retrieval then
    # requires OSUSU_RAG_MIN_SIMILARITY to be set explicitly.
    default_min_similarity: float | None = None

    @property
    def identity(self):
        return (self.name, self.model, self.dimension, self.embedding_version)

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """One vector of length `dimension` per text, in order."""

    def embed_text(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def embed_query(self, text: str) -> list[float]:
        # Asymmetric models embed queries differently; override if so.
        return self.embed_text(text)


# Function words carry no topical signal but dominate lexical overlap:
# in v1, "What is the capital of France?" outscored relevant questions.
STOPWORDS = frozenset(
    "a an and are as at be been by did do does for from had has have how "
    "i if in into is it its me my no not of on or our so than that the "
    "their them then there these they this to was we were what when where "
    "which who why will with you your".split()
)


class HashingEmbeddingProvider(EmbeddingProvider):
    """
    Signed feature hashing of lowercase content-word unigrams and bigrams
    (stop-words removed), L2-normalized. Deterministic across processes
    and machines (SHA-256, not Python's hash()). Lexical only; see module
    docstring.

    v2 (Sprint 25): stop-word removal + 4096 buckets. Measured on the
    retrieval evaluation set (knowledge/tests/test_retrieval_evaluation.py)
    unrelated questions fell from 0.267 (v1) to 0.0, with collision noise
    <= 0.015 and relevant top hits >= 0.044.
    """

    model = "hashing-lexical-v2"
    embedding_version = "2"

    # Chosen in the observed gap between noise (<= 0.015) and relevant top
    # hits (>= 0.044) on the evaluation set. A development baseline, not a
    # validated benchmark; the margin is narrow.
    default_min_similarity = 0.03

    def __init__(self, dimension=4096):
        if dimension < 16:
            raise ValueError("dimension must be at least 16.")
        self.dimension = dimension
        self.name = f"hashing-lexical-v2-d{dimension}"

    def embed_documents(self, texts):
        return [self._embed(text) for text in texts]

    def _embed(self, text):
        tokens = [
            t for t in TOKEN_PATTERN.findall(text.lower())
            if t not in STOPWORDS
        ]
        features = tokens + [
            f"{a} {b}" for a, b in zip(tokens, tokens[1:])
        ]

        vector = [0.0] * self.dimension
        for feature in features:
            digest = hashlib.sha256(feature.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[bucket] += sign

        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            return vector

        return [v / norm for v in vector]


def get_default_embedding_provider():
    """The configured provider. Never falls back to another provider."""
    name = (getattr(settings, "OSUSU_EMBEDDING_PROVIDER", "hashing") or "").strip()

    if name == "hashing":
        return HashingEmbeddingProvider()

    if name == "openai":
        # Imported here so the SDK is only loaded when selected.
        from services.knowledge.openai_embedding_provider import (
            OpenAIEmbeddingProvider,
        )

        return OpenAIEmbeddingProvider(
            api_key=getattr(settings, "OSUSU_EMBEDDING_API_KEY", ""),
            model=getattr(
                settings, "OSUSU_EMBEDDING_MODEL", "text-embedding-3-small",
            ),
            dimension=int(getattr(settings, "OSUSU_EMBEDDING_DIMENSIONS", 1536)),
        )

    raise EmbeddingProviderUnavailable(
        "The configured embedding provider is not available."
    )


def get_min_similarity(provider):
    """
    OSUSU_RAG_MIN_SIMILARITY if set, else the provider's measured default.
    Fails closed when neither exists (an unmeasured production model).
    """
    configured = getattr(settings, "OSUSU_RAG_MIN_SIMILARITY", "")

    if configured not in (None, ""):
        value = float(configured)
    elif provider.default_min_similarity is not None:
        value = provider.default_min_similarity
    else:
        raise EmbeddingProviderUnavailable(
            "No similarity threshold is configured for this embedding model."
        )

    if not -1.0 <= value < 1.0:
        raise EmbeddingProviderUnavailable("Invalid similarity threshold.")

    return value
