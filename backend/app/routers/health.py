"""Liveness + dependency checks.

Phase 0: reports which dependencies are configured. Real reachability checks
(DB, Redis, LLM provider) are added as each dependency is introduced.
"""

from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import __version__
from app.core.config import get_settings
from app.core.rate_limit import client_ip_with_source

router = APIRouter(tags=["health"])

DependencyStatus = Literal["ok", "configured", "not_configured", "error"]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str
    environment: str
    dependencies: dict[str, DependencyStatus]


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    s = get_settings()
    deps: dict[str, DependencyStatus] = {
        "database": "configured"
        if s.supabase_url and s.supabase_service_role_key
        else "not_configured",
        "llm_groq": "configured" if s.groq_api_key else "not_configured",
        "llm_gemini": "configured" if s.gemini_api_key else "not_configured",
        # Phase 7 controls: each is OFF ("not_configured") until its env vars are set.
        "redis": "configured"
        if s.upstash_redis_rest_url and s.upstash_redis_rest_token
        else "not_configured",
        "turnstile": "configured" if s.turnstile_secret_key else "not_configured",
        "email": "configured" if s.resend_api_key and s.email_from else "not_configured",
        "cron": "configured" if s.cron_secret else "not_configured",
        "webhook": "configured" if s.webhook_enabled else "not_configured",
    }
    return HealthResponse(
        status="ok", version=__version__, environment=s.app_env, dependencies=deps
    )


@router.get("/health/client-ip")
async def client_ip_check(request: Request) -> JSONResponse:
    """Which client IP the backend sees, and from which header (docs/SECURITY.md, "Verify the
    client IP"). Open it in a browser on the deployed site: `ip` must be YOUR address and
    `source` should be "proxy". It only ever echoes the caller's own address."""
    ip, source = client_ip_with_source(request)
    return JSONResponse({"ip": ip, "source": source}, headers={"Cache-Control": "no-store"})
