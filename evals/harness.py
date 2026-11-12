"""Eval plumbing: caching LLM/embedding wrappers, offline fakes, and an in-memory hybrid search.

Live mode calls the real providers through the production `LLMClient` and `GeminiEmbedder`, but
every response is cached on disk (evals/.cache/), keyed by a hash of the exact request and model
names, so re-running the suite costs nothing unless a prompt, a dataset item or a model changes.

Fake mode replaces both providers with deterministic heuristics. Its numbers mean nothing about
model quality: it exists so CI can check that the runner, metrics and report still work.
"""

import asyncio
import hashlib
import json
import math
import re
import sys
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, TypeVar
from uuid import UUID

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.tracing import LLMCall, collect_llm_calls, note_usage, trace_llm_call  # noqa: E402
from app.services.chunking import Chunk  # noqa: E402
from app.services.knowledge import load_knowledge_dir  # noqa: E402
from app.services.retrieval import RetrievedChunk  # noqa: E402
from pydantic import BaseModel  # noqa: E402

T = TypeVar("T", bound=BaseModel)
TaskType = Literal["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"]

STEP_BY_SCHEMA = {
    "CVProfile": "cv_extract",
    "JobProfile": "jd_extract",
    "EvidenceJudgements": "judge",
    "InsightsDraft": "insights",
    "InterviewPlanDraft": "plan",
    "AnswerEvaluationDraft": "score_answer",
}


class CacheMiss(RuntimeError):
    pass


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# ------------------------------------------------------------------ call bookkeeping


@dataclass
class CallStat:
    step: str
    cached: bool
    provider: str
    model: str
    latency_s: float
    ok: bool
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: float | None


@dataclass
class RunStats:
    calls: list[CallStat] = field(default_factory=list)
    embed_calls: int = 0
    embed_cached: int = 0
    embed_texts: int = 0

    def add(self, step: str, cached: bool, llm_calls: list[dict[str, Any]]) -> None:
        for c in llm_calls:
            call = LLMCall(**c)
            self.calls.append(
                CallStat(
                    step=step,
                    cached=cached,
                    provider=call.provider,
                    model=call.model,
                    latency_s=call.latency_s,
                    ok=call.ok,
                    prompt_tokens=call.prompt_tokens,
                    completion_tokens=call.completion_tokens,
                    cost_usd=call.cost_usd,
                )
            )


class TokenPacer:
    """Keep fresh calls under the free-tier tokens-per-minute budget (Groq: ~8K TPM per model)."""

    def __init__(self, budget_per_min: int = 6000, estimate: int = 2500) -> None:
        self.budget = budget_per_min
        self.estimate = estimate
        self._spent: dict[str, deque[tuple[float, int]]] = {}

    async def wait(self, lane: str) -> None:
        window = self._spent.setdefault(lane, deque())
        while True:
            now = time.monotonic()
            while window and now - window[0][0] > 60:
                window.popleft()
            used = sum(t for _, t in window)
            if not window or used + self.estimate <= self.budget:
                return
            await asyncio.sleep(max(1.0, 60 - (now - window[0][0]) + 0.5))

    def spend(self, lane: str, tokens: int) -> None:
        self._spent.setdefault(lane, deque()).append((time.monotonic(), tokens))


# ------------------------------------------------------------------ cached LLM


