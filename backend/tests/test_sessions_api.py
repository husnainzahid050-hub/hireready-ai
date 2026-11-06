"""End-to-end API tests with an in-memory fake database and a scripted fake LLM."""

import fnmatch
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.routers.sessions as sessions_router
from app.main import app
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
from tests.conftest import make_docx

# ------------------------------------------------------------------ fakes


def _match(row: dict[str, Any], key: str, cond: str) -> bool:
    if cond.startswith("eq."):
        return str(row.get(key)) == cond[3:]
    if cond == "not.is.null":
        return row.get(key) is not None
    if cond.startswith("in.("):
        return str(row.get(key)) in cond[4:-1].split(",")
    if cond.startswith("like."):
        return fnmatch.fnmatchcase(str(row.get(key)), cond[5:])
    raise NotImplementedError(cond)


class FakeDB:
    def __init__(self) -> None:
        self.t: dict[str, list[dict[str, Any]]] = {}

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
            self.rows(table).append(r)

    async def insert_returning(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        r = {
            "id": str(uuid.uuid4()),
            "status": "created",
            "expires_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
            "created_at": datetime.now(UTC).isoformat(),
            "role_title": None,
            **row,
        }
        self.rows(table).append(r)
        return dict(r)

    async def update(self, table: str, params: dict[str, str], values: dict[str, Any]) -> None:
        for r in self._filter(table, params):
            r.update(values)

    async def delete(self, table: str, params: dict[str, str]) -> None:
        doomed = {id(r) for r in self._filter(table, params)}
        self.t[table] = [r for r in self.rows(table) if id(r) not in doomed]
        if table == "documents":  # emulate ON DELETE CASCADE
            ids = {r["id"] for r in self.rows("documents")}
            self.t["doc_chunks"] = [c for c in self.rows("doc_chunks") if c["document_id"] in ids]

    async def rpc(self, fn: str, args: dict[str, Any]) -> list[dict[str, Any]]:
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

    async def embed(self, texts: list[str], task: str) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


REAL_QUOTE = "served answers through a FastAPI backend."


class FakeLLM:
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


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    db, llm = FakeDB(), FakeLLM()
    monkeypatch.setattr(sessions_router, "get_db", lambda: db)
    monkeypatch.setattr(sessions_router, "get_llm", lambda: llm)
    monkeypatch.setattr(sessions_router, "get_embedder", lambda: FakeEmbedder())
    return TestClient(app), db, llm


def sse_events(text: str) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


# ------------------------------------------------------------------ tests


def test_create_session_requires_consent(env) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = env
    r = client.post("/api/v1/sessions", json={"consent": False})
    assert r.status_code == 400 and r.json()["error"]["code"] == "consent_required"


def test_token_is_stored_hashed(env) -> None:  # type: ignore[no-untyped-def]
    client, db, _ = env
    r = client.post("/api/v1/sessions", json={"consent": True})
    assert r.status_code == 201
    token = r.json()["guest_token"]
    stored = db.rows("sessions")[0]["guest_token_hash"]
    assert token not in json.dumps(db.t) and len(stored) == 64


def test_demo_full_flow_streams_and_guards_quotes(env) -> None:  # type: ignore[no-untyped-def]
    client, db, llm = env
    s = client.post("/api/v1/sessions?demo=true", json={"consent": True}).json()
    h = {"X-Guest-Token": s["guest_token"]}

    r = client.post(f"/api/v1/sessions/{s['session_id']}/analyze", headers=h)
    assert r.headers["content-type"].startswith("text/event-stream")
    events = sse_events(r.text)
    names = [e for e, _ in events]
    assert names[0] == "status" and names[-1] == "done"
    assert {"profiles", "score", "gaps", "insights"} <= set(names)

    done = events[-1][1]
    gaps = {g["skill"]: g for g in done["gaps"]}
    assert gaps["FastAPI"]["verdict"] == "strong_evidence" and gaps["FastAPI"]["quote_verified"]
    assert gaps["Docker"]["verdict"] == "no_evidence"  # hallucinated quote downgraded
    assert done["match_score"] == round(100 * (0.7 * 0.5 + 0.2 * 0.5 + 0.1))  # 55
    assert [d["day"] for d in done["prep_plan"]] == list(range(1, 8))

    # Judge prompt lists each excerpt once and references ids per skill.
    judge_prompt = llm.prompts[llm.calls.index("EvidenceJudgements")]
    assert "[E1]" in judge_prompt and "- FastAPI: check E1" in judge_prompt

    # Session marked analyzed; second analyze is served from cache (no new LLM calls).
    assert db.rows("sessions")[0]["status"] == "analyzed"
    n = len(llm.calls)
    again = sse_events(client.post(f"/api/v1/sessions/{s['session_id']}/analyze", headers=h).text)
    assert [e for e, _ in again] == ["done"] and len(llm.calls) == n

    got = client.get(f"/api/v1/sessions/{s['session_id']}/analysis", headers=h).json()
    assert got["analysis"]["role_title"] == "Junior AI Engineer" and got["session"]["is_demo"]


def test_wrong_or_missing_token_is_404(env) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = env
    s = client.post("/api/v1/sessions?demo=true", json={"consent": True}).json()
    for headers in ({"X-Guest-Token": "nope"}, {}):
        r = client.get(f"/api/v1/sessions/{s['session_id']}/analysis", headers=headers)
        assert r.status_code == 404 and r.json()["error"]["code"] == "session_not_found"


def test_upload_documents_replaces_old_analysis(env) -> None:  # type: ignore[no-untyped-def]
    client, db, _ = env
    s = client.post("/api/v1/sessions", json={"consent": True}).json()
    h = {"X-Guest-Token": s["guest_token"]}
    cv = make_docx(["ALI RAZA", "Built a chatbot and " + REAL_QUOTE] + ["Python projects."] * 5)
    jd = "We need FastAPI and Docker skills. " * 10
    r = client.post(
        f"/api/v1/sessions/{s['session_id']}/documents",
        headers=h,
        files={"cv": ("cv.docx", cv, "application/octet-stream")},
        data={"jd_text": jd},
    )
    assert r.status_code == 200, r.text
    assert {d["kind"] for d in db.rows("documents")} == {"cv", "jd"}
    events = sse_events(client.post(f"/api/v1/sessions/{s['session_id']}/analyze", headers=h).text)
    assert events[-1][0] == "done" and db.rows("gap_analyses")

    # Re-upload => old analysis removed, so the next analyze recomputes.
    client.post(
        f"/api/v1/sessions/{s['session_id']}/documents",
        headers=h,
        files={"cv": ("cv.docx", cv, "application/octet-stream")},
        data={"jd_text": jd + " Also SQL."},
    )
    assert db.rows("gap_analyses") == []


def test_analysis_is_null_before_analyze(env) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = env
    s = client.post("/api/v1/sessions?demo=true", json={"consent": True}).json()
    r = client.get(
        f"/api/v1/sessions/{s['session_id']}/analysis", headers={"X-Guest-Token": s["guest_token"]}
    )
    assert r.status_code == 200 and r.json()["analysis"] is None


def test_analyze_without_documents_streams_error(env) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = env
    s = client.post("/api/v1/sessions", json={"consent": True}).json()
    events = sse_events(
        client.post(f"/api/v1/sessions/{s['session_id']}/analyze",
                    headers={"X-Guest-Token": s["guest_token"]}).text
    )  # fmt: skip
    assert events == [("error", {"code": "documents_missing", "message": events[0][1]["message"]})]
