"""Security headers on every API response.

The Next.js app sets headers for pages (frontend/next.config.ts). The FastAPI backend also has
its own public Vercel URL, so it must not rely on the proxy: these headers make API responses
non-cacheable (they carry personal data), non-sniffable and non-frameable.
"""

from typing import Final

from starlette.types import ASGIApp, Message, Receive, Scope, Send

API_SECURITY_HEADERS: Final[dict[bytes, bytes]] = {
    b"x-content-type-options": b"nosniff",
    b"x-frame-options": b"DENY",
    b"referrer-policy": b"no-referrer",
    # A JSON API never needs to load anything or be framed.
    b"content-security-policy": b"default-src 'none'; frame-ancestors 'none'",
    b"cross-origin-resource-policy": b"same-origin",
    b"strict-transport-security": b"max-age=63072000; includeSubDomains",
}
DEFAULT_CACHE_CONTROL: Final = b"no-store"
# Swagger UI (dev only; disabled in production) loads scripts from a CDN.
DOCS_PATHS: Final = ("/api/v1/docs", "/api/v1/openapi.json")


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_docs = str(scope.get("path", "")).startswith(DOCS_PATHS)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                for key, value in API_SECURITY_HEADERS.items():
                    if key == b"content-security-policy" and is_docs:
                        continue
                    if key not in present:
                        headers.append((key, value))
                if b"cache-control" not in present:  # SSE sets its own "no-cache"
                    headers.append((b"cache-control", DEFAULT_CACHE_CONTROL))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
