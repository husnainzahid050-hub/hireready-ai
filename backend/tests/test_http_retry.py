import httpx
import pytest

from app.core.http import request_with_retry


class Sleeps:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, s: float) -> None:
        self.calls.append(s)


def make_send(responses: list[httpx.Response | Exception]):  # type: ignore[no-untyped-def]
    it = iter(responses)

    async def send() -> httpx.Response:
        item = next(it)
        if isinstance(item, Exception):
            raise item
        return item

    return send


async def test_returns_immediately_on_success() -> None:
    sleep = Sleeps()
    r = await request_with_retry(make_send([httpx.Response(200)]), what="t", sleep=sleep)
    assert r.status_code == 200
    assert sleep.calls == []


async def test_retries_on_429_then_succeeds_and_honors_retry_after() -> None:
    sleep = Sleeps()
    send = make_send([httpx.Response(429, headers={"retry-after": "3"}), httpx.Response(200)])
    r = await request_with_retry(send, what="t", sleep=sleep)
    assert r.status_code == 200
    assert len(sleep.calls) == 1 and sleep.calls[0] >= 3


async def test_does_not_retry_client_errors() -> None:
    sleep = Sleeps()
    r = await request_with_retry(make_send([httpx.Response(400)]), what="t", sleep=sleep)
    assert r.status_code == 400
    assert sleep.calls == []


async def test_gives_up_after_max_attempts_and_returns_last_response() -> None:
    sleep = Sleeps()
    send = make_send([httpx.Response(503)] * 3)
    r = await request_with_retry(send, what="t", max_attempts=3, sleep=sleep)
    assert r.status_code == 503
    assert len(sleep.calls) == 2


async def test_network_errors_are_retried_then_raised() -> None:
    sleep = Sleeps()
    err = httpx.ConnectError("boom")
    with pytest.raises(httpx.ConnectError):
        await request_with_retry(make_send([err, err]), what="t", max_attempts=2, sleep=sleep)
    assert len(sleep.calls) == 1


async def test_backoff_is_capped() -> None:
    sleep = Sleeps()
    send = make_send([httpx.Response(500)] * 6)
    await request_with_retry(send, what="t", max_attempts=6, max_delay=2.0, sleep=sleep)
    assert max(sleep.calls) <= 2.0
