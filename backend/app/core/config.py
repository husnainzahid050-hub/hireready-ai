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
    embedding_dim: int = 768

    # Data
    supabase_url: str | None = None
    supabase_service_role_key: SecretStr | None = None

    @field_validator("embedding_dim")
    @classmethod
    def _positive_dim(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("EMBEDDING_DIM must be positive")
        return v

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