class CachedLLM:
    """Same `structured()` signature as LLMClient. Caches validated outputs + their call records."""

    def __init__(
        self,
        inner: Any,
        stats: RunStats,
        *,
        cache_dir: Path | None,
        models: dict[str, str | None],
        cache_only: bool = False,
        pacer: TokenPacer | None = None,
    ) -> None:
        self._inner = inner
        self._stats = stats
        self._dir = cache_dir
        self._models = models
        self._cache_only = cache_only
        self._pacer = pacer
        self.salt = ""  # set to e.g. "repeat-2" to force an independent sample
        self.last: dict[str, BaseModel] = {}  # most recent output per schema (raw, pre-validation)
        self.fallbacks = 0

    async def structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        tier: str = "fast",
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> T:
        step = STEP_BY_SCHEMA.get(schema.__name__, schema.__name__)
        key = _hash(
            {
                "system": system,
                "user": user,
                "schema": schema.model_json_schema(),
                "tier": tier,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "models": self._models,
                "salt": self.salt,
            }
        )
        path = self._dir / f"{key[:40]}.json" if self._dir else None
        if path and path.exists():
            entry = json.loads(path.read_text(encoding="utf-8"))
            self._stats.add(step, True, entry["calls"])
            out = schema.model_validate(entry["result"])
            self.last[schema.__name__] = out
            return out
        if self._cache_only:
            raise CacheMiss(f"no cached response for {step} ({key[:12]})")
        if self._pacer:
            await self._pacer.wait(tier)
        with collect_llm_calls() as calls:
            try:
                out = await self._inner.structured(
                    system=system,
                    user=user,
                    schema=schema,
                    tier=tier,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            finally:
                records = [asdict(c) for c in calls]
                self._stats.add(step, False, records)
                if self._pacer:
                    spent = sum((c.prompt_tokens or 0) + (c.completion_tokens or 0) for c in calls)
                    self._pacer.spend(tier, spent or self._pacer.estimate)
        self.last[schema.__name__] = out
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            entry = {"step": step, "result": out.model_dump(mode="json"), "calls": records}
            path.write_text(json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
        return out


# ------------------------------------------------------------------ cached embeddings


class CachedEmbedder:
    def __init__(self, inner: Any, stats: RunStats, *, cache_dir: Path | None, model: str, cache_only: bool) -> None:
        self._inner = inner
        self._stats = stats
        self._dir = cache_dir
        self._model = model
        self._cache_only = cache_only
        self.dim: int = inner.dim

    def _path(self, text: str, task: str) -> Path | None:
        if not self._dir:
            return None
        return self._dir / f"{_hash([self._model, self.dim, task, text])[:40]}.json"

    async def embed(self, texts: list[str], task: TaskType) -> list[list[float]]:
        out: list[list[float] | None] = [None] * len(texts)
        missing: list[int] = []
        for i, t in enumerate(texts):
            p = self._path(t, task)
            if p and p.exists():
                out[i] = json.loads(p.read_text(encoding="utf-8"))
                self._stats.embed_cached += 1
            else:
                missing.append(i)
        if missing:
            if self._cache_only:
                raise CacheMiss(f"{len(missing)} embeddings not cached")
            vectors = await self._inner.embed([texts[i] for i in missing], task)
            self._stats.embed_calls += 1
            self._stats.embed_texts += len(missing)
            for i, v in zip(missing, vectors, strict=True):
                v = [round(x, 6) for x in v]
                out[i] = v
                p = self._path(texts[i], task)
                if p:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(json.dumps(v), encoding="utf-8", newline="\n")
        return [v for v in out if v is not None]


# ------------------------------------------------------------------ text helpers

_WORD = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset(
    "a an and are as at be but by can do does for from how i if in into is it its me my of on or "
    "so that the their them then there they this to was we what when where which who why will with "
    "you your vs versus".split()
)


def stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def terms(text: str) -> list[str]:
    return [stem(w) for w in _WORD.findall(text.lower()) if w not in STOPWORDS]


class FakeEmbedder:
    """Deterministic hashed bag-of-words vectors (offline mode only)."""

    dim = 512

    async def embed(self, texts: list[str], task: TaskType) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for w in terms(t):
                h = int(hashlib.md5(w.encode(), usedforsecurity=False).hexdigest(), 16)
                v[h % self.dim] += 1.0 if (h >> 12) % 2 else -1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
        return out


# ------------------------------------------------------------------ in-memory hybrid search


@dataclass
class Doc:
    id: UUID
    key: str
    content: str
    competency: str | None = None
    level: str | None = None
    source_file: str | None = None
    terms: list[str] = field(default_factory=list)
    vector: list[float] = field(default_factory=list)


Mode = Literal["hybrid", "vector", "keyword"]


class InMemoryHybrid:
    """Re-implementation of the `hybrid_search` SQL function for evals without a database.

    Same shape: a keyword ranker (all query terms must match, like websearch_to_tsquery's AND;
    ranked by term frequency instead of Postgres ts_rank_cd) and a cosine ranker, each with a pool
    of 4 x k, fused with Reciprocal Rank Fusion (k = 50).
    """

    RRF_K = 50

    def __init__(self, docs: list[Doc]) -> None:
        self.docs = docs

    @classmethod
    async def build(cls, docs: list[Doc], embedder: Any) -> "InMemoryHybrid":
        vectors = await embedder.embed([d.content for d in docs], "RETRIEVAL_DOCUMENT")
        for d, v in zip(docs, vectors, strict=True):
            d.vector = v
            d.terms = terms(d.content)
        return cls(docs)

    def search(self, query: str, vector: list[float], k: int = 5, mode: Mode = "hybrid") -> list[Doc]:
        pool = k * 4
        q_terms = list(dict.fromkeys(terms(query)))
        fts: list[Doc] = []
        if q_terms:
            matches = [d for d in self.docs if all(t in d.terms for t in q_terms)]
            fts = sorted(matches, key=lambda d: -sum(d.terms.count(t) for t in q_terms))[:pool]
        sem = sorted(self.docs, key=lambda d: -sum(a * b for a, b in zip(d.vector, vector, strict=True)))[:pool]
        w_fts = 0.0 if mode == "vector" else 1.0
        w_sem = 0.0 if mode == "keyword" else 1.0
        scores: dict[UUID, float] = {}
        for rank, d in enumerate(fts, start=1):
            scores[d.id] = scores.get(d.id, 0.0) + w_fts / (self.RRF_K + rank)
        for rank, d in enumerate(sem, start=1):
            scores[d.id] = scores.get(d.id, 0.0) + w_sem / (self.RRF_K + rank)
        by_id = {d.id: d for d in self.docs}
        ranked = sorted(scores, key=lambda i: -scores[i])
        return [by_id[i] for i in ranked[:k]]


def chunk_key(source_file: str, heading_path: list[str]) -> str:
    return f"{source_file}#{heading_path[-1]}"


def chunk_uuid(text: str) -> UUID:
    return uuid.UUID(hex=hashlib.sha256(text.encode()).hexdigest()[:32])


def knowledge_docs() -> list[Doc]:
    docs: list[Doc] = []
    for kf in load_knowledge_dir(BACKEND / "knowledge"):
        c: Chunk
        for c in kf.chunks:
            docs.append(
                Doc(
                    id=chunk_uuid(c.content),
                    key=chunk_key(kf.source_file, c.heading_path),
                    content=c.content,
                    competency=kf.competency,
                    level=c.level,
                    source_file=kf.source_file,
                )
            )
    return docs


def to_retrieved(d: Doc, score: float = 0.0) -> RetrievedChunk:
    return RetrievedChunk(
        id=d.id,
        content=d.content,
        score=score,
        metadata={},
        competency=d.competency,
        level=d.level,
        source_file=d.source_file,
    )


class EvalRetriever:
    """Duck-typed stand-in for app.services.retrieval.Retriever used by the pipeline code.

    CV search runs in memory over the one CV under test. Rubric search goes to the real database
    (`rubric`, a Retriever) in live mode, or to the in-memory knowledge index in fake mode.
    """

    def __init__(
        self,
        cv_index: InMemoryHybrid | None,
        embedder: Any,
        rubric: Any = None,
        kb_index: InMemoryHybrid | None = None,
    ) -> None:
        self._cv = cv_index
        self._embedder = embedder
        self._rubric = rubric
        self._kb = kb_index

    async def search_cv_many(self, session_id: UUID, queries: list[str], *, k: int = 3) -> list[list[RetrievedChunk]]:
        if self._cv is None or not queries:
            return [[] for _ in queries]
        cleaned = [q.strip() or "-" for q in queries]
        vectors = await self._embedder.embed(cleaned, "RETRIEVAL_QUERY")
        return [[to_retrieved(d) for d in self._cv.search(q, v, k)] for q, v in zip(cleaned, vectors, strict=True)]

    async def search_rubric_many(
        self, queries: Any, *, level: str | None = None, k: int = 3
    ) -> list[list[RetrievedChunk]]:
        if self._rubric is not None:
            return await self._rubric.search_rubric_many(queries, level=level, k=k)  # type: ignore[no-any-return]
        assert self._kb is not None  # noqa: S101
        texts = [q for q, _ in queries]
        vectors = await self._embedder.embed(texts, "RETRIEVAL_QUERY")
        out = []
        for (q, comp), v in zip(queries, vectors, strict=True):
            docs = [d for d in self._kb.search(q, v, k * 4) if not comp or d.competency == comp]
            out.append([to_retrieved(d) for d in docs[:k]])
        return out


# ------------------------------------------------------------------ fake LLM (offline mode)

_TAG = re.compile(r"<(cv|jd|transcript|evidence|analysis_data)>\n(.*?)\n</\1>", re.DOTALL)
COMPETENCY_HINTS = {
    "python": "python", "pytest": "python", "sql": "sql", "postgres": "sql", "machine learning": "machine_learning",
    "statistic": "machine_learning", "pytorch": "deep_learning", "deep learning": "deep_learning",
    "rag": "nlp_llms", "llm": "nlp_llms", "nlp": "nlp_llms", "vector": "nlp_llms", "pandas": "data_handling",
    "excel": "data_handling", "tableau": "data_handling", "fastapi": "apis_backend", "django": "apis_backend",
    "rest": "apis_backend", "react": "frontend_basics", "javascript": "frontend_basics", "html": "frontend_basics",
    "typescript": "frontend_basics", "git": "git_collaboration", "docker": "cloud_devops", "ci/cd": "cloud_devops",
    "kubernetes": "cloud_devops", "aws": "cloud_devops", "communication": "communication",
}  # fmt: skip


def _tagged(user: str, tag: str) -> str:
    found = [m.group(2) for m in _TAG.finditer(user) if m.group(1) == tag]
    return found[-1] if found else ""


def _competency(name: str) -> str:
    low = name.lower()
    return next((c for hint, c in COMPETENCY_HINTS.items() if hint in low), "other")


_HEADERS = {
    "requirements (must have)", "must have", "required skills", "nice to have", "preferred (a plus)",
    "bonus points", "what you will do", "what you'll do", "responsibilities", "about the role",
}  # fmt: skip


def _section_lines(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = "_"
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.isupper() or line.lower() in _HEADERS:
            current = line.lower()
            continue
        sections.setdefault(current, []).append(line)
    return sections


class FakeLLM:
    """Deterministic heuristics with the same interface as LLMClient (fake mode only)."""

    fallbacks = 0

    async def structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        tier: str = "fast",
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> T:
        with trace_llm_call("fake", "fake-heuristic", schema.__name__):
            note_usage(len(user) // 4, 150)
            await asyncio.sleep(0)
            data = getattr(self, f"_{schema.__name__}")(user)
            return schema.model_validate(data)

    def _JobProfile(self, user: str) -> dict[str, Any]:
        text = _tagged(user, "jd")
        sec = _section_lines(text)

        def skills(keys: tuple[str, ...]) -> list[dict[str, str]]:
            out = []
            for name, lines in sec.items():
                if any(k in name for k in keys):
                    out += [
                        {"name": ln.lstrip("- ").strip(), "competency": _competency(ln)}
                        for ln in lines
                        if ln.startswith("-")
                    ]
            return out

        seniority = "mid" if re.search(r"\b3\+ years|mid-level|mid level", text, re.I) else "junior"
        return {
            "title": text.splitlines()[0].split(" - ")[0].strip() if text else "",
            "seniority": seniority,
            "must_have_skills": skills(("must", "required")),
            "nice_to_have_skills": skills(("nice", "preferred", "bonus")),
            "responsibilities": [],
            "tools": [],
            "soft_skills": [],
        }

    def _CVProfile(self, user: str) -> dict[str, Any]:
        text = _tagged(user, "cv")
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        sec = _section_lines(text)
        skills = [s.strip() for ln in sec.get("skills", []) for s in ln.split(",")]
        projects = [
            {"title": ln, "stack": [], "outcome": None} for ln in sec.get("projects", []) if not ln.startswith("-")
        ]
        experience = [
            {
                "role": ln.split(",")[0],
                "org": ln.split(",")[1].strip() if "," in ln else "",
                "duration": None,
                "bullets": [],
            }
            for ln in sec.get("experience", [])
            if not ln.startswith("-")
        ]
        return {
            "name": lines[0] if lines else None,
            "education": [],
            "skills": skills,
            "projects": projects,
            "experience": experience,
            "certifications": [],
        }

    def _EvidenceJudgements(self, user: str) -> dict[str, Any]:
        evidence = _tagged(user, "evidence")
        cv_lines = [ln.strip() for ln in evidence.splitlines() if ln.strip() and not ln.startswith("[E")]
        judgements = []
        for m in re.finditer(r"^- (.+?): check ", user, re.M):
            skill = m.group(1)
            alts = [a.strip().lower() for a in re.split(r"\bor\b|/|\bwith\b|\(|\)", skill) if len(a.strip()) > 1]
            bullet = next(
                (ln for ln in cv_lines if ln.startswith("-") and any(a in ln.lower() for a in alts)),
                None,
            )
            listed = next((ln for ln in cv_lines if any(a in ln.lower() for a in alts)), None)
            if bullet:
                judgements.append(
                    {
                        "skill": skill,
                        "verdict": "strong_evidence",
                        "evidence_quote": bullet.lstrip("- "),
                        "reason": "used",
                    }
                )
            elif listed:
                judgements.append(
                    {
                        "skill": skill,
                        "verdict": "weak_evidence",
                        "evidence_quote": listed,
                        "reason": "listed",
                    }
                )
            else:
                judgements.append(
                    {
                        "skill": skill,
                        "verdict": "no_evidence",
                        "evidence_quote": None,
                        "reason": "none",
                    }
                )
        return {"judgements": judgements}

    def _AnswerEvaluationDraft(self, user: str) -> dict[str, Any]:
        answer = _tagged(user, "transcript")
        words = len(answer.split())
        score = "1" if words < 25 else "2" if words < 40 else "3" if words < 70 else "4" if words < 100 else "5"
        behavioral = "QUESTION TYPE: behavioral" in user

        def crit() -> dict[str, Any]:
            return {"score": score, "justification": "length heuristic", "evidence_quote": None}

        return {
            "relevance": crit(),
            "technical_accuracy": None if behavioral else crit(),
            "depth": crit(),
            "structure": crit(),
            "communication": crit(),
            "what_interviewer_wanted": "-",
            "improved_answer": "-",
            "one_tip": "-",
            "feedback_summary": "-",
            "answer_quality": "complete" if score >= "3" else "shallow",
            "follow_up_question": None,
            "transition": "Thanks.",
        }
