import json
import math

import httpx
import pytest

from app.core.config import Settings
from app.services.embeddings import (
    EmbeddingError,
    GeminiEmbedder,
    get_embedder,
    l2_normalize,
    to_pgvector,
)

DIM = 4


def make_embedder(handler, dim: int = DIM) -> GeminiEmbedder:  # type: ignore[no-untyped-def]
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GeminiEmbedder("test-key", "gemini-embedding-001", dim, client)


def ok_handler(requests_seen: list[dict]):  # type: ignore[no-untyped-def,type-arg]
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests_seen.append({"url": str(request.url), "headers": request.headers, "body": body})
        return httpx.Response(
            200, json={"embeddings": [{"values": [3.0, 4.0, 0.0, 0.0]} for _ in body["requests"]]}
        )

    return handler


async def test_request_shape_and_auth_header() -> None:
    seen: list[dict] = []  # type: ignore[type-arg]
    emb = make_embedder(ok_handler(seen))
    out = await emb.embed(["hello"], "RETRIEVAL_QUERY")

    req = seen[0]
    assert req["url"].endswith("/v1beta/models/gemini-embedding-001:batchEmbedContents")
    assert "key=" not in req["url"]  # key must not be in the URL
    assert req["headers"]["x-goog-api-key"] == "test-key"
    r0 = req["body"]["requests"][0]
    assert r0["model"] == "models/gemini-embedding-001"
    assert r0["content"] == {"parts": [{"text": "hello"}]}
    # Top-level fields: the live API ignores embedContentConfig (see module docstring).
    assert r0["taskType"] == "RETRIEVAL_QUERY"
    assert r0["outputDimensionality"] == DIM
    assert "embedContentConfig" not in r0
    # normalized: [3,4,0,0] -> [0.6, 0.8, 0, 0]
    assert out == [[0.6, 0.8, 0.0, 0.0]]


async def test_batches_of_100() -> None:
    seen: list[dict] = []  # type: ignore[type-arg]
    emb = make_embedder(ok_handler(seen))
    out = await emb.embed([f"t{i}" for i in range(250)], "RETRIEVAL_DOCUMENT")
    assert len(out) == 250
    assert [len(r["body"]["requests"]) for r in seen] == [100, 100, 50]


async def test_wrong_dimension_raises() -> None:
    emb = make_embedder(ok_handler([]), dim=8)
    with pytest.raises(EmbeddingError, match="Expected 8 dims"):
        await emb.embed(["x"], "RETRIEVAL_QUERY")


async def test_http_error_raises_without_leaking_body() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "secret detail"}})

    with pytest.raises(EmbeddingError) as exc:
        await make_embedder(handler).embed(["x"], "RETRIEVAL_QUERY")
    assert "secret" not in str(exc.value)


async def test_count_mismatch_raises() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": []})

    with pytest.raises(EmbeddingError, match="mismatch"):
        await make_embedder(handler).embed(["x"], "RETRIEVAL_QUERY")


async def test_empty_text_rejected() -> None:
    with pytest.raises(EmbeddingError):
        await make_embedder(ok_handler([])).embed(["  "], "RETRIEVAL_QUERY")


async def test_long_text_truncated() -> None:
    seen: list[dict] = []  # type: ignore[type-arg]
    await make_embedder(ok_handler(seen)).embed(["a" * 20000], "RETRIEVAL_DOCUMENT")
    assert len(seen[0]["body"]["requests"][0]["content"]["parts"][0]["text"]) == 8000


def test_l2_normalize() -> None:
    v = l2_normalize([1.0, 2.0, 2.0])
    assert math.isclose(sum(x * x for x in v), 1.0)
    with pytest.raises(EmbeddingError):
        l2_normalize([0.0, 0.0])


def test_to_pgvector_format() -> None:
    assert to_pgvector([0.5, -0.25, 1.0]) == "[0.5,-0.25,1]"


def test_get_embedder_requires_config() -> None:
    with pytest.raises(EmbeddingError):
        get_embedder(Settings(gemini_api_key=None, gemini_embedding_model=None))


def test_patient_mode_uses_longer_retries() -> None:
    s = Settings(gemini_api_key="k", gemini_embedding_model="gemini-embedding-001")
    fast, patient = get_embedder(s), get_embedder(s, patient=True)
    assert (fast._max_attempts, fast._max_delay) == (4, 8.0)
    assert (patient._max_attempts, patient._max_delay) == (7, 30.0)


async def test_429_is_retried_then_succeeds() -> None:
    # One real backoff sleep (<0.5 s) happens here; that's acceptable for a unit test.
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429)
        n = len(json.loads(request.content)["requests"])
        return httpx.Response(200, json={"embeddings": [{"values": [1.0, 0, 0, 0]}] * n})

    out = await make_embedder(handler).embed(["x"], "RETRIEVAL_DOCUMENT")
    assert calls["n"] == 2 and out == [[1.0, 0.0, 0.0, 0.0]]
