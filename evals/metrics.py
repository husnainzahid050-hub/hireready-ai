"""Pure metric functions for the eval suite (no I/O, fully unit-tested in backend/tests)."""

import math
import statistics
from collections.abc import Iterable, Sequence


def first_hit_rank(ranked: Sequence[str], expected: Iterable[str]) -> int | None:
    """1-based rank of the first relevant item, or None if none was returned."""
    wanted = set(expected)
    for i, item in enumerate(ranked, start=1):
        if item in wanted:
            return i
    return None


def hit_rate_at_k(results: Sequence[Sequence[str]], expected: Sequence[Iterable[str]], k: int) -> float:
    """Share of queries with at least one relevant item in the top k."""
    if not results:
        return 0.0
    hits = 0
    for ranked, exp in zip(results, expected, strict=True):
        rank = first_hit_rank(ranked[:k], exp)
        hits += rank is not None
    return hits / len(results)


def mrr(results: Sequence[Sequence[str]], expected: Sequence[Iterable[str]], k: int | None = None) -> float:
    """Mean reciprocal rank of the first relevant item (0 for a miss), optionally cut at k."""
    if not results:
        return 0.0
    total = 0.0
    for ranked, exp in zip(results, expected, strict=True):
        rank = first_hit_rank(ranked[:k] if k else ranked, exp)
        total += 1.0 / rank if rank else 0.0
    return total / len(results)


def precision_recall(predicted: Iterable[bool], actual: Iterable[bool]) -> dict[str, float | int]:
    """Binary precision / recall / F1 (positive = True). Empty denominators give 1.0 by convention
    only when there is nothing to find AND nothing was flagged; otherwise 0.0."""
    tp = fp = fn = tn = 0
    for p, a in zip(predicted, actual, strict=True):
        if p and a:
            tp += 1
        elif p and not a:
            fp += 1
        elif a and not p:
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if tp + fp else (1.0 if fn == 0 else 0.0)
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }


def within_range(value: float, low: float, high: float) -> bool:
    return low <= value <= high


def calibration_agreement(scores: Sequence[float], ranges: Sequence[tuple[float, float]]) -> float:
    """Share of scores inside their expected [low, high] range."""
    if not scores:
        return 0.0
    ok = sum(within_range(s, lo, hi) for s, (lo, hi) in zip(scores, ranges, strict=True))
    return ok / len(scores)


def bucket(score: float, cuts: tuple[float, float] = (2.5, 3.5)) -> str:
    """Average score -> bad / medium / good (strict, non-overlapping cut-offs)."""
    if score < cuts[0]:
        return "bad"
    if score < cuts[1]:
        return "medium"
    return "good"


def label_agreement(scores: Sequence[float], labels: Sequence[str]) -> float:
    if not scores:
        return 0.0
    return sum(bucket(s) == lab for s, lab in zip(scores, labels, strict=True)) / len(scores)


def confusion(predicted: Sequence[str], actual: Sequence[str], classes: Sequence[str]) -> dict[str, dict[str, int]]:
    """confusion[actual][predicted] counts."""
    table = {a: dict.fromkeys(classes, 0) for a in classes}
    for p, a in zip(predicted, actual, strict=True):
        table[a][p] += 1
    return table


def population_variance(values: Sequence[float]) -> float:
    return statistics.pvariance(values) if len(values) > 1 else 0.0


def percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile (q in 0..100); None for no data."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion (well-behaved at 0% and 100%, unlike +/- 1.96 SE)."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def population_sd(values: Sequence[float]) -> float:
    return statistics.pstdev(values) if len(values) > 1 else 0.0


def safe_mean(values: Iterable[float]) -> float | None:
    vals = list(values)
    return sum(vals) / len(vals) if vals else None
