"""FastAPI entrypoint. Vercel auto-detects the `app` object in app/main.py."""

import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.core.body_limit import BodySizeLimitMiddleware
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.headers import SecurityHeadersMiddleware
from app.core.logging import configure_logging, get_logger, request_id_var, safe_request_id
from app.routers import health, interview, sessions

configure_logging()
log = get_logger("app")
settings = get_settings()

app = FastAPI(
    title="HireReady AI API",
    version=__version__,
    # Hide interactive docs in production.
    docs_url=None if settings.is_production else "/api/v1/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/api/v1/openapi.json",
)

# Explicit allowlist only. In production the browser goes through the Next.js
# rewrite (same origin), so CORS mainly matters for local dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-Guest-Token", "X-Turnstile-Token"],
)


@app.middleware("http")
async def request_context(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    rid = safe_request_id(request.headers.get("x-request-id")) or uuid.uuid4().hex
    token = request_id_var.set(rid)
    start = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    response.headers["X-Request-ID"] = rid
    log.info(
        "request",
        extra={
            "extra_fields": {
                "request_id": rid,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
            }
        },
    )
    return response


# Added last = outermost: oversized bodies are rejected before any other work happens.
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(BodySizeLimitMiddleware)

register_error_handlers(app)
app.include_router(health.router, prefix="/api/v1")
app.include_router(sessions.router, prefix="/api/v1")
app.include_router(interview.router, prefix="/api/v1")
