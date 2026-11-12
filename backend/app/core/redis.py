"""Tiny Upstash Redis client over its REST API (no SDK, no TCP connection to keep alive).

Upstash's REST API takes Redis commands as JSON arrays: `POST {url}/pipeline` with
`[["INCR", "k"], ["EXPIRE", "k", "60", "NX"]]` and `Authorization: Bearer <token>` returns
`[{"result": 1}, {"result": 1}]` (or `{"error": "..."}` per command). Serverless-friendly: each
call is one HTTPS request. Docs: https://upstash.com/docs/redis/features/restapi

`get_redis()` returns None until UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN are both set;
callers then use their in-process fallback.
"""

from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.http import get_http_client

TIMEOUT_S = 2.0  # a slow Redis must not slow every request; callers fall back instead


class RedisUnavailableError(Exception):
    pass


class UpstashRedis:
    def __init__(self, url: str, token: str, client: httpx.AsyncClient) -> None:
        self._url = url.rstrip("/") + "/pipeline"
        self._headers = {"Authorization": f"Bearer {token}"}
        self._client = client

    async def pipeline(self, commands: list[list[str]]) -> list[Any]:
        """Run the commands in order; return each command's result. Any failure (network,
        HTTP status, malformed body, a per-command error) raises RedisUnavailableError."""
        try:
            resp = await self._client.post(
                self._url, headers=self._headers, json=commands, timeout=TIMEOUT_S
            )
            resp.raise_for_status()
            body = resp.json()
            if not isinstance(body, list) or len(body) != len(commands):
                raise ValueError("unexpected pipeline response")
            if any("error" in item for item in body):
                raise ValueError("command error")
            return [item["result"] for item in body]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise RedisUnavailableError(type(exc).__name__) from exc


_redis: UpstashRedis | None = None
_resolved = False


def get_redis(settings: Settings | None = None) -> UpstashRedis | None:
    global _redis, _resolved
    if not _resolved:
        s = settings or get_settings()
        if s.upstash_redis_rest_url and s.upstash_redis_rest_token:
            _redis = UpstashRedis(
                s.upstash_redis_rest_url,
                s.upstash_redis_rest_token.get_secret_value(),
                get_http_client(),
            )
        _resolved = True
    return _redis


def reset_redis() -> None:
    """Tests: forget the cached client so new settings take effect."""
    global _redis, _resolved
    _redis, _resolved = None, False
