"""Gemini embeddings over REST (batchEmbedContents).

Request shape verified against the official discovery document
(generativelanguage.googleapis.com/$discovery/rest?version=v1beta, rev 20261105):
`embedContentConfig.{taskType, outputDimensionality}` (the top-level fields are deprecated).

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
    def __init__(self, api_key: str, model: str, dim: int, client: httpx.AsyncClient) -> None:
        self._key = api_key
        self._model = model if model.startswith("models/") else f"models/{model}"
        self.dim = dim
        self._client = client

    async def _embed_batch(self, texts: list[str], task: TaskType) -> list[list[float]]:
        body = {
            "requests": [
                {
                    "model": self._model,
                    "content": {"parts": [{"text": t[:MAX_CHARS]}]},
                    "embedContentConfig": {"taskType": task, "outputDimensionality": self.dim},
                }
                for t in texts
            ]
        }
        url = f"{GEMINI_BASE}/{self._model}:batchEmbedContents"

        async def send() -> httpx.Response:
            # Key in a header, not the URL, so it never shows up in access logs.
            return await self._client.post(url, json=body, headers={"x-goog-api-key": self._key})

        resp = await request_with_retry(send, what="gemini embed")
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


def get_embedder(settings: Settings | None = None) -> GeminiEmbedder:
    s = settings or get_settings()
    if not s.gemini_api_key or not s.gemini_embedding_model:
        raise EmbeddingError("GEMINI_API_KEY and GEMINI_EMBEDDING_MODEL must be set")
    return GeminiEmbedder(
        s.gemini_api_key.get_secret_value(),
        s.gemini_embedding_model,
        s.embedding_dim,
        get_http_client(),
    )


def to_pgvector(v: list[float]) -> str:
    """pgvector text format, e.g. '[0.1,0.2]' (PostgREST passes it straight through)."""
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"
