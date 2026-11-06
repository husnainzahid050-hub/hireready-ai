"""Shared async HTTP client + retry with exponential backoff.

One AsyncClient per process is reused across requests (connection pooling),
which matters a lot for latency on serverless warm starts.
"""

import asyncio
import random
from collections.abc import Awaitable, Callable

import httpx

from app.core.logging import get_logger

log = get_logger(__name__)

RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _client


async def close_http_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


async def request_with_retry(
    send: Callable[[], Awaitable[httpx.Response]],
    *,
    what: str,
    max_attempts: int = 4,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> httpx.Response:
    """Call `send()` until it returns a non-retryable response or attempts run out.

    Retries on network errors and on RETRYABLE_STATUS. Honors Retry-After.
    Returns the last response (caller decides how to handle non-2xx).
    """
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = await send()
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            last_exc = exc
            response = None
        if response is not None and response.status_code not in RETRYABLE_STATUS:
            return response
        if attempt == max_attempts:
            break
        delay = min(max_delay, base_delay * 2 ** (attempt - 1)) * (0.5 + random.random() / 2)  # noqa: S311
        if response is not None:
            delay = max(delay, min(max_delay, _retry_after_seconds(response) or 0.0))
        log.warning(
            "http_retry",
            extra={
                "extra_fields": {
                    "what": what,
                    "attempt": attempt,
                    "status": response.status_code if response is not None else None,
                    "delay_s": round(delay, 2),
                }
            },
        )
        await sleep(delay)
    if response is not None:
        return response
    assert last_exc is not None  # noqa: S101
    raise last_exc
