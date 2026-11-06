"""Reject oversized request bodies before anything parses them.

Without this, a multipart upload is fully parsed (and spooled to disk) before our 2 MB check
runs, and a JSON body of any size is read into memory. Vercel caps bodies at 4.5 MB, but the
backend should not rely on the platform (local, preview, or a future host).

Pure ASGI middleware: checks `Content-Length` up front AND counts the bytes actually received,
so a lying or missing Content-Length (chunked encoding) can't bypass it.
"""

import json
from typing import Final

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Vercel's request body limit; also comfortably above a 2 MB CV + JD + multipart overhead and
# a 120 s opus voice answer (~1-2 MB).
DEFAULT_MAX_BODY_BYTES: Final = 4_500_000


class BodyTooLargeError(Exception):
    pass


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int = DEFAULT_MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = -1
                if declared < 0 or declared > self.max_bytes:
                    await _reject(send, 413 if declared > self.max_bytes else 400)
                    return

        received = 0
        response_started = False
        rejected = False

        async def limited_receive() -> Message:
            nonlocal received, rejected
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # Answer 413 ourselves right away: FastAPI wraps body-parsing errors into a
                    # generic 400, and we want a clear status. Later app output is dropped.
                    if not response_started and not rejected:
                        rejected = True
                        await _reject(send, 413)
                    raise BodyTooLargeError
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if rejected:
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except BodyTooLargeError:
            pass  # the 413 was already sent (or the response had started; nothing to do)


async def _reject(send: Send, status: int) -> None:
    code, message = (
        ("request_too_large", "The request is too large.")
        if status == 413
        else ("bad_request", "Invalid Content-Length header.")
    )
    body = json.dumps({"error": {"code": code, "message": message}}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
