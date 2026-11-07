import json
import uuid

import httpx

from app.db.client import SupabaseRest
from app.services.retrieval import Retriever
from tests.fakes import FakeEmbedder


def make(rows: list[dict]):  # type: ignore[no-untyped-def,type-arg]
    seen: list[dict] = []  # type: ignore[type-arg]

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return httpx.Response(200, json=rows)

    db = SupabaseRest(
        "https://p.supabase.co",
        "sb_secret_x",
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    emb = FakeEmbedder()
    return Retriever(db, emb), seen, emb


ROW = {
    "id": str(uuid.uuid4()),
    "content": "Python > Question bank > Junior > What is a list?\n\nA mutable sequence.",
    "metadata": {"heading_path": ["Python"]},
    "competency": "python",
    "level": "junior",
    "source_file": "python.md",
    "document_id": None,
    "score": 0.0328,
}


async def test_search_rubric_sends_filter_and_query_embedding() -> None:
    retriever, seen, emb = make([ROW])
    results = await retriever.search_rubric(
        "  list vs tuple  ", competency="python", level="junior", k=3
    )

    assert emb.calls == [(["list vs tuple"], "RETRIEVAL_QUERY")]
    args = seen[0]
    assert args["query_text"] == "list vs tuple"
    assert args["query_embedding"] == "[1,0,0]"
    assert args["match_count"] == 3
    assert args["filter"] == {"source": "knowledge", "competency": "python", "level": "junior"}
    assert results[0].competency == "python" and results[0].score == 0.0328


async def test_search_rubric_without_filters() -> None:
    retriever, seen, _ = make([])
    assert await retriever.search_rubric("anything") == []
    assert seen[0]["filter"] == {"source": "knowledge"}


async def test_search_cv_is_scoped_to_session() -> None:
    sid = uuid.uuid4()
    retriever, seen, _ = make([])
    await retriever.search_cv(sid, "fastapi")
    assert seen[0]["filter"] == {"source": "cv", "session_id": str(sid)}


async def test_empty_query_skips_network() -> None:
    retriever, seen, emb = make([ROW])
    assert await retriever.search_rubric("   ") == []
    assert seen == [] and emb.calls == []


async def test_k_is_clamped_and_query_truncated() -> None:
    retriever, seen, emb = make([])
    await retriever.search_rubric("q" * 5000, k=500)
    assert seen[0]["match_count"] == 50
    assert len(emb.calls[0][0][0]) == 1000
