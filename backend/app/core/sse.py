"""Server-Sent Events helpers: wire format, an overall time budget and "still working" notices.

`paced()` wraps an async stream of (event, payload) pairs and:
- stops it with `BudgetExceededError` once `budget_s` is used up, so a slow provider can never
  run past the serverless function limit (Vercel kills the function at `maxDuration` without
  telling the browser anything);
- emits `slow_event` once per step when nothing has arrived for `slow_after_s`, or as soon as
  `fallbacks()` grows (the LLM client switched to the backup provider). Besides telling the user
  what is happening, these events keep proxies from closing an idle connection.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

Event = tuple[str, dict[str, Any]]


class BudgetExceededError(Exception):
    pass


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def paced(
    events: AsyncIterator[Event],
    *,
    budget_s: float,
    slow_after_s: float,
    slow_event: Event,
    fallbacks: Callable[[], int] = lambda: 0,
    poll_s: float = 1.0,
) -> AsyncIterator[Event]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + budget_s
    try:
        while True:
            # The next item is produced in its own task so we can wake up while waiting for it.
            step = asyncio.ensure_future(anext(events))
            step_started, seen_fallbacks, warned = loop.time(), fallbacks(), False
            try:
                while not step.done():
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        raise BudgetExceededError
                    await asyncio.wait({step}, timeout=min(poll_s, remaining))
                    if step.done() or warned:
                        continue
                    if loop.time() - step_started >= slow_after_s or fallbacks() > seen_fallbacks:
                        warned = True
                        yield slow_event
            finally:
                if not step.done():
                    step.cancel()
                    await asyncio.wait({step})  # let the producer unwind before we close it
            try:
                item = step.result()
            except StopAsyncIteration:
                return
            yield item
    finally:
        aclose = getattr(events, "aclose", None)
        if aclose is not None:
            await aclose()
