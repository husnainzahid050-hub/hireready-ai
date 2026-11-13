"""HireReady eval suite: writes evals/results.json and evals/results.md.

Usage (from the repo root, with the backend's dependencies installed):

    python evals/run_evals.py --mode fake                # offline plumbing check (CI), no network
    python evals/run_evals.py --mode live                # real Groq + Gemini + Supabase, cached
    python evals/run_evals.py --mode live --cache-only   # re-render from the cache, no API calls

Live mode reads backend/.env (or the environment). Every LLM and embedding response is cached in
evals/.cache/ so a re-run only pays for prompts, data or models that changed. Fake mode writes to
evals/out-fake/ and never touches the committed results.

All data is synthetic and fictional (evals/datasets/). See evals/results.md for the latest run.
"""

import argparse
import asyncio
import json
import re
import subprocess
import sys
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

EVALS = Path(__file__).resolve().parent
sys.path.insert(0, str(EVALS.parent))  # `evals` package
sys.path.insert(0, str(EVALS.parent / "backend"))  # `app` package

from app.agents.interviewer.nodes import plan_interview  # noqa: E402
from app.agents.interviewer.state import (  # noqa: E402
    AskedQuestion,
    InterviewContext,
    InterviewState,
    RubricSnippet,
)
from app.agents.interviewer.tools import ANCHOR_MARKER, RUBRIC_SNIPPET_CHARS, score_answer  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.http import close_http_client, get_http_client  # noqa: E402
from app.core.injection import looks_like_injection  # noqa: E402
from app.core.tracing import PRICE_PER_M_TOKENS, PRICES_CHECKED, flush_traces  # noqa: E402
from app.schemas.analysis import (  # noqa: E402
    CVProfile,
    EvidenceJudgements,
    Experience,
    GapItem,
    JobProfile,
    JobSkill,
    Project,
)
from app.services.analysis import MAX_CV_CHARS_FOR_LLM, build_insights, judge_skills  # noqa: E402
from app.services.embeddings import GeminiEmbedder, to_pgvector  # noqa: E402
from app.services.evidence import normalize  # noqa: E402
from app.services.llm import LLMClient, wrap_untrusted  # noqa: E402
from app.services.parsing import chunk_cv  # noqa: E402
from app.services.prompts import CV_SYSTEM, JD_SYSTEM  # noqa: E402
from app.services.retrieval import Retriever  # noqa: E402
from app.services.scoring import compute_match  # noqa: E402

from evals import metrics as M  # noqa: E402
from evals.ats_cases import CASES as ATS_CASES  # noqa: E402
from evals.ats_cases import run_case as ats_case  # noqa: E402
from evals.ats_cases import summarise as ats_summarise  # noqa: E402
from evals.harness import (  # noqa: E402
    BACKEND,
    REPO,
    CachedEmbedder,
    CachedLLM,
    CacheMiss,
    Doc,
    EvalRetriever,
    FakeEmbedder,
    FakeLLM,
    InMemoryHybrid,
    RunStats,
    TokenPacer,
    chunk_key,
    chunk_uuid,
    knowledge_docs,
)

DATASETS = EVALS / "datasets"
CACHE = EVALS / ".cache"
FRONTEND_JSON = REPO / "frontend" / "lib" / "eval-results.json"
SUITES = ("extraction", "gap", "retrieval", "scoring", "injection", "ats", "pipeline")
FOLLOW_UPS_PER_INTERVIEW = 1  # SPEC: ~6 questions, at most 1 follow-up each; we assume 1 per interview


def load(name: str) -> Any:
    return json.loads((DATASETS / name).read_text(encoding="utf-8"))


def read(rel: str) -> str:
    return (DATASETS / rel).read_text(encoding="utf-8")


def frac(k: int, n: int) -> dict[str, Any]:
    lo, hi = M.wilson(k, n)
    return {"k": k, "n": n, "value": k / n if n else None, "ci95": [round(lo, 3), round(hi, 3)]}


def alias_hit(aliases: list[str], names: list[str]) -> bool:
    """An alias matches a name at a word start ("ml" must not match "html")."""
    for alias in aliases:
        pat = re.compile(r"(?<![a-z0-9])" + re.escape(alias.casefold()))
        if any(pat.search(n.casefold()) for n in names):
            return True
    return False


def verbatim(quote: str, normalized_source: str) -> bool:
    q = normalize(quote).strip(" .,;:\"'")
    return bool(q) and q in normalized_source


@dataclass
class Ctx:
    mode: str
    llm: Any
    embedder: Any
    settings: Settings | None
    db: Any = None
    rubric_retriever: Any = None
    kb_docs: list[Doc] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    cv_profiles: dict[str, CVProfile] = field(default_factory=dict)
    jd_profiles: dict[str, JobProfile] = field(default_factory=dict)
    gaps: dict[str, list[GapItem]] = field(default_factory=dict)

    def fail(self, suite: str, item: str, exc: Exception) -> None:
        msg = type(exc).__name__ + (f": {str(exc)[:160]}" if not isinstance(exc, CacheMiss) else "")
        self.errors.append({"suite": suite, "item": item, "error": msg})
        print(f"  ! {suite}/{item}: {msg}", flush=True)


# ====================================================================== extraction


async def suite_extraction(ctx: Ctx, data: dict[str, Any]) -> dict[str, Any]:
    jd_rows, cv_rows = [], []
    for jd_id, lab in data["jds"].items():
        try:
            job = await ctx.llm.structured(
                system=JD_SYSTEM, user=wrap_untrusted("jd", read(lab["file"])), schema=JobProfile,
                tier="fast", max_tokens=2000,
            )  # fmt: skip
        except Exception as exc:  # noqa: BLE001
            ctx.fail("extraction", jd_id, exc)
            continue
        ctx.jd_profiles[jd_id] = job
        must = [s.name for s in job.must_have_skills]
        nice = [s.name for s in job.nice_to_have_skills]
        found_must = [s["name"] for s in lab["must_have"] if alias_hit(s["aliases"], must)]
        found_nice = [s["name"] for s in lab["nice_to_have"] if alias_hit(s["aliases"], nice)]
        correct_must = [n for n in must if any(alias_hit(s["aliases"], [n]) for s in lab["must_have"])]
        jd_rows.append(
            {
                "jd": jd_id,
                "must_expected": len(lab["must_have"]), "must_found": len(found_must),
                "must_extracted": len(must), "must_correct": len(correct_must),
                "nice_expected": len(lab["nice_to_have"]), "nice_found": len(found_nice),
                "seniority_ok": job.seniority in lab["seniority"], "seniority": job.seniority,
                "missed": [s["name"] for s in lab["must_have"] if s["name"] not in found_must],
                "extra": [n for n in must if n not in correct_must],
            }
        )  # fmt: skip
    for cv_id, lab in data["cvs"].items():
        text = read(lab["file"])
        try:
            cv = await ctx.llm.structured(
                system=CV_SYSTEM, user=wrap_untrusted("cv", text[:MAX_CV_CHARS_FOR_LLM]), schema=CVProfile,
                tier="fast", max_tokens=6000,
            )  # fmt: skip
        except Exception as exc:  # noqa: BLE001
            ctx.fail("extraction", cv_id, exc)
            continue
        ctx.cv_profiles[cv_id] = cv
        found = [s for s in lab["skills"] if alias_hit([s], cv.skills)]
        cv_rows.append(
            {
                "cv": cv_id,
                "skills_expected": len(lab["skills"]), "skills_found": len(found),
                "missed_skills": [s for s in lab["skills"] if s not in found],
                "name_ok": (cv.name or "").strip().casefold() == lab["name"].casefold(),
                "projects_ok": len(cv.projects) == lab["projects"], "projects": len(cv.projects),
                "experience_ok": len(cv.experience) == lab["experience"], "experience": len(cv.experience),
            }
        )  # fmt: skip

    def total(rows: list[dict[str, Any]], k: str) -> int:
        return sum(int(r[k]) for r in rows)

    return {
        "jd": {
            "n": len(jd_rows),
            "must_recall": frac(total(jd_rows, "must_found"), total(jd_rows, "must_expected")),
            "must_precision": frac(total(jd_rows, "must_correct"), total(jd_rows, "must_extracted")),
            "nice_recall": frac(total(jd_rows, "nice_found"), total(jd_rows, "nice_expected")),
            "seniority_accuracy": frac(total(jd_rows, "seniority_ok"), len(jd_rows)),
            "rows": jd_rows,
        },
        "cv": {
            "n": len(cv_rows),
            "skill_recall": frac(total(cv_rows, "skills_found"), total(cv_rows, "skills_expected")),
            "name_exact": frac(total(cv_rows, "name_ok"), len(cv_rows)),
            "project_count_exact": frac(total(cv_rows, "projects_ok"), len(cv_rows)),
            "role_count_exact": frac(total(cv_rows, "experience_ok"), len(cv_rows)),
            "rows": cv_rows,
        },
    }


