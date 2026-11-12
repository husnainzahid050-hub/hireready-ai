"""Eval metric functions (evals/metrics.py) and the dataset files' integrity."""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from evals import metrics as M  # noqa: E402
from evals.harness import InMemoryHybrid, chunk_key, knowledge_docs, terms  # noqa: E402

DATASETS = REPO / "evals" / "datasets"


def test_first_hit_rank() -> None:
    assert M.first_hit_rank(["a", "b", "c"], ["c"]) == 3
    assert M.first_hit_rank(["a", "b"], ["x", "b"]) == 2
    assert M.first_hit_rank(["a"], ["z"]) is None
    assert M.first_hit_rank([], ["z"]) is None


def test_hit_rate_at_k() -> None:
    results = [["a", "b", "c"], ["x", "y", "z"], ["q", "w", "e"]]
    expected = [["c"], ["x"], ["nope"]]
    assert M.hit_rate_at_k(results, expected, 3) == pytest.approx(2 / 3)
    assert M.hit_rate_at_k(results, expected, 1) == pytest.approx(1 / 3)
    assert M.hit_rate_at_k([], [], 5) == 0.0


def test_mrr() -> None:
    results = [["a", "b", "c"], ["x", "y"], ["q"]]
    expected = [["c"], ["x"], ["nope"]]
    assert M.mrr(results, expected) == pytest.approx((1 / 3 + 1 + 0) / 3)
    # Cut-off at k: a hit at rank 3 does not count for MRR@2.
    assert M.mrr(results, expected, k=2) == pytest.approx(1 / 3)
    assert M.mrr([], []) == 0.0


def test_precision_recall() -> None:
    pred = [True, True, False, False, True]
    actual = [True, False, True, False, True]
    res = M.precision_recall(pred, actual)
    assert (res["tp"], res["fp"], res["fn"], res["tn"]) == (2, 1, 1, 1)
    assert res["precision"] == pytest.approx(2 / 3)
    assert res["recall"] == pytest.approx(2 / 3)
    assert res["f1"] == pytest.approx(2 / 3)
    # Nothing to find, nothing flagged: perfect by convention.
    assert M.precision_recall([False], [False])["precision"] == 1.0
    # Nothing flagged but something missed: precision 0.
    assert M.precision_recall([False], [True])["precision"] == 0.0


def test_calibration_and_bands() -> None:
    scores = [4.2, 3.0, 1.4, 2.6]
    ranges = [(3.4, 5.0), (2.0, 3.8), (1.0, 2.5), (1.0, 2.5)]
    assert M.calibration_agreement(scores, ranges) == pytest.approx(3 / 4)
    assert M.within_range(2.5, 1.0, 2.5)  # inclusive bounds
    assert [M.bucket(s) for s in (1.0, 2.49, 2.5, 3.49, 3.5, 5.0)] == [
        "bad", "bad", "medium", "medium", "good", "good",
    ]  # fmt: skip
    assert M.label_agreement(scores, ["good", "medium", "bad", "bad"]) == pytest.approx(3 / 4)
    table = M.confusion(["good", "bad"], ["good", "medium"], ["good", "medium", "bad"])
    assert table["good"]["good"] == 1 and table["medium"]["bad"] == 1
    assert M.calibration_agreement([], []) == 0.0


def test_wilson_interval() -> None:
    lo, hi = M.wilson(27, 30)
    assert 0.73 < lo < 0.75 and 0.96 < hi < 0.98  # the brief's "90% is really 74-97%"
    lo, hi = M.wilson(10, 10)
    assert hi == 1.0 and 0.70 < lo < 0.73  # well-behaved at 100%
    assert M.wilson(0, 0) == (0.0, 1.0)


def test_spread_and_percentiles() -> None:
    assert M.population_variance([2.0, 2.0, 2.0]) == 0.0
    assert M.population_sd([1.0, 3.0]) == pytest.approx(1.0)
    assert M.population_sd([4.0]) == 0.0
    assert M.percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.0
    assert M.percentile([1.0, 2.0, 3.0, 4.0], 95) == 4.0
    assert M.percentile([], 50) is None
    assert M.safe_mean([]) is None


def test_terms_and_rrf_search() -> None:
    assert terms("The Merging of branches") == ["merg", "branch"]

    async def run() -> list[str]:
        from evals.harness import Doc, FakeEmbedder, chunk_uuid

        docs = [
            Doc(id=chunk_uuid(t), key=t, content=t)
            for t in ("git merge conflict", "sql having", "docker")
        ]
        index = await InMemoryHybrid.build(docs, FakeEmbedder())
        [v] = await FakeEmbedder().embed(["merge conflict"], "RETRIEVAL_QUERY")
        return [d.key for d in index.search("merge conflict", v, k=2)]

    import asyncio

    assert asyncio.run(run())[0] == "git merge conflict"


def test_datasets_are_consistent() -> None:
    keys = {d.key for d in knowledge_docs()}
    retrieval = json.loads((DATASETS / "retrieval.json").read_text(encoding="utf-8"))
    assert len(retrieval["queries"]) == 30
    for q in retrieval["queries"]:
        assert q["expected"] and set(q["expected"]) <= keys, q["id"]

    pairs = json.loads((DATASETS / "pairs.json").read_text(encoding="utf-8"))
    assert len(pairs["pairs"]) == 10
    for p in pairs["pairs"]:
        jd = pairs["jds"][p["jd"]]
        names = {s["name"] for s in jd["must_have"] + jd["nice_to_have"]}
        assert set(p["labels"]) == names, p["id"]
        for acc in p["labels"].values():
            # Ambiguity only between strong and weak, so the gap label stays crisp.
            assert acc == ["no_evidence"] or "no_evidence" not in acc
        assert (DATASETS / pairs["cvs"][p["cv"]]["file"]).exists()

    answers = json.loads((DATASETS / "answers.json").read_text(encoding="utf-8"))
    assert len(answers["answers"]) == 30
    qids = {q["id"] for q in answers["questions"]}
    for q in answers["questions"]:
        assert q["rubric"] in keys
    for a in answers["answers"]:
        assert a["question"] in qids and a["label"] in answers["ranges"]


def test_chunk_key() -> None:
    assert chunk_key("sql.md", ["SQL", "Question bank", "Junior", "Q?"]) == "sql.md#Q?"
