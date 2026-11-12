"""Shared in-memory fakes for API and service tests: database, embedder, scripted LLM, SSE parser.

One copy only: every test module imports these instead of defining its own. `FakeDB` emulates the
small PostgREST surface `app.db.client.SupabaseRest` exposes, plus the SQL functions the app calls
(`consume_quota`, `claim_analysis`, `hybrid_search`), with the same semantics as the migrations.
"""

import fnmatch
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

import app.routers.interview as interview_router
import app.routers.report as report_router
import app.routers.sessions as sessions_router
from app.db.client import DatabaseError
from app.schemas.analysis import (
    CVProfile,
    EvidenceJudgements,
    InsightsDraft,
    JobProfile,
    JobSkill,
    PrepDayDraft,
    QuestionGroup,
    SkillJudgement,
    Strength,
)


def _get(row: dict[str, Any], key: str) -> Any:
    """Column value, or a PostgREST JSON path like `state->current->>id`."""
    if "->" not in key:
        return row.get(key)
    head, *path = key.replace("->>", "->").split("->")
    value: Any = row.get(head)
    for part in path:
        value = value.get(part) if isinstance(value, dict) else None
    return value


def _match(row: dict[str, Any], key: str, cond: str) -> bool:
    if "->" in key:
        return cond.startswith("eq.") and str(_get(row, key)) == cond[3:]
    if cond.startswith("eq."):
        return str(row.get(key)) == cond[3:]
    if cond.startswith("lt."):
        return row.get(key) is not None and str(row.get(key)) < cond[3:]
    if cond.startswith("lte."):
        return row.get(key) is not None and str(row.get(key)) <= cond[4:]
    if cond == "not.is.null":
        return row.get(key) is not None
    if cond.startswith("in.("):
        return str(row.get(key)) in cond[4:-1].split(",")
    if cond.startswith("like."):
        return fnmatch.fnmatchcase(str(row.get(key)), cond[5:])
    raise NotImplementedError(cond)


# Unique constraints the app relies on (insert without upsert -> 409, like PostgREST).
# Tables whose primary key isn't `id` count too (interview_state is keyed by session_id).
UNIQUE: dict[str, tuple[str, ...]] = {
    "reports": ("session_id", "share_token"),
    "interview_state": ("session_id",),
}
# ON DELETE CASCADE children: table -> [(child table, child column, parent column)].
CASCADE: dict[str, list[tuple[str, str, str]]] = {
    "sessions": [
        ("documents", "session_id", "id"), ("gap_analyses", "session_id", "id"),
        ("questions", "session_id", "id"), ("interview_state", "session_id", "id"),
        ("reports", "session_id", "id"), ("reminders", "session_id", "id"),
    ],
    "documents": [("doc_chunks", "document_id", "id")],
    "questions": [("answers", "question_id", "id")],
}  # fmt: skip


