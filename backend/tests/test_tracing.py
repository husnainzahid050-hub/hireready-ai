"""Tracing: a complete no-op without Langfuse keys, metadata-only spans with them, never raises."""

import asyncio
import json
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

import app.core.tracing as tracing
from app.core.config import Settings
from app.core.tracing import (
    LLMCall,
    collect_llm_calls,
    langfuse_config,
    note_usage,
    record_llm_call,
    span_payload,
    trace_llm_call,
)
from app.services.llm import LLMClient

CV_TEXT = "Ali Raza built a RAG assistant at Example Labs"


def _settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


LANGFUSE = {
    "langfuse_public_key": "pk-lf-test",
    "langfuse_secret_key": "sk-lf-test",
    "langfuse_host": "https://langfuse.example.com/",
}


def test_config_off_unless_all_three_vars_set() -> None:
    assert langfuse_config(_settings()) is None
    assert langfuse_config(_settings(langfuse_public_key="pk", langfuse_host="https://x")) is None
    assert langfuse_config(_settings(langfuse_secret_key="sk", langfuse_host="https://x")) is None  # noqa: S106
    cfg = langfuse_config(_settings(**LANGFUSE))
    assert cfg is not None
    assert cfg.endpoint == "https://langfuse.example.com/api/public/otel/v1/traces"
    assert cfg.auth_header.startswith("Basic ")


async def test_no_keys_means_no_export_and_no_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    scheduled: list[Any] = []
    monkeypatch.setattr(tracing, "_schedule_export", lambda *a: scheduled.append(a))
    record_llm_call(LLMCall("groq", "m", "S", 0.1, True), settings=_settings())
    assert scheduled == []
    assert not tracing._pending


async def test_collector_records_usage_and_failures() -> None:
    with collect_llm_calls() as calls:
        with trace_llm_call("groq", "openai/gpt-oss-20b", "JobProfile"):
            note_usage(1000, 200)
        with pytest.raises(ValueError), trace_llm_call("gemini", "g", "JobProfile"):
            raise ValueError("boom")
    assert [c.ok for c in calls] == [True, False]
    assert calls[0].prompt_tokens == 1000 and calls[0].completion_tokens == 200
    assert calls[0].cost_usd == pytest.approx((1000 * 0.075 + 200 * 0.30) / 1e6)
    assert calls[1].error == "ValueError" and calls[1].prompt_tokens is None
    # Outside the block nothing is collected and nothing fails.
    record_llm_call(LLMCall("groq", "m", "S", 0.1, True), settings=_settings())


def test_note_usage_outside_a_call_is_ignored() -> None:
    note_usage(1, 2)  # no active attempt: must not raise


def test_span_has_metadata_only() -> None:
    call = LLMCall("groq", "openai/gpt-oss-120b", "EvidenceJudgements", 1.5, True, 900, 100)
    payload = span_payload(call, "test", request_id="req-123")
    span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    keys = {a["key"] for a in span["attributes"]}
    assert "langfuse.observation.input" not in keys and "langfuse.observation.output" not in keys
    assert {"gen_ai.request.model", "gen_ai.usage.input_tokens", "hireready.request_id"} <= keys
    assert len(span["traceId"]) == 32 and len(span["spanId"]) == 16
    # Same request -> same trace id, so all calls of one request group into one trace.
    again = span_payload(call, "test", request_id="req-123")
    assert again["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["traceId"] == span["traceId"]


class _Out(BaseModel):
    ok: bool


async def test_llm_call_exports_without_prompt_text(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "groq" in request.url.host:
            body = {
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 5},
            }
            return httpx.Response(200, json=body)
        sent.append({"url": str(request.url), "body": request.content.decode()})
        return httpx.Response(200, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = _settings(groq_api_key="k", groq_fast_model="openai/gpt-oss-20b", **LANGFUSE)
    monkeypatch.setattr(tracing, "get_settings", lambda: settings)
    monkeypatch.setattr(tracing, "get_http_client", lambda: client)

    with collect_llm_calls() as calls:
        out = await LLMClient(settings, client).structured(system="s", user=CV_TEXT, schema=_Out)
    await tracing.flush_traces()
    assert out.ok is True
    assert len(calls) == 1 and calls[0].prompt_tokens == 50
    assert len(sent) == 1 and sent[0]["url"].endswith("/api/public/otel/v1/traces")
    assert "Ali Raza" not in sent[0]["body"] and "RAG assistant" not in sent[0]["body"]
    assert json.loads(sent[0]["body"])["resourceSpans"]
    await client.aclose()


async def test_export_failure_never_breaks_the_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "groq" in request.url.host:
            body = {"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {}}
            return httpx.Response(200, json=body)
        raise httpx.ConnectError("langfuse down")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = _settings(groq_api_key="k", groq_fast_model="m", **LANGFUSE)
    monkeypatch.setattr(tracing, "get_settings", lambda: settings)
    monkeypatch.setattr(tracing, "get_http_client", lambda: client)
    out = await LLMClient(settings, client).structured(system="s", user="u", schema=_Out)
    await tracing.flush_traces()
    assert out.ok is True
    await client.aclose()


def test_record_swallows_internal_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_: Settings) -> None:
        raise RuntimeError("bad config")

    monkeypatch.setattr(tracing, "langfuse_config", broken)
    record_llm_call(LLMCall("groq", "m", "S", 0.1, True), settings=_settings())


def test_no_event_loop_is_fine() -> None:
    cfg = langfuse_config(_settings(**LANGFUSE))
    assert cfg is not None
    tracing._schedule_export(cfg, LLMCall("groq", "m", "S", 0.1, True))
    assert not tracing._pending


def test_flush_with_nothing_pending() -> None:
    asyncio.run(tracing.flush_traces())
