"""LLM call tracing: an in-process usage record, plus optional Langfuse export.

Every provider attempt made by `LLMClient.structured()` becomes one `LLMCall` record (provider,
model, output schema, token usage, latency, ok/failed). Records go to two optional sinks:

1. `collect_llm_calls()`: a context manager that gathers the records made inside it (used by the
   eval runner to measure tokens, latency and cost per pipeline step).
2. Langfuse, ONLY when LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and LANGFUSE_HOST are all set.
   Spans are sent with a few httpx calls to Langfuse's OpenTelemetry endpoint
   (`/api/public/otel/v1/traces`, OTLP over HTTP/JSON), so there is no SDK dependency.

Privacy: a span carries metadata only (model, schema name, token counts, latency, status, the
request id). Prompts and outputs are NEVER sent, because they contain CV / JD / transcript text.
That makes a trace less useful for debugging a single bad answer, which is the deliberate trade.

Safety: tracing must never break a request. Every sink is wrapped so any error (bad config,
network failure, missing event loop) is swallowed and logged as a warning without details. Export
is fire-and-forget: the request does not wait for Langfuse.
"""

import asyncio
import base64
import hashlib
import json
import secrets
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from app.core.config import Settings, get_settings
from app.core.http import get_http_client
from app.core.logging import get_logger, request_id_var

log = get_logger(__name__)

OTLP_PATH = "/api/public/otel/v1/traces"
EXPORT_TIMEOUT_S = 3.0

# Paid on-demand list prices in USD per 1M tokens (input, output), used only for cost ESTIMATES:
# the app runs on free tiers, so the real cost is $0. Source: Groq's model pages
# (console.groq.com/docs/model/openai/gpt-oss-20b and .../gpt-oss-120b), checked 2026-11-12.
PRICES_CHECKED = "2026-11-12"
PRICE_PER_M_TOKENS: dict[str, tuple[float, float]] = {
    "openai/gpt-oss-20b": (0.075, 0.30),
    "openai/gpt-oss-120b": (0.15, 0.60),
}

# Output schema -> pipeline step, so a trace reads like the architecture.
SPAN_NAMES = {
    "CVProfile": "extract_cv",
    "JobProfile": "extract_jd",
    "EvidenceJudgements": "gap_judge",
    "InsightsDraft": "insights",
    "InterviewPlanDraft": "plan_interview",
    "AnswerEvaluationDraft": "evaluate_answer",
}


@dataclass(frozen=True)
class LLMCall:
    provider: str
    model: str
    schema: str
    latency_s: float
    ok: bool
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error: str | None = None

    @property
    def cost_usd(self) -> float | None:
        """Estimated paid-tier cost; None when the model's price is unknown."""
        price = PRICE_PER_M_TOKENS.get(self.model)
        if price is None or self.prompt_tokens is None or self.completion_tokens is None:
            return None
        return (self.prompt_tokens * price[0] + self.completion_tokens * price[1]) / 1_000_000


# Collector for `collect_llm_calls()`; None = nobody is collecting.
_collector: ContextVar[list[LLMCall] | None] = ContextVar("llm_call_collector", default=None)
# Token usage reported by the provider for the attempt running in this task.
_usage: ContextVar[dict[str, int | None] | None] = ContextVar("llm_call_usage", default=None)
# Strong references to in-flight exports (asyncio only keeps weak references to tasks).
_pending: set[asyncio.Task[None]] = set()


@contextmanager
def collect_llm_calls() -> Iterator[list[LLMCall]]:
    """Collect every LLMCall recorded inside the block (including in tasks it starts)."""
    calls: list[LLMCall] = []
    token = _collector.set(calls)
    try:
        yield calls
    finally:
        _collector.reset(token)


def note_usage(prompt_tokens: Any, completion_tokens: Any) -> None:
    """Called by a provider adapter once it knows the token usage of the current attempt."""
    usage = _usage.get()
    if usage is not None:
        usage["prompt"] = prompt_tokens if isinstance(prompt_tokens, int) else None
        usage["completion"] = completion_tokens if isinstance(completion_tokens, int) else None


@contextmanager
def trace_llm_call(provider: str, model: str, schema: str) -> Iterator[None]:
    """Wrap ONE provider attempt. Records it on exit; never swallows the attempt's exception."""
    usage: dict[str, int | None] = {"prompt": None, "completion": None}
    token = _usage.set(usage)
    started = time.perf_counter()
    error: str | None = None
    try:
        yield
    except BaseException as exc:
        error = type(exc).__name__
        raise
    finally:
        _usage.reset(token)
        record_llm_call(
            LLMCall(
                provider=provider,
                model=model,
                schema=schema,
                latency_s=round(time.perf_counter() - started, 3),
                ok=error is None,
                prompt_tokens=usage["prompt"],
                completion_tokens=usage["completion"],
                error=error,
            )
        )


