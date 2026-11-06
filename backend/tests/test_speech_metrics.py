"""Speech metrics (pure functions): words per minute, filler words, long pauses."""

import pytest

from app.services.speech_metrics import (
    compute_metrics,
    count_fillers,
    count_words,
    pauses,
    speaking_seconds,
    words_per_minute,
)

# ------------------------------------------------------------------ words / WPM


def test_count_words_handles_punctuation_and_contractions() -> None:
    assert count_words("I don't know, it's... fine!") == 5
    assert count_words("") == 0
    assert count_words("   ,.!? ") == 0
    assert count_words("FastAPI + Docker (v2)") == 3  # "+" and brackets are not words


def test_wpm_from_duration() -> None:
    assert words_per_minute(150, 60.0) == 150.0
    assert words_per_minute(70, 30.0) == 140.0
    assert words_per_minute(0, 30.0) is None
    assert words_per_minute(5, None) is None
    assert words_per_minute(5, 0.5) is None  # too short to be meaningful


def test_speaking_time_ignores_leading_and_trailing_silence() -> None:
    words = [(2.0, 2.4), (2.5, 3.0), (10.0, 12.0)]
    assert speaking_seconds(15.0, [(0.0, 14.0)], words) == 10.0  # words win over segments
    assert speaking_seconds(15.0, [(1.0, 13.0)], []) == 12.0
    assert speaking_seconds(15.0, [], []) == 15.0
    assert speaking_seconds(None, [], []) is None
    assert speaking_seconds(0.0, [], []) is None


# ------------------------------------------------------------------ fillers


def test_english_fillers_counted_with_word_boundaries() -> None:
    text = "Um, so I basically, uh, built it. Umm, actually it was fine. Uhh."
    assert count_fillers(text) == {"um": 2, "uh": 2, "basically": 1, "actually": 1}


def test_fillers_need_word_boundaries() -> None:
    # "umbrella", "huh", "actuallyx", "sumo", "drum" are not fillers
    assert count_fillers("An umbrella, a drum and sumo; huh") == {}
    assert count_fillers("the unlikely likeness") == {}


def test_like_only_counts_as_interjection() -> None:
    assert count_fillers("I like Python and it looks like this.") == {}
    assert count_fillers("Something like 40 percent of requests.") == {}
    assert count_fillers("I was, like, really nervous") == {"like": 1}
    assert count_fillers("Like, we tried caching first") == {"like": 1}
    assert count_fillers("it was like um slow") == {"um": 1, "like": 1}


def test_you_know_only_at_clause_end() -> None:
    assert count_fillers("Do you know Docker?") == {}
    assert count_fillers("You know, it was fast, you know.") == {"you know": 2}
    assert count_fillers("it scaled you know") == {"you know": 1}  # end of text


def test_hedges_but_not_after_determiners() -> None:
    assert count_fillers("It was kind of slow and sort of messy") == {"sort of": 1, "kind of": 1}
    assert count_fillers("What kind of database? A sort of cache.") == {}
    assert count_fillers("This kind of problem") == {}


def test_urdu_and_hinglish_fillers() -> None:
    text = "Matlab, I used FastAPI. Yaani, wo jo API thi, acha, woh fast thi. Achha."
    assert count_fillers(text) == {"matlab": 1, "yani": 1, "wo": 2, "acha": 2}


def test_urdu_script_fillers() -> None:
    assert count_fillers("مطلب میں نے یعنی وہ کام کیا، اچھا") == {
        "matlab": 1,
        "yani": 1,
        "wo": 1,
        "acha": 1,
    }
    assert count_fillers("مطلبی") == {}  # word boundary in Urdu script too


def test_fillers_case_insensitive_and_curly_apostrophes() -> None:
    assert count_fillers("BASICALLY, UM… You Know.") == {"um": 1, "you know": 1, "basically": 1}


def test_no_fillers_in_empty_text() -> None:
    assert count_fillers("") == {}


# ------------------------------------------------------------------ pauses


def test_long_pauses_strictly_over_two_seconds() -> None:
    spans = [(0.0, 1.0), (3.5, 4.0), (6.0, 7.0), (9.01, 10.0)]  # gaps 2.5, 2.0, 2.01
    assert pauses(spans) == (2, 2.5)


def test_pauses_unsorted_overlapping_and_empty() -> None:
    assert pauses([]) == (0, 0.0)
    assert pauses([(0.0, 5.0)]) == (0, 0.0)
    assert pauses([(4.0, 6.0), (0.0, 5.0)]) == (0, 0.0)  # overlap = no gap


# ------------------------------------------------------------------ end to end


def test_compute_metrics_prefers_word_timestamps() -> None:
    text = "Um, I built a RAG chatbot. Basically it answers course questions."
    words = [(0.5 + i * 0.4, 0.8 + i * 0.4) for i in range(5)] + [
        (6.0 + i * 0.4, 6.3 + i * 0.4) for i in range(5)
    ]
    m = compute_metrics(text, 9.0, segments=[(0.0, 2.6), (2.6, 9.0)], words=words)
    assert m.word_count == 11
    assert m.duration_seconds == 9.0
    assert m.speaking_seconds == pytest.approx(7.4)
    assert m.words_per_minute == pytest.approx(89.2)
    assert m.filler_count == 2 and m.filler_breakdown == {"um": 1, "basically": 1}
    assert m.long_pauses == 1 and m.longest_pause_seconds == pytest.approx(3.6)


def test_compute_metrics_without_segments_uses_duration() -> None:
    m = compute_metrics("one two three four five six", 3.0)
    assert m.speaking_seconds == 3.0 and m.words_per_minute == 120.0
    assert m.long_pauses == 0 and m.longest_pause_seconds == 0.0


def test_compute_metrics_empty_transcript() -> None:
    m = compute_metrics("", None)
    assert m.word_count == 0 and m.words_per_minute is None
    assert m.filler_count == 0 and m.filler_breakdown == {}
    assert m.duration_seconds is None and m.speaking_seconds is None
