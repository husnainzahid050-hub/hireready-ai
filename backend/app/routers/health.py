"""Liveness + dependency checks.

Phase 0: reports which dependencies are configured. Real reachability checks
(DB, Redis, LLM provider) are added as each dependency is introduced.
"""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app import __version__
from app.core.config import get_settings

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
    }
    return HealthResponse(
        status="ok", version=__version__, environment=s.app_env, dependencies=deps
    )
