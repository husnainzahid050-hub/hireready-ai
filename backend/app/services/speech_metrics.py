"""Speech metrics from a Whisper transcript: pace, filler words, long pauses (SPEC 6.4).

Pure Python, no I/O, so every rule here is unit-tested (tests/test_speech_metrics.py).

Words per minute
    words / speaking time. Speaking time runs from the first word's start to the last word's end
    (word timestamps), else from the first segment's start to the last segment's end, else the
    whole recording. So the second of silence before you start talking doesn't make you "slow".
    Under 1 s of speech we return None instead of a meaningless number.

Filler words (counted with word boundaries, case-insensitive)
    Always fillers:      um (umm, uhm, erm), uh (uhh, er), basically, actually
    Context-dependent:   like, you know, sort of, kind of
    Urdu / Hinglish:     matlab, yani (yaani), wo (woh, vo, voh), acha (achha, accha),
                         plus the same words in Urdu script (مطلب، یعنی، وہ، اچھا), because
                         Whisper sometimes writes Urdu in Urdu script.

    "like" is mostly a real word ("I like Python", "looks like this", "something like 40%").
    We only count it as a filler when it is set off like an interjection: followed by a comma
    ("I was, like, nervous" / "like, we tried...") or directly followed by another filler
    ("like um"). That misses unpunctuated fillers ("so like I built it"), but it never
    penalises a candidate for normal English: under-counting is the safer error for feedback.
    Whisper adds commas around spoken interjections fairly consistently, which makes this work.

    "you know" counts only when it ends a clause ("you know, it..." / "...fast, you know.")
    and never in a question like "do you know Docker?".

    "sort of" / "kind of" count as hedges ("it was kind of slow") but not after a determiner
    ("what kind of database", "a sort of cache").

    "wo" means "that/he/she" in Urdu, so in a fully Urdu answer it would over-count. Interviews
    run in English, where it only shows up as a code-switched filler.

Long pauses
    Gaps longer than 2 s between consecutive words (word timestamps) or, without them, between
    consecutive segments. Whisper stretches word/segment ends into silence a little, so real
    pauses are slightly longer than measured; 2 s is still a clearly noticeable silence.
"""

import re
from collections.abc import Sequence
from typing import Final

from app.schemas.speech import SpeechMetrics

LONG_PAUSE_SECONDS: Final = 2.0
MIN_SPEECH_SECONDS_FOR_WPM: Final = 1.0

Span = tuple[float, float]

_WORD_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)*")

_CLAUSE_END = r"(?=\s*(?:[,.;!?…]|$))"

# filler name -> pattern. All compiled case-insensitive on the normalised text.
_SIMPLE: Final = {
    "um": r"\b(?:u+h?m+|e+r+m+)\b",
    "uh": r"\b(?:u+h+|e+r+)\b",
    "basically": r"\bbasically\b",
    "actually": r"\bactually\b",
    "matlab": r"\bmatlab\b|(?<!\w)مطلب(?!\w)",
    "yani": r"\bya+n[iy]\b|(?<!\w)یعنی(?!\w)",
    "wo": r"\b(?:wo|woh|vo|voh)\b|(?<!\w)وہ(?!\w)",
    "acha": r"\b(?:acha|achha|accha|achcha)\b|(?<!\w)اچھا(?!\w)",
}
_FILLER_AFTER_LIKE = r"(?:u+h?m+|u+h+|e+r+m*)\b"
_LIKE: Final = re.compile(rf"\blike\b(?=\s*,|\s+{_FILLER_AFTER_LIKE})", re.IGNORECASE)
_YOU_KNOW: Final = re.compile(rf"\byou\s+know\b{_CLAUSE_END}", re.IGNORECASE)
_HEDGE: Final = re.compile(r"\b(sort|kind)\s+of\b", re.IGNORECASE)
_DETERMINERS: Final = frozenset(
    "a an the what which this that these those any some every each one no another my your our "
    "their its his her same different other all many".split()
)
_SIMPLE_RE: Final = {name: re.compile(p, re.IGNORECASE) for name, p in _SIMPLE.items()}
_LAST_WORD_RE = re.compile(r"([^\W_]+)\W*$")

FILLER_NAMES: Final = (
    "um", "uh", "like", "you know", "basically", "actually", "sort of", "kind of",
    "matlab", "yani", "wo", "acha",
)  # fmt: skip


def _normalise(text: str) -> str:
    return text.replace("’", "'").replace(" ", " ")


def count_words(text: str) -> int:
    return len(_WORD_RE.findall(_normalise(text)))


def count_fillers(text: str) -> dict[str, int]:
    """Filler -> count (only fillers that occur). See the module docstring for the rules."""
    t = _normalise(text)
    counts: dict[str, int] = {}
    for name, rx in _SIMPLE_RE.items():
        if n := len(rx.findall(t)):
            counts[name] = n
    if n := len(_LIKE.findall(t)):
        counts["like"] = n
    if n := len(_YOU_KNOW.findall(t)):
        counts["you know"] = n
    for m in _HEDGE.finditer(t):
        before = _LAST_WORD_RE.search(t[: m.start()])
        if before and before.group(1).lower() in _DETERMINERS:
            continue
        key = f"{m.group(1).lower()} of"
        counts[key] = counts.get(key, 0) + 1
    return {name: counts[name] for name in FILLER_NAMES if name in counts}  # stable order


def pauses(spans: Sequence[Span], threshold: float = LONG_PAUSE_SECONDS) -> tuple[int, float]:
    """(number of gaps > threshold, longest gap) between consecutive (start, end) spans."""
    ordered = sorted(spans)
    gaps = [max(0.0, b[0] - a[1]) for a, b in zip(ordered, ordered[1:], strict=False)]
    long_count = sum(1 for g in gaps if g > threshold)
    return long_count, round(max(gaps, default=0.0), 2)


def speaking_seconds(
    duration: float | None, segments: Sequence[Span], words: Sequence[Span]
) -> float | None:
    spans = words or segments
    if spans:
        start = min(s for s, _ in spans)
        end = max(e for _, e in spans)
        if end > start:
            return round(end - start, 2)
    return round(duration, 2) if duration and duration > 0 else None


def words_per_minute(word_count: int, seconds: float | None) -> float | None:
    if not word_count or not seconds or seconds < MIN_SPEECH_SECONDS_FOR_WPM:
        return None
    return round(word_count * 60.0 / seconds, 1)


def compute_metrics(
    text: str,
    duration: float | None,
    segments: Sequence[Span] = (),
    words: Sequence[Span] = (),
) -> SpeechMetrics:
    word_count = count_words(text)
    fillers = count_fillers(text)
    speaking = speaking_seconds(duration, segments, words)
    long_count, longest = pauses(words or segments)
    return SpeechMetrics(
        duration_seconds=round(duration, 2) if duration is not None else None,
        speaking_seconds=speaking,
        word_count=word_count,
        words_per_minute=words_per_minute(word_count, speaking),
        filler_count=sum(fillers.values()),
        filler_breakdown=fillers,
        long_pauses=long_count,
        longest_pause_seconds=longest,
    )