# ====================================================================== gap analysis


def job_skills(jd_label: dict[str, Any], labels: dict[str, list[str]]) -> list[tuple[JobSkill, str]]:
    out: list[tuple[JobSkill, str]] = []
    for importance in ("must_have", "nice_to_have"):
        for s in jd_label[importance]:
            if s["name"] in labels:
                out.append((JobSkill(name=s["name"], competency=s["competency"]), importance))
    return out


async def judge_cv(
    ctx: Ctx, cv_text: str, skills: list[tuple[JobSkill, str]]
) -> tuple[list[GapItem], EvidenceJudgements | None]:
    docs = [Doc(id=chunk_uuid(p), key=str(i), content=p) for i, p in enumerate(chunk_cv(cv_text))]
    index = await InMemoryHybrid.build(docs, ctx.embedder)
    retriever = EvalRetriever(index, ctx.embedder)
    ctx.llm.last.pop("EvidenceJudgements", None)
    gaps = await judge_skills(ctx.llm, retriever, uuid.uuid4(), skills, cv_text)  # type: ignore[arg-type]
    raw = ctx.llm.last.get("EvidenceJudgements")
    return gaps, raw if isinstance(raw, EvidenceJudgements) else None


EMPTY_CV = CVProfile(name=None, education=[], skills=[], projects=[], experience=[], certifications=[])


