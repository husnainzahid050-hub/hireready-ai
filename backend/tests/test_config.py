import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_cors_origins_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://a.com, https://b.com ,")
    assert Settings().cors_origins == ["http://a.com", "https://b.com"]


def test_secrets_are_masked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk_supersecret")
    s = Settings()
    assert "gsk_supersecret" not in repr(s)
    assert s.groq_api_key is not None
    assert s.groq_api_key.get_secret_value() == "gsk_supersecret"


def test_invalid_embedding_dim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDING_DIM", "0")
    with pytest.raises(ValidationError):
        Settings()
