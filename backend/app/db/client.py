"""Minimal Supabase client over the REST (PostgREST) API.

Why not the official `supabase` Python package? It also pulls in realtime, storage
and auth clients we don't need. A few httpx calls keep the serverless bundle and
cold start small, and are trivial to mock in tests.

Auth: new-style secret keys (`sb_secret_...`) go ONLY in the `apikey` header.
Legacy service_role JWTs also need `Authorization: Bearer`.
"""

from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.http import get_http_client, request_with_retry


class DatabaseError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"Database error {status_code}: {message}")
        self.status_code = status_code


class NotConfiguredError(RuntimeError):
    pass


class SupabaseRest:
    def __init__(self, url: str, key: str, client: httpx.AsyncClient) -> None:
        self._base = url.rstrip("/") + "/rest/v1"
        self._client = client
        self._headers = {"apikey": key, "Content-Type": "application/json"}
        if not key.startswith("sb_secret_"):
            self._headers["Authorization"] = f"Bearer {key}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: Any = None,
        prefer: str | None = None,
    ) -> Any:
        headers = dict(self._headers)
        if prefer:
            headers["Prefer"] = prefer
        url = f"{self._base}/{path}"

        async def send() -> httpx.Response:
            return await self._client.request(
                method, url, params=params, json=json, headers=headers
            )

        resp = await request_with_retry(send, what=f"supabase {method} {path.split('?')[0]}")
        if resp.status_code >= 400:
            # PostgREST error bodies contain a message, never our row data.
            try:
                msg = str(resp.json().get("message", resp.text))
            except ValueError:
                msg = resp.text
            raise DatabaseError(resp.status_code, msg[:300])
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    async def rpc(self, fn: str, args: dict[str, Any]) -> Any:
        return await self._request("POST", f"rpc/{fn}", json=args)

    async def select(self, table: str, params: dict[str, str]) -> list[dict[str, Any]]:
        result = await self._request("GET", table, params=params)
        return list(result or [])

    async def insert(
        self, table: str, rows: list[dict[str, Any]], *, on_conflict: str | None = None
    ) -> None:
        if not rows:
            return
        params = {"on_conflict": on_conflict} if on_conflict else None
        prefer = "return=minimal"
        if on_conflict:
            prefer += ",resolution=merge-duplicates"
        await self._request("POST", table, params=params, json=rows, prefer=prefer)

    async def insert_returning(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        result = await self._request("POST", table, json=row, prefer="return=representation")
        if not result:
            raise DatabaseError(500, "Insert returned no row")
        return dict(result[0])

    async def update(self, table: str, params: dict[str, str], values: dict[str, Any]) -> None:
        if not params:
            raise ValueError("Refusing to update without a filter")
        await self._request("PATCH", table, params=params, json=values, prefer="return=minimal")

    async def update_returning(
        self, table: str, params: dict[str, str], values: dict[str, Any], *, select: str
    ) -> list[dict[str, Any]]:
        """PATCH and return the changed rows (only `select` columns). [] = no row matched the
        filter, which callers use as a compare-and-swap ("someone else changed it first")."""
        if not params:
            raise ValueError("Refusing to update without a filter")
        result = await self._request(
            "PATCH",
            table,
            params={**params, "select": select},
            json=values,
            prefer="return=representation",
        )
        return list(result or [])

    async def delete(self, table: str, params: dict[str, str]) -> None:
        if not params:
            raise ValueError("Refusing to delete without a filter")
        await self._request("DELETE", table, params=params, prefer="return=minimal")


def get_db(settings: Settings | None = None) -> SupabaseRest:
    s = settings or get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        raise NotConfiguredError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    return SupabaseRest(
        s.supabase_url, s.supabase_service_role_key.get_secret_value(), get_http_client()
    )
