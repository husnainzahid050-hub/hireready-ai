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
DOCS_PATHS: Final = frozenset(
    {"/api/v1/docs", "/api/v1/docs/oauth2-redirect", "/api/v1/openapi.json"}
)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, docs_enabled: bool = True) -> None:
        self.app = app
        # In production the docs routes don't exist, so they keep the strict CSP like any 404
        # (the live 404 for /api/v1/docs had no CSP at all: security re-audit S2-6).
        self.docs_enabled = docs_enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_docs = self.docs_enabled and str(scope.get("path", "")) in DOCS_PATHS

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
