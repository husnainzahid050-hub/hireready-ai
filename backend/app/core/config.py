"""Application settings, loaded from environment variables.

All secrets come from the environment (never hard-coded). Model names are also
env-driven because providers rename/deprecate models often.
"""

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = Field(default="development")
    app_base_url: str = Field(default="http://localhost:3000")
    # Comma-separated in the env var, e.g. "http://localhost:3000,https://x.vercel.app"
    allowed_origins: str = Field(default="http://localhost:3000")

    # LLM / STT (used from Phase 1+; optional in Phase 0)
    groq_api_key: SecretStr | None = None
    groq_fast_model: str | None = None
    groq_strong_model: str | None = None
    groq_stt_model: str | None = None
    gemini_api_key: SecretStr | None = None
    gemini_text_model: str | None = None
    gemini_embedding_model: str | None = None
    # Gemini 3.x "thinking" depth for the fallback model: low keeps latency ~2 s. Empty = omit.
    gemini_thinking_level: str = "low"
    embedding_dim: int = 768

    # Data
    supabase_url: str | None = None
    supabase_service_role_key: SecretStr | None = None

    # Abuse protection (Phase 7). Each control is OFF until its env vars are set, so local dev
    # and tests need no extra accounts. See docs/SECURITY.md.
    upstash_redis_rest_url: str | None = None
    upstash_redis_rest_token: SecretStr | None = None
    turnstile_secret_key: SecretStr | None = None
    # Email (Phase 5) via Resend's HTTP API. Sending is OFF (503 email_not_configured) until
    # both are set. EMAIL_FROM: a sender on a domain verified in Resend ("Name <a@b.com>" works).
    resend_api_key: SecretStr | None = None
    email_from: str | None = None
    # Set automatically by Vercel ("production" | "preview" | "development").
    vercel_env: str | None = None

    # Phase 7: automation. Each feature is OFF until its secret is set.
    # Vercel Cron sends "Authorization: Bearer <CRON_SECRET>"; unset = cron endpoints answer 503.
    cron_secret: SecretStr | None = None
    # Standard Webhooks "report.completed" event; the secret may be "whsec_<base64>" or raw text.
    outbound_webhook_url: str | None = None
    outbound_webhook_secret: SecretStr | None = None
    # Signs the single-purpose reminder links (confirm / mark done / unsubscribe).
    reminder_token_secret: SecretStr | None = None
    reminder_daily_cap: int = Field(default=250, ge=1, le=10_000)
    # Shared with the Next.js proxy (frontend/proxy.ts), which forwards the browser's IP in
    # X-HireReady-Client-IP. Only trusted when the request also carries this secret.
    client_ip_header_secret: SecretStr | None = None
    # Global daily LLM-call budget across all users (denial-of-wallet guard). Above
    # LLM_DAILY_SOFT_RATIO x budget, demo sessions are served from the cache only; above the
    # budget every fresh LLM action gets 503 until 00:00 UTC.
    llm_daily_budget: int = Field(default=1500, ge=1)
    llm_daily_soft_ratio: float = Field(default=0.8, gt=0, le=1)

    @field_validator("embedding_dim")
    @classmethod
    def _positive_dim(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("EMBEDDING_DIM must be positive")
        return v

    @field_validator("allowed_origins")
    @classmethod
    def _no_wildcard_origin(cls, v: str) -> str:
        if any(o.strip() == "*" for o in v.split(",")):
            raise ValueError("ALLOWED_ORIGINS must be an explicit list, not '*'")
        return v

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        # Also trust Vercel's own flag, so forgetting APP_ENV can't expose /docs in production.
        return self.app_env == "production" or self.vercel_env == "production"

    @property
    def webhook_enabled(self) -> bool:
        return bool(self.outbound_webhook_url and self.outbound_webhook_secret)

    def startup_problems(self) -> tuple[list[str], list[str]]:
        """(errors, warnings) about the configuration. In production, errors stop the app at
        startup (fail fast) instead of surfacing as a 500 on the first request."""
        errors: list[str] = []
        warnings: list[str] = []
        if not (self.supabase_url and self.supabase_service_role_key):
            errors.append("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
        if not (self.groq_api_key or self.gemini_api_key):
            errors.append("GROQ_API_KEY or GEMINI_API_KEY is required")
        if self.outbound_webhook_url and not self.outbound_webhook_secret:
            errors.append("OUTBOUND_WEBHOOK_URL is set without OUTBOUND_WEBHOOK_SECRET")
        if self.outbound_webhook_url and not self.outbound_webhook_url.startswith("https://"):
            errors.append("OUTBOUND_WEBHOOK_URL must use https://")
        if self.app_base_url.startswith("http://localhost"):
            warnings.append("APP_BASE_URL points at localhost (email links will be wrong)")
        for name, value in (
            ("UPSTASH_REDIS_REST_URL", self.upstash_redis_rest_url),
            ("TURNSTILE_SECRET_KEY", self.turnstile_secret_key),
            ("CRON_SECRET", self.cron_secret),
        ):
            if not value:
                warnings.append(f"{name} is not set (that control is off)")
        return errors, warnings


@lru_cache
def get_settings() -> Settings:
    return Settings()
