"""Gemini embeddings over REST (batchEmbedContents).

Gotcha found by live testing (2026-11-06): the discovery document marks the top-level
`taskType` / `outputDimensionality` fields as deprecated in favour of `embedContentConfig`,
but the live API IGNORES `embedContentConfig` for gemini-embedding-001 and returns 3072 dims.
Only the top-level fields are honoured, so we send those. We also check the returned
dimension, so a silent API change fails loudly instead of corrupting the vector index.

Gemini only pre-normalizes full-size (3072-d) vectors, so we L2-normalize ourselves.
With unit vectors, cosine similarity == dot product, which keeps the math simple.
"""

import math
from typing import Literal, Protocol

import httpx

from app.core.config import Settings, get_settings
from app.core.http import get_http_client, request_with_retry

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
MAX_BATCH = 100  # batchEmbedContents rejects more than 100 requests per call
MAX_CHARS = 8000  # keep inputs well inside the model's token limit

TaskType = Literal["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"]


class EmbeddingError(Exception):
    pass


class Embedder(Protocol):
    dim: int

    async def embed(self, texts: list[str], task: TaskType) -> list[list[float]]: ...


def l2_normalize(v: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in v))
    if norm == 0:
        raise EmbeddingError("Received a zero vector from the embedding API")
    return [x / norm for x in v]


class GeminiEmbedder:
    def __init__(
        self,
        api_key: str,
        model: str,
        dim: int,
        client: httpx.AsyncClient,
        *,
        max_attempts: int = 4,
        max_delay: float = 8.0,
    ) -> None:
        self._key = api_key
        # Request-time calls fail fast; batch jobs (ingestion) pass patient values so a
        # free-tier per-minute quota (429) is waited out instead of crashing the run.
        self._max_attempts = max_attempts
        self._max_delay = max_delay
        self._model = model if model.startswith("models/") else f"models/{model}"
        self.dim = dim
        self._client = client

    async def _embed_batch(self, texts: list[str], task: TaskType) -> list[list[float]]:
        body = {
            "requests": [
                {
                    "model": self._model,
                    "content": {"parts": [{"text": t[:MAX_CHARS]}]},
                    "taskType": task,
                    "outputDimensionality": self.dim,
                }
                for t in texts
            ]
        }
        url = f"{GEMINI_BASE}/{self._model}:batchEmbedContents"

        async def send() -> httpx.Response:
            # Key in a header, not the URL, so it never shows up in access logs.
            return await self._client.post(url, json=body, headers={"x-goog-api-key": self._key})

        resp = await request_with_retry(
            send, what="gemini embed", max_attempts=self._max_attempts, max_delay=self._max_delay
        )
        if resp.status_code != 200:
            raise EmbeddingError(f"Gemini embeddings failed with status {resp.status_code}")
        embeddings = resp.json().get("embeddings", [])
        if len(embeddings) != len(texts):
            raise EmbeddingError("Embedding count mismatch")
        out: list[list[float]] = []
        for e in embeddings:
            values = e.get("values") or []
            if len(values) != self.dim:
                raise EmbeddingError(f"Expected {self.dim} dims, got {len(values)}")
            out.append(l2_normalize([float(x) for x in values]))
        return out

    async def embed(self, texts: list[str], task: TaskType) -> list[list[float]]:
        if any(not t.strip() for t in texts):
            raise EmbeddingError("Cannot embed empty text")
        out: list[list[float]] = []
        for i in range(0, len(texts), MAX_BATCH):
            out.extend(await self._embed_batch(texts[i : i + MAX_BATCH], task))
        return out


def get_embedder(settings: Settings | None = None, *, patient: bool = False) -> GeminiEmbedder:
    s = settings or get_settings()
    if not s.gemini_api_key or not s.gemini_embedding_model:
        raise EmbeddingError("GEMINI_API_KEY and GEMINI_EMBEDDING_MODEL must be set")
    return GeminiEmbedder(
        s.gemini_api_key.get_secret_value(),
        s.gemini_embedding_model,
        s.embedding_dim,
        get_http_client(),
        # patient: ~6 retries with waits up to 30 s, enough to outlast a per-minute quota.
        max_attempts=7 if patient else 4,
        max_delay=30.0 if patient else 8.0,
    )


def to_pgvector(v: list[float]) -> str:
    """pgvector text format, e.g. '[0.1,0.2]' (PostgREST passes it straight through)."""
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"