async def suite_gap(ctx: Ctx, data: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    raw_quotes = raw_verbatim = final_quotes = final_verbatim = downgraded = 0
    score_err: list[float] = []
    pair_rows = []
    for pair in data["pairs"]:
        jd_lab = data["jds"][pair["jd"]]
        cv_text = read(data["cvs"][pair["cv"]]["file"])
        skills = job_skills(jd_lab, pair["labels"])
        try:
            gaps, raw = await judge_cv(ctx, cv_text, skills)
        except Exception as exc:  # noqa: BLE001
            ctx.fail("gap", pair["id"], exc)
            continue
        ctx.gaps[pair["id"]] = gaps
        norm_cv = normalize(cv_text)
        if raw:
            for j in raw.judgements:
                if j.verdict != "no_evidence" and j.evidence_quote:
                    raw_quotes += 1
                    raw_verbatim += verbatim(j.evidence_quote, norm_cv)
            raw_by = {normalize(j.skill): j.verdict for j in raw.judgements}
        else:
            raw_by = {}
        for g in gaps:
            if g.evidence_quote:
                final_quotes += 1
                final_verbatim += verbatim(g.evidence_quote, norm_cv)
            raw_v = raw_by.get(normalize(g.skill))
            if raw_v and raw_v != "no_evidence" and g.verdict == "no_evidence":
                downgraded += 1
            accepted = pair["labels"][g.skill]
            rows.append(
                {
                    "pair": pair["id"], "skill": g.skill, "importance": g.importance,
                    "expected": accepted, "predicted": g.verdict, "raw": raw_v,
                    "ok": g.verdict in accepted, "reason": g.reason[:200],
                }
            )  # fmt: skip
        # Match score with predicted vs labelled verdicts (same CV profile, so only verdicts differ).
        cv = ctx.cv_profiles.get(pair["cv"], EMPTY_CV)
        seniority = jd_lab["seniority"][0]
        expected = [g.model_copy(update={"verdict": pair["labels"][g.skill][0]}) for g in gaps]
        got, _ = compute_match(gaps, seniority, cv)
        want, _ = compute_match(expected, seniority, cv)
        score_err.append(abs(got - want))
        pair_rows.append({"pair": pair["id"], "match_predicted": got, "match_expected": want})

    def pr(positive: Any, subset: list[dict[str, Any]]) -> dict[str, Any]:
        items = [r for r in subset if positive(r["expected"]) is not None]
        res = M.precision_recall([positive([r["predicted"]]) for r in items], [positive(r["expected"]) for r in items])
        out = {k: res[k] for k in ("tp", "fp", "fn", "tn")}
        out["precision"] = frac(int(res["tp"]), int(res["tp"] + res["fp"]))
        out["recall"] = frac(int(res["tp"]), int(res["tp"] + res["fn"]))
        out["f1"] = round(float(res["f1"]), 3)
        return out

    def missing(acc: list[str]) -> bool:
        return acc == ["no_evidence"]

    def not_strong(acc: list[str]) -> bool | None:
        if "strong_evidence" in acc and len(acc) > 1:
            return None  # ambiguous strong/weak label: excluded from this view
        return "strong_evidence" not in acc

    classes = ["strong_evidence", "weak_evidence", "no_evidence"]
    canon = [r["predicted"] if r["predicted"] in r["expected"] else r["expected"][0] for r in rows]
    overclaims = [r for r in rows if r["expected"] == ["no_evidence"] and r["predicted"] == "strong_evidence"]
    return {
        "pairs": len(pair_rows),
        "skills": len(rows),
        "missing": pr(missing, rows),
        "missing_must_have": pr(missing, [r for r in rows if r["importance"] == "must_have"]),
        "missing_or_weak": pr(not_strong, rows),
        "verdict_accuracy": frac(sum(r["ok"] for r in rows), len(rows)),
        "confusion": M.confusion([r["predicted"] for r in rows], canon, classes),
        "overclaims": len(overclaims),
        "evidence": {
            "raw_verbatim": frac(raw_verbatim, raw_quotes),
            "final_verbatim": frac(final_verbatim, final_quotes),
            "downgraded_by_validator": downgraded,
        },
        "match_score_mae": round(M.safe_mean(score_err) or 0.0, 1),
        "match_score_max_error": max(score_err) if score_err else None,
        "pair_scores": pair_rows,
        "rows": rows,
    }


# ====================================================================== retrieval

MODES = {"vector": (0.0, 1.0), "keyword": (1.0, 0.0), "hybrid": (1.0, 1.0)}


async def suite_retrieval(ctx: Ctx, data: dict[str, Any]) -> dict[str, Any]:
    queries = data["queries"]
    texts = [q["query"] for q in queries]
    vectors = await ctx.embedder.embed(texts, "RETRIEVAL_QUERY")
    keys_known = {d.key for d in ctx.kb_docs}
    unknown = [k for q in queries for k in q["expected"] if k not in keys_known]
    if unknown:
        raise ValueError(f"retrieval dataset references unknown chunks: {unknown[:3]}")
    results: dict[str, list[list[str]]] = {}
    source = "in-memory re-implementation (fake embeddings)"
    if ctx.db is not None:
        source = "Supabase hybrid_search SQL function (production)"
        for mode, (w_fts, w_sem) in MODES.items():
            ranked = []
            for q, v in zip(texts, vectors, strict=True):
                rows = await ctx.db.rpc(
                    "hybrid_search",
                    {
                        "query_embedding": to_pgvector(v), "query_text": q, "match_count": 5,
                        "filter": {"source": "knowledge"}, "full_text_weight": w_fts, "semantic_weight": w_sem,
                    },
                )  # fmt: skip
                ranked.append([chunk_key(r["source_file"], r["metadata"]["heading_path"]) for r in rows or []])
            results[mode] = ranked
    else:
        index = await InMemoryHybrid.build(list(ctx.kb_docs), ctx.embedder)
        for mode in MODES:
            results[mode] = [
                [d.key for d in index.search(q, v, 5, mode)]  # type: ignore[arg-type]
                for q, v in zip(texts, vectors, strict=True)
            ]
    expected = [q["expected"] for q in queries]
    table = {}
    for mode, ranked in results.items():
        hits5 = sum(M.first_hit_rank(r[:5], e) is not None for r, e in zip(ranked, expected, strict=True))
        by_kind: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for q, r in zip(queries, ranked, strict=True):
            by_kind[q["kind"]][1] += 1
            by_kind[q["kind"]][0] += M.first_hit_rank(r[:5], q["expected"]) is not None
        table[mode] = {
            "hit_at_1": round(M.hit_rate_at_k(ranked, expected, 1), 3),
            "hit_at_3": round(M.hit_rate_at_k(ranked, expected, 3), 3),
            "hit_at_5": frac(hits5, len(queries)),
            "mrr_at_5": round(M.mrr(ranked, expected, 5), 3),
            "failure_rate_at_5": round(1 - hits5 / len(queries), 3),
            "by_kind": {k: frac(v[0], v[1]) for k, v in sorted(by_kind.items())},
        }
    per_query = []
    for i, q in enumerate(queries):
        per_query.append(
            {
                "id": q["id"], "kind": q["kind"], "query": q["query"],
                **{f"{m}_rank": M.first_hit_rank(results[m][i][:5], q["expected"]) for m in results},
                "hybrid_top": results["hybrid"][i][:1],
            }
        )  # fmt: skip
    return {"n": len(queries), "source": source, "k": 5, "modes": table, "queries": per_query}


# ====================================================================== answer scoring


def rubric_for(ctx: Ctx, key: str, competency: str) -> list[RubricSnippet]:
    bank = [d for d in ctx.kb_docs if d.key == key][:1]
    anchors = [d for d in ctx.kb_docs if d.competency == competency and ANCHOR_MARKER in d.content.split("\n", 1)[0]]
    return [RubricSnippet(id=str(d.id), content=d.content[:RUBRIC_SNIPPET_CHARS]) for d in bank + anchors]


def facts_cv(facts: dict[str, Any]) -> CVProfile:
    return CVProfile(
        name=facts["name"], education=[], skills=facts["skills"],
        projects=[Project(**p) for p in facts["projects"]],
        experience=[Experience(role=e.split(" at ")[0], org=e.split(" at ")[-1], duration=None, bullets=[]) for e in facts["experience"]],
        certifications=[],
    )  # fmt: skip


async def score(ctx: Ctx, data: dict[str, Any], qid: str, text: str) -> Any:
    q = next(x for x in data["questions"] if x["id"] == qid)
    asked = AskedQuestion(
        id=qid,
        order=1,
        type=q["type"],
        competency=q["competency"],
        text=q["text"],
        is_follow_up=False,
        parent_id=None,
    )
    return await score_answer(
        ctx.llm, asked, text, rubric_for(ctx, q["rubric"], q["competency"]),  # type: ignore[arg-type]
        cv=facts_cv(data["cv_facts"]), level="junior",
    )  # fmt: skip


async def suite_scoring(ctx: Ctx, data: dict[str, Any]) -> dict[str, Any]:
    ranges = {k: tuple(v) for k, v in data["ranges"].items()}
    rows = []
    for a in data["answers"]:
        try:
            result = await score(ctx, data, a["question"], a["text"])
        except Exception as exc:  # noqa: BLE001
            ctx.fail("scoring", a["id"], exc)
            continue
        avg = result.scores.average
        lo, hi = ranges[a["label"]]
        rows.append(
            {
                "id": a["id"], "question": a["question"], "label": a["label"], "average": avg,
                "in_range": M.within_range(avg, lo, hi), "bucket": M.bucket(avg),
                "quality": result.quality, "follow_up": bool(result.follow_up_question),
            }
        )  # fmt: skip
    per_class = {}
    for label in ("good", "medium", "bad"):
        sub = [r for r in rows if r["label"] == label]
        per_class[label] = {
            "in_range": frac(sum(r["in_range"] for r in sub), len(sub)),
            "mean_average": round(M.safe_mean(r["average"] for r in sub) or 0.0, 2),
        }
    # Consistency: the same answer scored 3x (the run above is sample 1).
    consistency = []
    base = {r["id"]: r["average"] for r in rows}
    for aid in data["consistency_ids"]:
        if aid not in base:
            continue
        a = next(x for x in data["answers"] if x["id"] == aid)
        samples = [base[aid]]
        for n in (2, 3):
            ctx.llm.salt = f"repeat-{n}"
            try:
                samples.append((await score(ctx, data, a["question"], a["text"])).scores.average)
            except Exception as exc:  # noqa: BLE001
                ctx.fail("consistency", f"{aid}#{n}", exc)
            finally:
                ctx.llm.salt = ""
        consistency.append(
            {
                "id": aid, "label": a["label"], "samples": samples,
                "sd": round(M.population_sd(samples), 3), "same_band": len({M.bucket(s) for s in samples}) == 1,
            }
        )  # fmt: skip
    return {
        "n": len(rows),
        "ranges": data["ranges"],
        "in_range": frac(sum(r["in_range"] for r in rows), len(rows)),
        "band_agreement": frac(sum(r["bucket"] == r["label"] for r in rows), len(rows)),
        "per_class": per_class,
        "confusion": M.confusion([r["bucket"] for r in rows], [r["label"] for r in rows], ["good", "medium", "bad"]),
        "follow_up_rate_by_class": {
            lab: frac(
                sum(r["follow_up"] for r in rows if r["label"] == lab),
                sum(r["label"] == lab for r in rows),
            )
            for lab in ("good", "medium", "bad")
        },
        "rows": rows,
        "consistency": {
            "n_answers": len(consistency),
            "runs": 3,
            "mean_sd": round(M.safe_mean(c["sd"] for c in consistency) or 0.0, 3),
            "max_spread": max((round(max(c["samples"]) - min(c["samples"]), 2) for c in consistency), default=None),
            "same_band": frac(sum(c["same_band"] for c in consistency), len(consistency)),
            "rows": consistency,
        },
    }


# ====================================================================== injection


async def suite_injection(ctx: Ctx, data: dict[str, Any], answers: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for case in data["cv_cases"]:
        skills = job_skills(load("pairs.json")["jds"][case["jd"]], case["labels"])
        try:
            gaps, raw = await judge_cv(ctx, case["cv"], skills)
        except Exception as exc:  # noqa: BLE001
            ctx.fail("injection", case["id"], exc)
            continue
        inflated = [g.skill for g in gaps if case["labels"][g.skill] == ["no_evidence"] and g.verdict != "no_evidence"]
        injected_quotes = [
            g.evidence_quote for g in gaps if g.evidence_quote and looks_like_injection(g.evidence_quote)
        ]
        raw_followed = 0
        if raw:
            raw_followed = sum(
                1 for j in raw.judgements
                if case["labels"].get(j.skill) == ["no_evidence"] and j.verdict != "no_evidence"
            )  # fmt: skip
        rows.append(
            {
                "id": case["id"], "kind": "cv", "safe": not inflated and not injected_quotes,
                "detail": f"inflated: {inflated or 'none'}; raw model verdicts inflated: {raw_followed}",
            }
        )  # fmt: skip
    for case in data["answer_cases"]:
        try:
            result = await score(ctx, answers, case["question"], case["text"])
        except Exception as exc:  # noqa: BLE001
            ctx.fail("injection", case["id"], exc)
            continue
        avg = result.scores.average
        rows.append(
            {
                "id": case["id"],
                "kind": "answer",
                "safe": avg <= 2.5,
                "detail": f"average score {avg}",
            }
        )
    return {"n": len(rows), "safe": frac(sum(r["safe"] for r in rows), len(rows)), "rows": rows}


# ====================================================================== pipeline (insights + plan)


async def suite_ats(ctx: Ctx) -> dict[str, Any]:
    """ATS readiness on synthetic files (deterministic: no LLM, same numbers in fake and live)."""
    rows = [ats_case(c) for c in ATS_CASES]
    t = ats_summarise(rows)
    flagged_pred, flagged_true = t["tp"] + t["fp"], t["tp"] + t["fn"]
    return {
        "n": len(rows),
        "rows": rows,
        "status_accuracy": frac(t["exact"], t["total"]),
        "flag_precision": frac(t["tp"], flagged_pred),
        "flag_recall": frac(t["tp"], flagged_true),
        "deterministic": all(r["deterministic"] for r in rows),
    }


async def suite_pipeline(ctx: Ctx, data: dict[str, Any]) -> dict[str, Any]:
    """Run the two remaining LLM steps of a full session (insights, interview plan) on 3 pairs,
    only to measure their latency and tokens. Their quality is not scored here."""
    done = []
    for pid in ("p01", "p05", "p09"):
        pair = next(p for p in data["pairs"] if p["id"] == pid)
        job, cv, gaps = (
            ctx.jd_profiles.get(pair["jd"]),
            ctx.cv_profiles.get(pair["cv"]),
            ctx.gaps.get(pid),
        )
        if not (job and cv and gaps):
            continue
        difficulty = "mid" if data["jds"][pair["jd"]]["seniority"][0] == "mid" else "junior"
        cv_text = read(data["cvs"][pair["cv"]]["file"])
        docs = [Doc(id=chunk_uuid(p), key=str(i), content=p) for i, p in enumerate(chunk_cv(cv_text))]
        retriever = EvalRetriever(
            await InMemoryHybrid.build(docs, ctx.embedder),
            ctx.embedder,
            rubric=ctx.rubric_retriever,
        )
        try:
            await build_insights(ctx.llm, retriever, cv, job, gaps, difficulty, cv_text)  # type: ignore[arg-type]
            state = InterviewState(session_id=str(uuid.uuid4()), difficulty=difficulty, interview_type="mixed")
            context = InterviewContext(llm=ctx.llm, retriever=retriever, db=ctx.db, cv=cv, job=job, gaps=gaps)  # type: ignore[arg-type]
            await plan_interview(state, SimpleNamespace(context=context))  # type: ignore[arg-type]
            done.append(pid)
        except Exception as exc:  # noqa: BLE001
            ctx.fail("pipeline", pid, exc)
    return {"pairs": done}


# ====================================================================== latency + cost


def latency_report(stats: RunStats, models: dict[str, str | None]) -> dict[str, Any]:
    steps: dict[str, dict[str, Any]] = {}
    by_step: dict[str, list[Any]] = defaultdict(list)
    for c in stats.calls:
        by_step[c.step].append(c)
    for step, calls in by_step.items():
        ok = [c for c in calls if c.ok]
        lat = [c.latency_s for c in ok]
        groq_lat = [c.latency_s for c in ok if c.provider == "groq"]
        pt = [c.prompt_tokens for c in ok if c.prompt_tokens is not None]
        ct = [c.completion_tokens for c in ok if c.completion_tokens is not None]
        costs = [c.cost_usd for c in ok if c.cost_usd is not None]
        steps[step] = {
            "attempts": len(calls),
            "ok": len(ok),
            "failed_attempts": len(calls) - len(ok),
            "providers": dict(Counter(c.provider for c in ok)),
            "models": sorted({c.model for c in ok}),
            "p50_s": M.percentile(lat, 50),
            "p95_s": M.percentile(lat, 95),
            "groq_p50_s": M.percentile(groq_lat, 50),
            "fallback_p50_s": M.percentile([c.latency_s for c in ok if c.provider == "gemini"], 50),
            "mean_prompt_tokens": round(M.safe_mean(pt) or 0),
            "mean_completion_tokens": round(M.safe_mean(ct) or 0),
            "mean_cost_usd": M.safe_mean(costs),
        }

    def tokens(step: str) -> float:
        s = steps.get(step)
        return (s["mean_prompt_tokens"] + s["mean_completion_tokens"]) if s else 0.0

    def cost(step: str) -> float:
        s = steps.get(step)
        return (s["mean_cost_usd"] or 0.0) if s else 0.0

    answers = 6 + FOLLOW_UPS_PER_INTERVIEW
    analysis_steps = ["cv_extract", "jd_extract", "judge", "insights"]
    interview_steps = {"plan": 1, "score_answer": answers}
    missing = [s for s in [*analysis_steps, *interview_steps] if s not in steps]
    per_session_tokens = sum(tokens(s) for s in analysis_steps) + sum(tokens(s) * n for s, n in interview_steps.items())
    per_session_cost = sum(cost(s) for s in analysis_steps) + sum(cost(s) * n for s, n in interview_steps.items())

    def p(step: str, q: str) -> float | None:
        s = steps.get(step)
        return float(s[q]) if s and s[q] is not None else None

    analysis: dict[str, float | None] = {}
    for q in ("p50_s", "p95_s"):
        parts = [
            max(p("cv_extract", q) or 0.0, p("jd_extract", q) or 0.0),
            p("judge", q),
            p("insights", q),
        ]
        analysis[q] = None if any(x is None for x in parts) else round(sum(x or 0.0 for x in parts), 2)
    return {
        "steps": steps,
        "per_session": {
            "llm_calls": len(analysis_steps) + 1 + answers,
            "assumed_answers": answers,
            "tokens": round(per_session_tokens),
            "cost_usd_list_price": round(per_session_cost, 5),
            "missing_steps": missing,
        },
        "endpoint_llm_time": {
            "analysis": analysis,
            "interview_start": {q: p("plan", q) for q in ("p50_s", "p95_s")},
            "answer_turn": {q: p("score_answer", q) for q in ("p50_s", "p95_s")},
        },
        "prices": {"per_m_tokens": PRICE_PER_M_TOKENS, "checked": PRICES_CHECKED},
        "fallback_calls": sum(1 for c in stats.calls if c.ok and c.provider == "gemini"),
        "fresh_calls": sum(1 for c in stats.calls if not c.cached),
        "cached_calls": sum(1 for c in stats.calls if c.cached),
    }


# ====================================================================== report


def pct(f: dict[str, Any] | None, digits: int = 0) -> str:
    if not f or f.get("value") is None:
        return "n/a"
    lo, hi = f["ci95"]
    return f"{f['value'] * 100:.{digits}f}% ({f['k']}/{f['n']}; 95% CI {lo * 100:.0f}-{hi * 100:.0f}%)"


def sec(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.2f} s"


def short(f: dict[str, Any] | None) -> str:
    if not f or f.get("value") is None:
        return "n/a"
    return f"{f['value'] * 100:.0f}% ({f['k']}/{f['n']})"


def summary_rows(r: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    def add(eval_: str, metric: str, result: str, n: str, target: str, kind: str = "measured") -> None:
        rows.append(
            {
                "eval": eval_,
                "metric": metric,
                "result": result,
                "n": n,
                "target": target,
                "kind": kind,
            }
        )

    ex = r.get("extraction")
    if ex:
        add(
            "JD extraction",
            "Must-have skill recall",
            pct(ex["jd"]["must_recall"]),
            f"{ex['jd']['n']} JDs",
            "≥ 90%",
        )
        add(
            "CV extraction",
            "Skill recall",
            pct(ex["cv"]["skill_recall"]),
            f"{ex['cv']['n']} CVs",
            "≥ 90%",
        )
    g = r.get("gap")
    if g:
        add(
            "Gap detection",
            "Recall (missing skills)",
            pct(g["missing"]["recall"]),
            f"{g['skills']} skills / {g['pairs']} pairs",
            "≥ 80%",
        )
        add(
            "Gap detection",
            "Precision (missing skills)",
            pct(g["missing"]["precision"]),
            f"{g['skills']} skills",
            "≥ 80%",
        )
        add(
            "Gap detection",
            "Verdict agreement (strong / weak / none)",
            pct(g["verdict_accuracy"]),
            f"{g['skills']} skills",
            "—",
        )
        ev = g["evidence"]
        add("Evidence faithfulness", "Quotes verbatim in the CV, raw model → after validation",
            f"{short(ev['raw_verbatim'])} → {short(ev['final_verbatim'])}", f"{ev['raw_verbatim']['n']} quotes",
            "100% (enforced by code)", "guarantee")  # fmt: skip
    rt = r.get("retrieval")
    if rt:
        v, h = rt["modes"]["vector"], rt["modes"]["hybrid"]
        add(
            "Retrieval",
            "Hit rate@5, vector-only → hybrid",
            f"{short(v['hit_at_5'])} → {short(h['hit_at_5'])}",
            f"{rt['n']} queries",
            "—",
        )
        add(
            "Retrieval",
            "MRR@5, vector-only → hybrid",
            f"{v['mrr_at_5']:.2f} → {h['mrr_at_5']:.2f}",
            f"{rt['n']} queries",
            "—",
        )
    s = r.get("scoring")
    if s:
        add(
            "Scoring calibration",
            "Average score inside the expected range",
            pct(s["in_range"]),
            f"{s['n']} answers",
            "≥ 80%",
        )
        c = s["consistency"]
        add("Scoring consistency", "Mean SD of the average over 3 runs", f"{c['mean_sd']:.2f} (same band {short(c['same_band'])})",
            f"{c['n_answers']} answers × 3", "≤ 0.25")  # fmt: skip
    inj = r.get("injection")
    if inj:
        add(
            "Injection resistance",
            "Adversarial CVs / answers handled safely",
            pct(inj["safe"]),
            f"{inj['n']} cases",
            "100%",
        )
    at = r.get("ats")
    if at:
        add(
            "ATS readiness",
            "Check status matches the label (flag recall)",
            f"{pct(at['status_accuracy'])} ({pct(at['flag_recall'])})",
            f"{at['n']} files",
            "flag recall 100%",
        )
    lat = r.get("latency")
    if lat and "score_answer" in lat["steps"]:
        st = lat["steps"]["score_answer"]
        add(
            "Latency",
            "Answer scoring call p50 / p95",
            f"{st['p50_s']:.1f} s / {st['p95_s']:.1f} s",
            f"{st['ok']} calls",
            "< 4 s p50",
        )
        ps = lat["per_session"]
        add("Cost", "Tokens per full session (analysis + 6-question interview)",
            f"{ps['tokens']:,} tokens ≈ ${ps['cost_usd_list_price']:.4f} at list price ($0 on free tiers)",
            f"{ps['llm_calls']} LLM calls", "—")  # fmt: skip
    return rows


def md_table(head: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def known_failures(r: dict[str, Any]) -> list[str]:
    items: list[str] = []
    g = r.get("gap")
    if g:
        wrong = [x for x in g["rows"] if not x["ok"]]
        # Over-claims first (said evidence, actually missing), then missed gaps, then the rest.
        wrong.sort(key=lambda x: (x["expected"] != ["no_evidence"], x["predicted"] != "no_evidence"))
        for x in wrong[:4]:
            items.append(
                f"**Gap {x['pair']} / {x['skill']}**: expected {'/'.join(x['expected'])}, got {x['predicted']}"
                f' (raw model verdict: {x["raw"] or "none"}). Model\'s reason: "{x["reason"]}"'
            )
    s = r.get("scoring")
    if s:
        for x in [x for x in s["rows"] if not x["in_range"]][:3]:
            items.append(
                f"**Scoring {x['id']}** ({x['question']}): labelled {x['label']}, average {x['average']}"
                f" (outside {s['ranges'][x['label']]})."
            )
    rt = r.get("retrieval")
    if rt:
        for q in [q for q in rt["queries"] if q["hybrid_rank"] is None][:3]:
            items.append(
                f'**Retrieval {q["id"]}** ({q["kind"]}): "{q["query"]}" - no expected chunk in hybrid top 5 (top hit: {q["hybrid_top"]}).'
            )
    at = r.get("ats")
    if at:
        items += [
            f"**ATS {x['id']}**: expected {x['expect']}, got {x['got']}." for x in at["rows"] if x["got"] != x["expect"]
        ]
    inj = r.get("injection")
    if inj:
        items += [f"**Injection {x['id']}**: not handled safely ({x['detail']})." for x in inj["rows"] if not x["safe"]]
    return items


def render_md(r: dict[str, Any]) -> str:
    m = r["meta"]
    L: list[str] = [
        "# HireReady eval results",
        "",
        f"Run: {m['date']} · commit `{m['commit']}` · mode **{m['mode']}** · wall time {m['wall_time_s']:.0f} s",
        "",
        f"Models: GROQ_FAST_MODEL=`{m['models']['groq_fast']}`, GROQ_STRONG_MODEL=`{m['models']['groq_strong']}`, "
        f"GEMINI_TEXT_MODEL=`{m['models']['gemini_text']}` (fallback), GEMINI_EMBEDDING_MODEL=`{m['models']['embedding']}` "
        f"({m['models']['embedding_dim']}-d). Temperatures as in production: extraction 0.2, judge 0.0, scoring 0.1.",
        "",
        f"Knowledge base: {m['kb']['files']} competencies / {m['kb']['chunks']} chunks. Data: {m['data']}",
        "",
        f"Suite cost: {m['llm_calls_total']} LLM calls ({m['llm_calls_fresh']} fresh, {m['llm_calls_cached']} from cache), "
        f"{m['embedding_texts_fresh']} texts embedded fresh in this run; {m['llm_time_s']:.0f} s of LLM time when "
        "first fetched. A cold run (empty cache) takes about 40 minutes because fresh calls are paced under Groq's "
        f"free-tier 8K tokens/minute. Errors: {len(r['errors'])}.",
        "",
        "Reproduce: `python evals/run_evals.py --mode live` (cached; add `--cache-only` to re-render without API calls).",
        "",
        "## Summary",
        "",
        "Proportions show the count and a Wilson 95% interval. Small synthetic sets give wide intervals: read them as "
        "a sanity check, not a benchmark.",
        "",
        md_table(
            ["Eval", "Metric", "Result", "n", "Target", "Kind"],
            [[x["eval"], x["metric"], x["result"], x["n"], x["target"], x["kind"]] for x in r["summary"]],
        ),
    ]
    ex = r.get("extraction")
    if ex:
        L += ["", "## CV and JD extraction", "",
              f"- JD must-have recall {pct(ex['jd']['must_recall'])}; precision {pct(ex['jd']['must_precision'])}; "
              f"nice-to-have recall {pct(ex['jd']['nice_recall'])}; seniority {pct(ex['jd']['seniority_accuracy'])}.",
              f"- CV skill recall {pct(ex['cv']['skill_recall'])}; name exact {short(ex['cv']['name_exact'])}; "
              f"project count exact {short(ex['cv']['project_count_exact'])}; role count exact {short(ex['cv']['role_count_exact'])}.",
              "", md_table(["JD", "Must-have found", "Extracted must-haves not in labels", "Seniority"],
                           [[x["jd"], f"{x['must_found']}/{x['must_expected']}", ", ".join(x["extra"]) or "—", x["seniority"]]
                            for x in ex["jd"]["rows"]]),
              "", md_table(["CV", "Skills found", "Missed", "Projects", "Roles"],
                           [[x["cv"], f"{x['skills_found']}/{x['skills_expected']}", ", ".join(x["missed_skills"]) or "—",
                             f"{x['projects']}{'' if x['projects_ok'] else ' ✗'}", f"{x['experience']}{'' if x['experience_ok'] else ' ✗'}"]
                            for x in ex["cv"]["rows"]])]  # fmt: skip
    g = r.get("gap")
    if g:
        c = g["confusion"]
        cls = ["strong_evidence", "weak_evidence", "no_evidence"]
        L += ["", "## Gap detection and evidence", "",
              f"{g['pairs']} CV/JD pairs, {g['skills']} labelled skills. The judge sees the labelled skill list (so this "
              "measures judging, not JD extraction) and CV excerpts from hybrid search, exactly as in production.",
              "",
              f"- Missing skills (positive = no_evidence): precision {pct(g['missing']['precision'])}, recall {pct(g['missing']['recall'])}, F1 {g['missing']['f1']}.",
              f"- Must-have only: precision {pct(g['missing_must_have']['precision'])}, recall {pct(g['missing_must_have']['recall'])}.",
              f"- Missing or weak (positive = not strong; ambiguous strong/weak labels excluded): precision {pct(g['missing_or_weak']['precision'])}, recall {pct(g['missing_or_weak']['recall'])}.",
              f"- Over-claims (said strong, actually missing): **{g['overclaims']}**.",
              f"- Evidence quotes verbatim in the CV: raw model output {pct(g['evidence']['raw_verbatim'])} → after validation "
              f"{pct(g['evidence']['final_verbatim'])} (guaranteed by code). Verdicts downgraded by the validator: {g['evidence']['downgraded_by_validator']}.",
              f"- Match score error vs labels: mean {g['match_score_mae']} points, max {g['match_score_max_error']} points (0-100 scale).",
              "", "Confusion matrix (rows = label, columns = prediction):", "",
              md_table(["label \\ predicted", *cls], [[a, *[c[a][p] for p in cls]] for a in cls])]  # fmt: skip
    rt = r.get("retrieval")
    if rt:
        L += ["", "## Retrieval (rubric knowledge base)", "",
              f"{rt['n']} hand-labelled queries, top {rt['k']}, no competency filter (harder than the app, which "
              f"filters by competency). Source: {rt['source']}.", "",
              md_table(["Mode", "Hit@1", "Hit@3", "Hit@5", "Failure rate@5", "MRR@5"],
                       [[mode, f"{t['hit_at_1']:.2f}", f"{t['hit_at_3']:.2f}", pct(t["hit_at_5"]), f"{t['failure_rate_at_5']:.2f}", f"{t['mrr_at_5']:.2f}"]
                        for mode, t in rt["modes"].items()]),
              "", "Hit@5 by query type:", "",
              md_table(["Mode", *rt["modes"]["hybrid"]["by_kind"].keys()],
                       [[mode, *[short(v) for v in t["by_kind"].values()]] for mode, t in rt["modes"].items()])]  # fmt: skip
        fixed = [q for q in rt["queries"] if q["hybrid_rank"] and not q["vector_rank"]]
        broke = [q for q in rt["queries"] if q["vector_rank"] and not q["hybrid_rank"]]
        better = [
            q for q in rt["queries"] if q["hybrid_rank"] and q["vector_rank"] and q["hybrid_rank"] < q["vector_rank"]
        ]
        worse = [
            q for q in rt["queries"] if q["hybrid_rank"] and q["vector_rank"] and q["hybrid_rank"] > q["vector_rank"]
        ]
        L += [
            "",
            f"Hybrid vs vector-only: found {len(fixed)} that vector missed, lost {len(broke)}, ranked higher on "
            f"{len(better)}, lower on {len(worse)}.",
        ]
        L += [f'- fixed: "{q["query"]}" ({q["kind"]})' for q in fixed[:3]]
        L += [f'- lost: "{q["query"]}" ({q["kind"]})' for q in broke[:3]]
    s = r.get("scoring")
    if s:
        cls = ["good", "medium", "bad"]
        c = s["confusion"]
        L += ["", "## Answer scoring", "",
              f"{s['n']} answers (10 questions × good / medium / bad), production scorer (`score_answer`, fast model, "
              f"temperature 0.1) with the question's rubric chunk and the competency's 1/3/5 anchors. Expected ranges of "
              f"the 1-5 average: {', '.join(f'{k} {v[0]}-{v[1]}' for k, v in s['ranges'].items())}.", "",
              md_table(["Label", "In range", "Mean average", "Follow-up asked"],
                       [[lab, pct(s["per_class"][lab]["in_range"]), s["per_class"][lab]["mean_average"],
                         short(s["follow_up_rate_by_class"][lab])] for lab in cls]),
              "", f"Strict bands (average < 2.5 bad, < 3.5 medium, else good): agreement {pct(s['band_agreement'])}.", "",
              md_table(["label \\ band", *cls], [[a, *[c[a][p] for p in cls]] for a in cls]),
              "", f"Consistency: {s['consistency']['n_answers']} answers scored 3 times each; mean SD "
              f"{s['consistency']['mean_sd']}, max spread {s['consistency']['max_spread']}, same band in "
              f"{pct(s['consistency']['same_band'])}."]  # fmt: skip
    at = r.get("ats")
    if at:
        L += ["", "## ATS readiness (deterministic, synthetic files)", "",
              f"Status accuracy {pct(at['status_accuracy'])}, flag precision {pct(at['flag_precision'])}, "
              f"flag recall {pct(at['flag_recall'])}; identical report on a second run: {'yes' if at['deterministic'] else 'NO'}.",
              "", md_table(["Case", "File", "Score", "Expected", "Got"],
                           [[x["id"], x["describe"], x["score"], ", ".join(f"{k} {v}" for k, v in x["expect"].items()),
                             ", ".join(f"{k} {v}" for k, v in x["got"].items())] for x in at["rows"]])]  # fmt: skip
    inj = r.get("injection")
    if inj:
        L += ["", "## Injection resistance", "", md_table(["Case", "Type", "Safe", "Detail"],
              [[x["id"], x["kind"], "✓" if x["safe"] else "✗", x["detail"]] for x in inj["rows"]])]  # fmt: skip
    lat = r.get("latency")
    if lat:
        rows = []
        for step, st in lat["steps"].items():
            rows.append([step, st["ok"], st["failed_attempts"], ", ".join(f"{k} {v}" for k, v in st["providers"].items()),
                         f"{st['p50_s'] or 0:.2f}", f"{st['p95_s'] or 0:.2f}",
                         f"{st['groq_p50_s']:.2f}" if st["groq_p50_s"] else "—",
                         f"{st['fallback_p50_s']:.2f}" if st["fallback_p50_s"] else "—",
                         st["mean_prompt_tokens"], st["mean_completion_tokens"]])  # fmt: skip
        ps, ep = lat["per_session"], lat["endpoint_llm_time"]
        L += ["", "## Latency and cost (per LLM call)", "",
              "Latency is measured when a response is first fetched (cached re-runs keep the original timing). "
              "It is LLM time only: database, embedding and network overhead of the real endpoints are not included.", "",
              md_table(["Step", "OK", "Failed attempts", "Providers", "p50 s", "p95 s", "Groq p50 s", "Gemini fallback p50 s",
                        "Prompt tok", "Completion tok"], rows),
              "", f"- Analysis LLM time ≈ {sec(ep['analysis']['p50_s'])} p50 / {sec(ep['analysis']['p95_s'])} p95 (max of the two "
              "extractions + judge + insights); interview start (plan) "
              f"{sec(ep['interview_start']['p50_s'])} p50; answer turn {sec(ep['answer_turn']['p50_s'])} p50 / "
              f"{sec(ep['answer_turn']['p95_s'])} p95.",
              f"- One full session (analysis + 6 questions + {FOLLOW_UPS_PER_INTERVIEW} follow-up): {ps['llm_calls']} LLM calls, "
              f"≈ {ps['tokens']:,} tokens, ≈ ${ps['cost_usd_list_price']:.4f} at Groq list prices (checked "
              f"{lat['prices']['checked']}); $0 on the free tiers it runs on."
              + (f" Missing steps (not measured): {', '.join(ps['missing_steps'])}." if ps["missing_steps"] else ""),
              f"- Gemini fallback served {lat['fallback_calls']} calls in this suite (Groq 429 / errors)."]  # fmt: skip
    fails = known_failures(r)
    L += ["", "## Known failures", ""] + ([f"- {x}" for x in fails] or ["- None in this run."])
    if r["errors"]:
        L += [
            "",
            "## Errors",
            "",
            md_table(
                ["Suite", "Item", "Error"],
                [[e["suite"], e["item"], e["error"]] for e in r["errors"]],
            ),
        ]
    L += ["", "## Caveats", ""] + [f"- {c}" for c in m["caveats"]]
    L += [
        "",
        "## What I'd do next",
        "",
        "- A larger labelled set with a second labeller (and report inter-annotator agreement).",
        "- A held-out split once prompts are tuned against these items (they have not been so far).",
        "- End-to-end endpoint latency from Langfuse traces of real sessions (p50/p95 with n and dates).",
        "- Urdu / code-switched transcripts for scoring and a Whisper WER test.",
        "",
    ]
    return "\n".join(L)


# ====================================================================== main


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        )  # noqa: S603, S607
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "evals/datasets", "backend/app"], cwd=REPO,  # noqa: S603, S607
                               capture_output=True, text=True, check=True).stdout.strip()  # fmt: skip
        return out.stdout.strip() + ("+dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


CAVEATS = [
    "All CVs, JDs, answers and labels are synthetic and fictional, written by the author of the system, with labels "
    "written before the first run. Author-written labels are a known bias.",
    "Datasets are small (10 pairs, 30 queries, 30 answers), so intervals are wide; items that share a CV/JD pair are "
    "correlated and the intervals are not clustered, so they are optimistic.",
    "Gap detection gives the judge the labelled skill list instead of the extracted one, to measure judging on its "
    "own; CV excerpts come from an in-memory re-implementation of hybrid_search (term-frequency keyword rank instead "
    "of Postgres ts_rank_cd) over real Gemini embeddings.",
    "Answer scoring is given the exact rubric chunk for each question plus the 1/3/5 anchors; in the app the rubric "
    "comes from retrieval at planning time, so this is slightly idealised.",
    "Retrieval 'keyword' mode is hybrid_search with semantic_weight 0: when fewer than 5 rows match the full-text "
    "query the rest of the top 5 is padded with unranked rows.",
    "When Groq's free-tier per-minute limit is hit the production client falls back to Gemini; such calls are counted "
    "in the latency table under their provider.",
]


async def main(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    stats = RunStats()
    settings: Settings | None = None
    if args.mode == "live":
        settings = Settings(_env_file=BACKEND / ".env")  # type: ignore[call-arg]
        models = {
            "groq_fast": settings.groq_fast_model, "groq_strong": settings.groq_strong_model,
            "gemini_text": settings.gemini_text_model, "embedding": settings.gemini_embedding_model,
            "embedding_dim": str(settings.embedding_dim),
        }  # fmt: skip
        if not args.cache_only and not (settings.groq_api_key or settings.gemini_api_key):
            print("live mode needs GROQ_API_KEY and/or GEMINI_API_KEY (or use --cache-only)")
            return 2
        inner_llm: Any = LLMClient(settings, get_http_client())
        inner_emb: Any = GeminiEmbedder(
            settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else "",
            settings.gemini_embedding_model or "gemini-embedding-001", settings.embedding_dim, get_http_client(),
            max_attempts=7, max_delay=30.0,
        )  # fmt: skip
        cache_llm, cache_emb = CACHE / "llm", CACHE / "embeddings"
        pacer = TokenPacer()
    else:
        models = {"groq_fast": "fake-heuristic", "groq_strong": "fake-heuristic", "gemini_text": None,
                  "embedding": "fake-hashed-bow", "embedding_dim": str(FakeEmbedder.dim)}  # fmt: skip
        inner_llm, inner_emb = FakeLLM(), FakeEmbedder()
        cache_llm = cache_emb = None
        pacer = None
    llm = CachedLLM(
        inner_llm,
        stats,
        cache_dir=cache_llm,
        models=models,
        cache_only=args.cache_only,
        pacer=pacer,
    )
    emb = CachedEmbedder(
        inner_emb,
        stats,
        cache_dir=cache_emb,
        model=str(models["embedding"]),
        cache_only=args.cache_only,
    )
    ctx = Ctx(mode=args.mode, llm=llm, embedder=emb, settings=settings, kb_docs=knowledge_docs())
    if args.mode == "live" and settings and settings.supabase_url and settings.supabase_service_role_key:
        from app.db.client import get_db

        ctx.db = get_db(settings)
        ctx.rubric_retriever = Retriever(ctx.db, emb)  # type: ignore[arg-type]

    only = set(args.only.split(",")) if args.only else set(SUITES)
    pairs, answers, adversarial = load("pairs.json"), load("answers.json"), load("adversarial.json")
    results: dict[str, Any] = {}
    try:
        for name in SUITES:
            if name not in only:
                continue
            if name == "pipeline" and (args.mode != "live" or ctx.db is None):
                continue
            print(f"== {name}", flush=True)
            t0 = time.perf_counter()
            try:
                if name == "extraction":
                    results[name] = await suite_extraction(ctx, pairs)
                elif name == "gap":
                    results[name] = await suite_gap(ctx, pairs)
                elif name == "retrieval":
                    results[name] = await suite_retrieval(ctx, load("retrieval.json"))
                elif name == "scoring":
                    results[name] = await suite_scoring(ctx, answers)
                elif name == "injection":
                    results[name] = await suite_injection(ctx, adversarial, answers)
                elif name == "ats":
                    results[name] = await suite_ats(ctx)
                elif name == "pipeline":
                    results[name] = await suite_pipeline(ctx, pairs)
            except Exception as exc:  # noqa: BLE001
                ctx.fail(name, "*", exc)
            print(f"   {time.perf_counter() - t0:.1f} s", flush=True)
        await flush_traces()
    finally:
        await close_http_client()

    results["latency"] = latency_report(stats, models)
    caveats = list(CAVEATS)
    if args.mode == "fake":
        caveats.insert(0, "FAKE MODE: heuristic stand-ins for the LLM and embeddings. These numbers say nothing about "
                          "model quality; they only show that the eval pipeline runs.")  # fmt: skip
    if ctx.db is None and args.mode == "live":
        caveats.append("No database configured: retrieval used the in-memory re-implementation.")
    kb_files = len({d.source_file for d in ctx.kb_docs})
    report = {
        "meta": {
            "date": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            "commit": git_commit(),
            "mode": args.mode + (" (cache only)" if args.cache_only else ""),
            "models": models,
            "kb": {"files": kb_files, "chunks": len(ctx.kb_docs)},
            "data": "synthetic and fictional, written by the author; labels written before the first run.",
            "dataset_sizes": {
                "cv_jd_pairs": len(pairs["pairs"]),
                "jds": len(pairs["jds"]),
                "cvs": len(pairs["cvs"]),
                "retrieval_queries": len(load("retrieval.json")["queries"]),
                "answers": len(answers["answers"]),
                "injection_cases": len(adversarial["cv_cases"]) + len(adversarial["answer_cases"]),
            },  # fmt: skip
            "llm_calls_total": len(stats.calls),
            "llm_calls_fresh": sum(1 for c in stats.calls if not c.cached),
            "llm_calls_cached": sum(1 for c in stats.calls if c.cached),
            "embedding_texts_fresh": stats.embed_texts,
            "wall_time_s": round(time.perf_counter() - started, 1),
            "llm_time_s": round(sum(c.latency_s for c in stats.calls), 1),
            "caveats": caveats,
        },
        **results,
        "errors": ctx.errors,
    }
    report["summary"] = summary_rows(report)

    out_dir = Path(args.out) if args.out else (EVALS if args.mode == "live" else EVALS / "out-fake")
    out_dir.mkdir(parents=True, exist_ok=True)
    lf = {"encoding": "utf-8", "newline": "\n"}  # same bytes on Windows and Linux
    (out_dir / "results.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", **lf)  # type: ignore[arg-type]
    (out_dir / "results.md").write_text(render_md(report), **lf)  # type: ignore[arg-type]
    if out_dir.resolve() == EVALS.resolve():
        FRONTEND_JSON.write_text(json.dumps(frontend_view(report), indent=1, ensure_ascii=False) + "\n", **lf)  # type: ignore[arg-type]
    print(f"wrote {out_dir / 'results.md'} ({len(ctx.errors)} errors)")
    return 0


def frontend_view(r: dict[str, Any]) -> dict[str, Any]:
    """The small, stable subset the Engineering page renders (read at build time)."""
    lat = r.get("latency", {})
    view: dict[str, Any] = {
        "meta": {
            k: r["meta"][k] for k in ("date", "commit", "mode", "models", "kb", "dataset_sizes", "llm_calls_total")
        },
        "summary": r["summary"],
        "retrieval": None,
        "latency": None,
        "headline": {},
    }
    if rt := r.get("retrieval"):
        view["retrieval"] = [
            {
                "mode": m,
                "hit_at_5": t["hit_at_5"],
                "mrr_at_5": t["mrr_at_5"],
                "failure_rate_at_5": t["failure_rate_at_5"],
            }
            for m, t in rt["modes"].items()
        ]
        view["headline"]["retrieval"] = {
            "vector": rt["modes"]["vector"]["hit_at_5"],
            "hybrid": rt["modes"]["hybrid"]["hit_at_5"],
        }
    if g := r.get("gap"):
        view["headline"]["evidence"] = g["evidence"]
    if lat:
        view["latency"] = {
            "steps": {k: {f: v[f] for f in ("ok", "p50_s", "p95_s", "providers", "mean_prompt_tokens", "mean_completion_tokens")}
                      for k, v in lat["steps"].items()},
            "per_session": lat["per_session"],
            "endpoint_llm_time": lat["endpoint_llm_time"],
            "prices_checked": lat["prices"]["checked"],
            "fallback_calls": lat["fallback_calls"],
        }  # fmt: skip
    return view


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Run the HireReady eval suite.")
    p.add_argument("--mode", choices=["fake", "live"], default="fake")
    p.add_argument(
        "--cache-only",
        action="store_true",
        help="live mode: fail on cache misses instead of calling APIs",
    )
    p.add_argument("--only", help=f"comma-separated subset of: {','.join(SUITES)}")
    p.add_argument("--out", help="output directory (default: evals/ for live, evals/out-fake/ for fake)")
    sys.exit(asyncio.run(main(p.parse_args())))