def record_llm_call(call: LLMCall, settings: Settings | None = None) -> None:
    try:
        calls = _collector.get()
        if calls is not None:
            calls.append(call)
        cfg = langfuse_config(settings or get_settings())
        if cfg is not None:
            _schedule_export(cfg, call)
    except Exception as exc:  # noqa: BLE001 - tracing must never break a request
        log.warning("tracing_failed", extra={"extra_fields": {"error": type(exc).__name__}})


# ------------------------------------------------------------------ Langfuse (OTLP/HTTP JSON)


@dataclass(frozen=True)
class LangfuseConfig:
    endpoint: str
    auth_header: str
    environment: str


def langfuse_config(settings: Settings) -> LangfuseConfig | None:
    """None (tracing off) unless all three Langfuse variables are set."""
    pk, sk, host = (
        settings.langfuse_public_key,
        settings.langfuse_secret_key,
        settings.langfuse_host,
    )
    if not pk or sk is None or not sk.get_secret_value() or not host:
        return None
    raw = f"{pk}:{sk.get_secret_value()}".encode()
    return LangfuseConfig(
        endpoint=host.rstrip("/") + OTLP_PATH,
        auth_header="Basic " + base64.b64encode(raw).decode(),
        environment=settings.vercel_env or settings.app_env,
    )


def _attr(key: str, value: str | int | float | bool) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    if isinstance(value, float):
        return {"key": key, "value": {"doubleValue": value}}
    return {"key": key, "value": {"stringValue": value}}


def span_payload(call: LLMCall, environment: str, request_id: str | None = None) -> dict[str, Any]:
    """One OTLP span for one LLM call. Metadata only: no prompt, no output, no user text.

    All LLM calls of one HTTP request share a trace id derived from the request id, so Langfuse
    shows them as one trace (e.g. the 3-4 calls of an analysis).
    """
    rid = request_id or request_id_var.get()
    trace_seed = rid if rid and rid != "-" else secrets.token_hex(16)
    trace_id = hashlib.sha256(trace_seed.encode()).hexdigest()[:32]
    end_ns = time.time_ns()
    start_ns = end_ns - int(call.latency_s * 1e9)
    attrs = [
        _attr("langfuse.observation.type", "generation"),
        _attr("langfuse.trace.name", "hireready-request"),
        _attr("langfuse.environment", environment),
        _attr("gen_ai.system", call.provider),
        _attr("gen_ai.request.model", call.model),
        _attr("hireready.schema", call.schema),
        _attr("hireready.request_id", rid or "-"),
        _attr("hireready.ok", call.ok),
    ]
    if call.prompt_tokens is not None:
        attrs.append(_attr("gen_ai.usage.input_tokens", call.prompt_tokens))
    if call.completion_tokens is not None:
        attrs.append(_attr("gen_ai.usage.output_tokens", call.completion_tokens))
    if call.cost_usd is not None:
        attrs.append(
            _attr("langfuse.observation.cost_details", json.dumps({"total": call.cost_usd}))
        )
    if call.error:
        attrs.append(_attr("hireready.error", call.error))
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": [_attr("service.name", "hireready-backend")]},
                "scopeSpans": [
                    {
                        "scope": {"name": "hireready.llm"},
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": secrets.token_hex(8),
                                "name": SPAN_NAMES.get(call.schema, f"llm.{call.schema}"),
                                "kind": 3,  # CLIENT
                                "startTimeUnixNano": str(start_ns),
                                "endTimeUnixNano": str(end_ns),
                                "attributes": attrs,
                                "status": {"code": 1 if call.ok else 2},
                            }
                        ],
                    }
                ],
            }
        ]
    }


async def _export(cfg: LangfuseConfig, payload: dict[str, Any]) -> None:
    try:
        resp = await get_http_client().post(
            cfg.endpoint,
            json=payload,
            headers={"Authorization": cfg.auth_header, "x-langfuse-ingestion-version": "4"},
            timeout=EXPORT_TIMEOUT_S,
        )
        if resp.status_code >= 300:
            log.warning(
                "tracing_export_rejected", extra={"extra_fields": {"status": resp.status_code}}
            )
    except Exception as exc:  # noqa: BLE001 - never let tracing errors escape
        log.warning("tracing_export_failed", extra={"extra_fields": {"error": type(exc).__name__}})


def _schedule_export(cfg: LangfuseConfig, call: LLMCall) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # not inside an event loop: nothing to export with
    task = loop.create_task(_export(cfg, span_payload(call, cfg.environment)))
    _pending.add(task)
    task.add_done_callback(_pending.discard)


async def flush_traces(timeout_s: float = 5.0) -> None:
    """Wait for in-flight exports (scripts call this before exiting)."""
    if _pending:
        await asyncio.wait(set(_pending), timeout=timeout_s)
