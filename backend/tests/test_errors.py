from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.errors import AppError, register_error_handlers


def _make_app() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    class Body(BaseModel):
        text: str

    @app.get("/app-error")
    async def app_error() -> None:
        raise AppError("bad_upload", "File too large", status_code=413)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    @app.post("/validate")
    async def validate(body: Body) -> dict[str, str]:
        return {"ok": body.text}

    return app


client = TestClient(_make_app(), raise_server_exceptions=False)


def test_app_error_envelope() -> None:
    r = client.get("/app-error")
    assert r.status_code == 413
    assert r.json() == {"error": {"code": "bad_upload", "message": "File too large"}}


def test_unhandled_error_hides_details() -> None:
    r = client.get("/boom")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal_error"
    assert "secret" not in r.text


def test_validation_error_does_not_echo_input() -> None:
    r = client.post("/validate", json={"text": 123, "extra": "ali@example.com"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    assert "ali@example.com" not in r.text
