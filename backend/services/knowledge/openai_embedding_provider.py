"""
OpenAI embeddings adapter - the ONLY module that imports the OpenAI SDK.

Verified against the OpenAI documentation on 2026-09-30 (openai Python
SDK 2.20 / 3.20): text-embedding-3-small returns 1536 dimensions by
default, accepts `dimensions` to shorten it, takes at most 8192 tokens
per input and returns vectors normalized to length 1 (cosine similarity).
Only KnowledgeChunk text and user questions are ever sent here, never
database rows.

Failures map onto EmbeddingProviderUnavailable / EmbeddingProviderError
with fixed messages: SDK exception text (which can include request
details) is never propagated.

No similarity threshold is shipped for this model: it has not been
measured with a live key. OSUSU_RAG_MIN_SIMILARITY must be set explicitly
from the opt-in retrieval evaluation (evaluation/README.md).
"""

import math

import openai

from services.knowledge.embedding_service import (
    EmbeddingInputError,
    EmbeddingProvider,
    EmbeddingProviderError,
    EmbeddingProviderUnavailable,
)


MAX_BATCH_SIZE = 128
# text-embedding-3 accepts 8192 tokens per input; ~3 characters per token
# keeps us well inside it for English text. Chunks are ~1200 characters.
MAX_INPUT_CHARACTERS = 24000

# Native output dimension of each supported model; `dimensions` may only
# shorten it.
SUPPORTED_MODELS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
}
MIN_DIMENSION = 16


class OpenAIEmbeddingProvider(EmbeddingProvider):

    name = "openai"
    embedding_version = "1"
    default_min_similarity = None  # unmeasured; see module docstring

    def __init__(
        self,
        *,
        api_key,
        model="text-embedding-3-small",
        dimension=1536,
        timeout=30.0,
        max_retries=2,
        client=None,
    ):
        if client is None and not api_key:
            raise EmbeddingProviderUnavailable(
                "The embedding provider is not configured."
            )

        if model not in SUPPORTED_MODELS:
            # `dimensions` is only supported by the text-embedding-3 family.
            raise EmbeddingProviderUnavailable(
                "Unsupported embedding model configuration."
            )

        if (
            not isinstance(dimension, int)
            or not MIN_DIMENSION <= dimension <= SUPPORTED_MODELS[model]
        ):
            raise EmbeddingProviderUnavailable(
                "Unsupported embedding dimension."
            )

        self.model = model
        self.dimension = dimension
        self._client = client or openai.OpenAI(
            api_key=api_key,
            timeout=timeout,
            max_retries=max_retries,
        )

    def __repr__(self):
        # Never include the client (it holds the API key).
        return f"OpenAIEmbeddingProvider(model={self.model!r}, dimension={self.dimension})"

    def embed_documents(self, texts):
        texts = list(texts)

        for text in texts:
            if not isinstance(text, str) or not text.strip():
                raise EmbeddingInputError("Cannot embed empty text.")
            if len(text) > MAX_INPUT_CHARACTERS:
                raise EmbeddingInputError("Text is too long to embed.")

        vectors = []
        for start in range(0, len(texts), MAX_BATCH_SIZE):
            batch = texts[start:start + MAX_BATCH_SIZE]
            vectors.extend(self._embed_batch(batch))

        return vectors

    def _embed_batch(self, batch):
        try:
            response = self._client.embeddings.create(
                input=batch,
                model=self.model,
                dimensions=self.dimension,
            )
        except (openai.AuthenticationError, openai.PermissionDeniedError):
            raise EmbeddingProviderUnavailable(
                "Embedding provider rejected the credentials."
            ) from None
        except openai.RateLimitError:
            raise EmbeddingProviderUnavailable(
                "Embedding provider is rate limiting requests."
            ) from None
        except openai.APITimeoutError:  # before APIConnectionError (subclass)
            raise EmbeddingProviderUnavailable(
                "Embedding provider timed out."
            ) from None
        except openai.APIConnectionError:
            raise EmbeddingProviderUnavailable(
                "Embedding provider is unreachable."
            ) from None
        except openai.APIStatusError as exc:
            if exc.status_code >= 500:
                raise EmbeddingProviderUnavailable(
                    "Embedding provider is unavailable."
                ) from None
            raise EmbeddingProviderError(
                "Embedding provider rejected the request."
            ) from None
        except openai.OpenAIError:
            # Response validation and any other SDK failure: fixed message.
            raise EmbeddingProviderUnavailable(
                "Embedding provider is unavailable."
            ) from None

        return self._validate(response, len(batch))

    def _validate(self, response, expected):
        try:
            items = sorted(response.data, key=lambda item: item.index)
            vectors = [list(item.embedding) for item in items]
        except (AttributeError, TypeError):
            raise EmbeddingProviderError(
                "Embedding provider returned an unexpected response."
            ) from None

        if len(vectors) != expected or [i.index for i in items] != list(range(expected)):
            raise EmbeddingProviderError(
                "Embedding provider returned the wrong number of vectors."
            )

        for vector in vectors:
            if len(vector) != self.dimension or not all(
                isinstance(v, (int, float)) and math.isfinite(v) for v in vector
            ):
                raise EmbeddingProviderError(
                    "Embedding provider returned an invalid vector."
                )

        return [[float(v) for v in vector] for vector in vectors]
