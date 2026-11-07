"""Consistent error envelope: {"error": {"code", "message"}}. Never leak stack traces."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

log = get_logger(__name__)


class AppError(Exception):
    """Raise this for expected, user-facing errors."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def session_not_found() -> AppError:
    # Same error for "doesn't exist", "not yours", "expired" and "malformed id", so attackers
    # can't probe session ids.
    return AppError("session_not_found", "Session not found or expired.", status_code=404)


AI_UNAVAILABLE_MESSAGE = "Our AI providers are busy right now. Please try again in a minute."


def ai_unavailable() -> AppError:
    # 503: nothing was written, so the client can safely retry the same request.
    return AppError("ai_unavailable", AI_UNAVAILABLE_MESSAGE, status_code=503)


def error_body(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message), status_code=exc.status_code)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed", 429: "rate_limited"}.get(
            exc.status_code, "http_error"
        )
        return JSONResponse(
            error_body(code, str(exc.detail)),
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # A malformed session id is just an unknown session: same 404 as everywhere (QA B12).
        if any(tuple(e["loc"]) == ("path", "session_id") for e in exc.errors()):
            return await _app_error(request, session_not_found())
        # Only expose field locations, not the submitted values (may contain PII).
        fields = ", ".join(".".join(str(p) for p in e["loc"]) for e in exc.errors())
        return JSONResponse(
            error_body("validation_error", f"Invalid input: {fields}"), status_code=422
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", exc_info=exc)
        return JSONResponse(
            error_body("internal_error", "Something went wrong. Please try again."),
            status_code=500,
        )
