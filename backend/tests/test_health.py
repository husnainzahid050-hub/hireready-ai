from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok() -> None:
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert set(body["dependencies"]) == {
        "database",
        "llm_groq",
        "llm_gemini",
        "redis",
        "turnstile",
        "email",
        "cron",
        "webhook",
    }
    assert "X-Request-ID" in r.headers


def test_request_id_is_echoed() -> None:
    r = client.get("/api/v1/health", headers={"x-request-id": "abc123"})
    assert r.headers["X-Request-ID"] == "abc123"


def test_unknown_route_uses_error_envelope() -> None:
    r = client.get("/api/v1/does-not-exist")
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "not_found", "message": "Not Found"}}