class FakeDB:
    def __init__(self) -> None:
        self.t: dict[str, list[dict[str, Any]]] = {}
        self.usage: dict[tuple[str, str], int] = {}  # session_usage (quota counters)
        self.rpc_calls: list[str] = []
        self.demo_cache: dict[str, Any] | None = None  # gap_analyses row copy_demo_analysis copies

    def rows(self, table: str) -> list[dict[str, Any]]:
        return self.t.setdefault(table, [])

    def _filter(self, table: str, params: dict[str, str]) -> list[dict[str, Any]]:
        out = self.rows(table)
        for k, v in params.items():
            if k in ("select", "limit", "on_conflict", "order"):
                continue
            out = [r for r in out if _match(r, k, v)]
        return out[: int(params["limit"])] if "limit" in params else out

    async def select(self, table: str, params: dict[str, str]) -> list[dict[str, Any]]:
        if table == "session_usage":  # quota counters live in self.usage
            self.t["session_usage"] = [
                {"session_id": s, "action": a, "count": c} for (s, a), c in self.usage.items()
            ]
        return [dict(r) for r in self._filter(table, params)]

    async def insert(
        self, table: str, rows: list[dict[str, Any]], *, on_conflict: str | None = None
    ) -> None:
        for r in rows:
            r = dict(r)
            r.setdefault("id", str(uuid.uuid4()))
            r.setdefault("structured", None)
            if on_conflict:
                self.t[table] = [
                    x for x in self.rows(table) if x.get(on_conflict) != r[on_conflict]
                ]
            for col in UNIQUE.get(table, ()):
                if r.get(col) is not None and any(x.get(col) == r[col] for x in self.rows(table)):
                    raise DatabaseError(409, "duplicate key value violates unique constraint")
            self.rows(table).append(r)

    async def insert_returning(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        r = {
            "id": str(uuid.uuid4()),
            "status": "created",
            "expires_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
            "created_at": datetime.now(UTC).isoformat(),
            "role_title": None,
            "analysis_started_at": None,
            **row,
        }
        self.rows(table).append(r)
        return dict(r)

    async def update(self, table: str, params: dict[str, str], values: dict[str, Any]) -> None:
        for col in UNIQUE.get(table, ()):
            if values.get(col) is not None and any(
                x.get(col) == values[col] for x in self.rows(table)
            ):
                raise DatabaseError(409, "duplicate key value violates unique constraint")
        for r in self._filter(table, params):
            r.update(values)

    async def update_returning(
        self, table: str, params: dict[str, str], values: dict[str, Any], *, select: str
    ) -> list[dict[str, Any]]:
        changed = self._filter(table, params)
        for r in changed:
            r.update(values)
        return [{k: r.get(k) for k in select.split(",")} for r in changed]

    async def delete(self, table: str, params: dict[str, str]) -> None:
        doomed_rows = self._filter(table, params)
        doomed = {id(r) for r in doomed_rows}
        self.t[table] = [r for r in self.rows(table) if id(r) not in doomed]
        for child, col, parent_col in CASCADE.get(table, []):  # emulate ON DELETE CASCADE
            for parent_id in {str(r.get(parent_col)) for r in doomed_rows}:
                await self.delete(child, {col: f"eq.{parent_id}"})
        if table == "sessions":
            ids = {str(r["id"]) for r in doomed_rows}
            self.usage = {k: v for k, v in self.usage.items() if k[0] not in ids}

    def _copy_demo(self, sid: str) -> bool:
        is_demo = any(s.get("is_demo") for s in self._filter("sessions", {"id": f"eq.{sid}"}))
        if self.demo_cache is None or not is_demo:
            return False
        if self._filter("gap_analyses", {"session_id": f"eq.{sid}"}):
            return False
        self.rows("gap_analyses").append({**self.demo_cache, "session_id": sid})
        for s in self._filter("sessions", {"id": f"eq.{sid}"}):
            s["status"] = "analyzed"
        return True

    async def rpc(self, fn: str, args: dict[str, Any]) -> Any:
        self.rpc_calls.append(fn)
        if fn == "consume_quota":  # supabase/migrations/20261106000004_security.sql
            key = (args["p_session_id"], args["p_action"])
            if self.usage.get(key, 0) >= args["p_limit"]:
                return False
            self.usage[key] = self.usage.get(key, 0) + 1
            return True
        if fn == "claim_analysis":  # supabase/migrations/20261106000005_analysis_claim.sql
            sid = args["p_session_id"]
            stale = datetime.now(UTC) - timedelta(seconds=args["p_stale_seconds"])
            for s in self._filter("sessions", {"id": f"eq.{sid}"}):
                started = s.get("analysis_started_at")
                fresh = started is not None and datetime.fromisoformat(started) >= stale
                if fresh or self._filter("gap_analyses", {"session_id": f"eq.{sid}"}):
                    return False
                s["analysis_started_at"] = datetime.now(UTC).isoformat()
                return True
            return False
        if fn == "copy_demo_analysis":  # 20261112000007; a test sets self.demo_cache to opt in
            return self._copy_demo(args["p_session_id"])
        assert fn == "hybrid_search"
        f = args["filter"]
        if f["source"] == "cv":
            docs = {d["id"] for d in self.rows("documents") if d["session_id"] == f["session_id"]}
            return [
                {"id": c.get("id", str(uuid.uuid4())), "content": c["content"], "score": 0.03,
                 "metadata": {}, "document_id": c["document_id"]}
                for c in self.rows("doc_chunks") if c["document_id"] in docs
            ][: args["match_count"]]  # fmt: skip
        return [
            {"id": str(uuid.uuid4()), "content": "Python > Question bank > Junior > What is a list?\n\nx",
             "score": 0.03, "metadata": {}, "competency": "python", "level": "junior"}
        ]  # fmt: skip


class FakeEmbedder:
    dim = 3

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []

    async def embed(self, texts: list[str], task: str) -> list[list[float]]:
        self.calls.append((texts, task))
        return [[1.0, 0.0, 0.0] for _ in texts]


REAL_QUOTE = "served answers through a FastAPI backend."


class FakeLLM:
    """Scripted gap-analysis LLM: FastAPI is evidenced, Docker gets a hallucinated quote."""

    fallbacks = 0  # LLMClient counts provider fallbacks; the analysis stream reads it

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.prompts: list[str] = []

    async def structured(self, *, system: str, user: str, schema: type, **_: Any) -> Any:
        self.calls.append(schema.__name__)
        self.prompts.append(user)
        if schema is CVProfile:
            return CVProfile(
                name="Ali", education=[], skills=[], projects=[], experience=[], certifications=[]
            )
        if schema is JobProfile:
            return JobProfile(
                title="Junior AI Engineer", seniority="junior",
                must_have_skills=[JobSkill(name="FastAPI", competency="apis_backend"),
                                  JobSkill(name="Docker", competency="cloud_devops")],
                nice_to_have_skills=[], responsibilities=[], tools=[], soft_skills=[],
            )  # fmt: skip
        if schema is EvidenceJudgements:
            return EvidenceJudgements(
                judgements=[
                    SkillJudgement(skill="FastAPI", verdict="strong_evidence", evidence_quote=REAL_QUOTE, reason="r"),
                    # Hallucinated evidence: must be downgraded by the quote check.
                    SkillJudgement(skill="Docker", verdict="strong_evidence",
                                   evidence_quote="Deployed everything with Docker on AWS", reason="r"),
                ]
            )  # fmt: skip
        if schema is InsightsDraft:
            return InsightsDraft(
                strengths=[Strength(title="APIs", why_it_matters="w", evidence_quote=REAL_QUOTE)],
                likely_questions=[
                    QuestionGroup(topic="Docker", questions=["How would you containerize it?"])
                ],
                prep_plan=[
                    PrepDayDraft(focus="Docker", tasks=["t"], resource_urls=[]) for _ in range(7)
                ],
            )
        raise AssertionError(schema)


def install(
    monkeypatch: pytest.MonkeyPatch, db: Any, llm: Any, embedder: Any | None = None
) -> None:
    """Point both routers at the given fakes (no network, no real Supabase)."""
    emb = embedder or FakeEmbedder()
    for mod in (sessions_router, interview_router):
        monkeypatch.setattr(mod, "get_db", lambda: db)
        monkeypatch.setattr(mod, "get_llm", lambda: llm)
        monkeypatch.setattr(mod, "get_embedder", lambda: emb)
    monkeypatch.setattr(report_router, "get_db", lambda: db)
    monkeypatch.setattr(report_router, "get_llm", lambda: llm)


def sse_events(text: str) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out
