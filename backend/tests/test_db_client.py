import json

import httpx
import pytest

from app.core.config import Settings
from app.db.client import DatabaseError, NotConfiguredError, SupabaseRest, get_db


def make_db(handler, key: str = "sb_secret_abc") -> SupabaseRest:  # type: ignore[no-untyped-def]
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SupabaseRest("https://proj.supabase.co/", key, client)


async def test_new_secret_key_only_in_apikey_header() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=[{"id": 1}])

    db = make_db(handler)
    rows = await db.rpc("hybrid_search", {"query_text": "x"})
    assert rows == [{"id": 1}]
    req = seen[0]
    assert str(req.url) == "https://proj.supabase.co/rest/v1/rpc/hybrid_search"
    assert req.headers["apikey"] == "sb_secret_abc"
    assert "authorization" not in req.headers
    assert json.loads(req.content) == {"query_text": "x"}


async def test_legacy_jwt_key_also_sends_bearer() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=[])

    await make_db(handler, key="eyJhbGciOi.legacy.jwt").select("t", {"select": "*"})
    assert seen[0].headers["authorization"] == "Bearer eyJhbGciOi.legacy.jwt"


async def test_insert_upsert_sets_prefer_and_on_conflict() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(201)

    db = make_db(handler)
    await db.insert("knowledge_chunks", [{"a": 1}], on_conflict="content_hash")
    req = seen[0]
    assert req.method == "POST"
    assert req.url.params["on_conflict"] == "content_hash"
    assert req.headers["prefer"] == "return=minimal,resolution=merge-duplicates"


async def test_insert_empty_is_noop() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("should not be called")

    await make_db(handler).insert("t", [])


async def test_delete_requires_filter() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    with pytest.raises(ValueError):
        await make_db(handler).delete("t", {})


async def test_error_raises_database_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "function not found"})

    with pytest.raises(DatabaseError) as exc:
        await make_db(handler).rpc("nope", {})
    assert exc.value.status_code == 404
    assert "function not found" in str(exc.value)


def test_get_db_requires_config() -> None:
    with pytest.raises(NotConfiguredError):
        get_db(Settings(supabase_url=None, supabase_service_role_key=None))
