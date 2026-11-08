"""Voice answers: Groq Whisper client (mocked with httpx.MockTransport), audio validation, and the
multipart answer endpoint end to end with the fake DB + fake LLM. No network, no real audio."""

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

import app.routers.interview as interview_router
from app.core.config import Settings
from app.core.errors import AppError
from app.services.stt import (
    GROQ_STT_URL,
    MAX_AUDIO_BYTES,
    STTClient,
    Transcription,
    clean_transcription,
    sniff_container,
    validate_audio,
)
from tests.test_interview import env, evaluation, new_session, url  # noqa: F401 (fixture)

WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 4000
OGG = b"OggS" + b"\x00" * 4000
MP4 = b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 4000
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 4000
MP3 = b"ID3\x04" + b"\x00" * 4000
FLAC = b"fLaC" + b"\x00" * 4000

SPOKEN = "Um, so I basically built a RAG chatbot with FastAPI, you know. It cut wrong answers."


def verbose_json(text: str = SPOKEN, duration: float = 12.0, **extra: Any) -> dict[str, Any]:
    return {
        "task": "transcribe",
        "language": "english",
        "duration": duration,
        "text": " " + text,
        "segments": [
            {"id": 0, "start": 0.4, "end": 4.0, "text": text[:40], "no_speech_prob": 0.01,
             "avg_logprob": -0.2},
            {"id": 1, "start": 7.0, "end": 11.5, "text": text[40:], "no_speech_prob": 0.02,
             "avg_logprob": -0.3},
        ],
        "words": [{"word": "Um", "start": 0.4, "end": 0.6}, {"word": "answers", "start": 11.0,
                   "end": 11.5}],
        **extra,
    }  # fmt: skip


def settings(**kw: Any) -> Settings:
    base: dict[str, Any] = {"groq_api_key": "test-key", "groq_stt_model": "whisper-large-v3-turbo"}
    return Settings(_env_file=None, **{**base, **kw})  # type: ignore[call-arg]


def stt_with(handler: Callable[[httpx.Request], httpx.Response], **kw: Any) -> STTClient:
    return STTClient(settings(**kw), httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def ok(body: dict[str, Any] | None = None) -> Callable[[httpx.Request], httpx.Response]:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body or verbose_json())

    return handler


# ------------------------------------------------------------------ validation


@pytest.mark.parametrize(
    ("data", "mime", "ext"),
    [
        (WEBM, "audio/webm;codecs=opus", "webm"),
        (WEBM, "video/webm", "webm"),
        (OGG, "audio/ogg; codecs=opus", "ogg"),
        (MP4, "audio/mp4", "m4a"),
        (WAV, "audio/wav", "wav"),
        (MP3, "audio/mpeg", "mp3"),
        (FLAC, "audio/flac", "flac"),
    ],
)
def test_accepts_supported_formats(data: bytes, mime: str, ext: str) -> None:
    assert validate_audio(data, mime).ext == ext


@pytest.mark.parametrize(
    ("data", "mime", "code"),
    [
        (b"%PDF-1.4" + b"\x00" * 4000, "audio/webm", "unsupported_audio"),  # magic mismatch
        (WEBM, "application/pdf", "unsupported_audio"),  # MIME not allowed
        (WEBM, None, "unsupported_audio"),
        (OGG, "audio/webm", "unsupported_audio"),  # MIME and magic disagree
        (b"\x1a\x45\xdf\xa3", "audio/webm", "audio_empty"),
        (b"\x1a\x45\xdf\xa3" + b"\x00" * MAX_AUDIO_BYTES, "audio/webm", "audio_too_large"),
    ],
)
def test_rejects_bad_audio(data: bytes, mime: str | None, code: str) -> None:
    with pytest.raises(AppError) as exc:
        validate_audio(data, mime)
    assert exc.value.code == code


def test_sniff_needs_full_signatures() -> None:
    assert sniff_container(b"RIFF\x00\x00\x00\x00AVI LIST") is None  # RIFF but not WAVE
    assert sniff_container(b"") is None
    assert sniff_container(b"\xff\xfb\x90") == "mp3"


# ------------------------------------------------------------------ Groq client


def test_request_shape_is_verbose_json_with_timestamps() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=verbose_json())

    result = asyncio.run(stt_with(handler).transcribe(WEBM, validate_audio(WEBM, "audio/webm")))
    req = seen[0]
    assert str(req.url) == GROQ_STT_URL and req.method == "POST"
    assert req.headers["authorization"] == "Bearer test-key"
    assert req.headers["content-type"].startswith("multipart/form-data; boundary=")
    body = req.content
    for name, value in [
        ("model", "whisper-large-v3-turbo"),
        ("response_format", "verbose_json"),
        ("language", "en"),
        ("temperature", "0"),
    ]:
        assert f'name="{name}"\r\n\r\n{value}\r\n'.encode() in body
    assert body.count(b'name="timestamp_granularities[]"') == 2
    assert b'name="timestamp_granularities[]"\r\n\r\nword\r\n' in body
    assert b'name="file"; filename="answer.webm"' in body and b"Content-Type: audio/webm" in body
    assert WEBM in body
    assert result.text == SPOKEN and result.duration == 12.0 and len(result.segments) == 2
    assert result.words[1].word == "answers"


def test_parses_minimal_response_without_segments() -> None:
    result = asyncio.run(
        stt_with(ok({"text": " hello there "})).transcribe(WEBM, validate_audio(WEBM, "audio/webm"))
    )
    assert result.text == "hello there" and result.segments == [] and result.duration is None


@pytest.mark.parametrize("status", [429, 500, 503])
def test_provider_errors_become_503_after_one_retry(status: int) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"error": {"message": "busy"}})

    with pytest.raises(AppError) as exc:
        asyncio.run(stt_with(handler).transcribe(WEBM, validate_audio(WEBM, "audio/webm")))
    assert exc.value.status_code == 503 and exc.value.code == "stt_unavailable"
    assert calls == 2


def test_rejected_audio_is_422_without_retry() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"error": {"message": "could not decode"}})

    with pytest.raises(AppError) as exc:
        asyncio.run(stt_with(handler).transcribe(WEBM, validate_audio(WEBM, "audio/webm")))
    assert exc.value.code == "audio_unreadable" and calls == 1


def test_network_error_and_bad_json_are_503() -> None:
    def boom(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    def garbage(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>")

    fmt = validate_audio(WEBM, "audio/webm")
    for handler in (boom, garbage):
        with pytest.raises(AppError) as exc:
            asyncio.run(stt_with(handler).transcribe(WEBM, fmt))
        assert exc.value.code == "stt_unavailable"


def test_missing_config_is_503_without_calling_groq() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("must not be called")

    with pytest.raises(AppError) as exc:
        asyncio.run(
            stt_with(handler, groq_stt_model=None).transcribe(
                WEBM, validate_audio(WEBM, "audio/webm")
            )
        )
    assert exc.value.code == "stt_unavailable"


def test_hallucinated_silence_segments_are_dropped() -> None:
    t = Transcription.model_validate(
        {
            "text": " I used Docker. Thank you.",
            "segments": [
                {
                    "start": 0,
                    "end": 2,
                    "text": " I used Docker.",
                    "no_speech_prob": 0.05,
                    "avg_logprob": -0.2,
                },
                {
                    "start": 5,
                    "end": 9,
                    "text": " Thank you.",
                    "no_speech_prob": 0.95,
                    "avg_logprob": -1.4,
                },
            ],
            "words": [
                {"word": "Docker", "start": 1.0, "end": 1.6},
                {"word": "Thank", "start": 6.0, "end": 6.3},
            ],
        }  # fmt: skip
    )
    cleaned = clean_transcription(t)
    assert cleaned.text == "I used Docker." and len(cleaned.segments) == 1
    assert [w.word for w in cleaned.words] == ["Docker"]


# ------------------------------------------------------------------ endpoint


@pytest.fixture
def voice_env(env, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]  # noqa: F811
    client, db, llm = env
    state: dict[str, Any] = {"handler": ok(), "requests": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"] += 1
        return state["handler"](request)  # type: ignore[no-any-return]

    monkeypatch.setattr(interview_router, "get_stt", lambda: stt_with(handler))
    return client, db, llm, state


def started(client: TestClient, db: Any, practice: bool = True) -> tuple[str, dict[str, str], str]:
    sid, h = new_session(client, db)
    r = client.post(url(sid, "/start"), json={"practice_mode": practice}, headers=h)
    return sid, h, r.json()["question"]["id"]


def post_audio(
    client: TestClient,
    sid: str,
    h: dict[str, str],
    qid: str,
    data: bytes = WEBM,
    mime: str = "audio/webm;codecs=opus",
) -> httpx.Response:
    return client.post(
        url(sid, "/answer"),
        data={"question_id": qid},
        files={"audio": ("answer.webm", data, mime)},
        headers=h,
    )  # fmt: skip


def test_voice_answer_end_to_end(voice_env) -> None:  # type: ignore[no-untyped-def]
    client, db, llm, stt = voice_env
    sid, h, qid = started(client, db)
    r = post_audio(client, sid, h, qid)
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["question"]["order"] == 2 and t["progress"]["answered"] == 1
    last = t["last_answer"]
    assert last["question_id"] == qid and last["transcript"] == SPOKEN
    assert last["feedback"] is not None  # practice mode
    m = last["speech_metrics"]
    assert m["duration_seconds"] == 12.0 and m["word_count"] == 16
    assert m["speaking_seconds"] == 11.1 and m["words_per_minute"] == pytest.approx(86.5)
    assert m["filler_breakdown"] == {"um": 1, "you know": 1, "basically": 1}
    assert m["filler_count"] == 3 and m["long_pauses"] == 1
    assert stt["requests"] == 1

    # Metrics are stored in the answers columns; no audio anywhere.
    row = db.rows("answers")[-1]
    assert row["transcript"] == SPOKEN and row["duration_seconds"] == 12.0
    assert row["words_per_minute"] == pytest.approx(86.5) and row["filler_count"] == 3
    assert row["filler_breakdown"] == {"um": 1, "you know": 1, "basically": 1}
    assert row["long_pauses"] == 1
    stored = [v for rows in db.t.values() for r in rows for v in r.values()]
    assert not any(isinstance(v, bytes | bytearray) for v in stored)
    assert "answer.webm" not in json.dumps(db.t, default=str)

    # The transcript reaches the scorer fenced as untrusted data, like typed text.
    body = llm.prompts[-1].split("ANSWER TO SCORE:\n", 1)[1]
    assert body.startswith("<transcript>\n") and SPOKEN in body

    # Text answers keep working on the same endpoint, without speech_metrics.
    r = client.post(
        url(sid, "/answer"), json={"question_id": t["question"]["id"], "text": SPOKEN}, headers=h
    )
    assert r.status_code == 200 and r.json()["last_answer"]["speech_metrics"] is None
    assert db.rows("answers")[-1]["words_per_minute"] is None
    # GET after a voice answer still returns the normal turn
    assert client.get(url(sid), headers=h).json()["history"][0]["answer_text"] == SPOKEN


def test_voice_answer_bad_files_never_reach_groq(voice_env) -> None:  # type: ignore[no-untyped-def]
    client, db, _, stt = voice_env
    sid, h, qid = started(client, db)
    cases = [
        (b"%PDF-1.7" + b"\x00" * 4000, "audio/webm", 415, "unsupported_audio"),
        (WEBM, "text/plain", 415, "unsupported_audio"),
        (b"\x1a\x45\xdf\xa3", "audio/webm", 422, "audio_empty"),
        (b"\x1a\x45\xdf\xa3" + b"\x00" * MAX_AUDIO_BYTES, "audio/webm", 413, "audio_too_large"),
    ]
    for data, mime, status, code in cases:
        r = post_audio(client, sid, h, qid, data, mime)
        assert r.status_code == status and r.json()["error"]["code"] == code, r.text
    assert stt["requests"] == 0 and db.rows("answers") == []


def test_voice_answer_form_validation(voice_env) -> None:  # type: ignore[no-untyped-def]
    client, db, _, _ = voice_env
    sid, h, qid = started(client, db)
    r = client.post(url(sid, "/answer"), data={"question_id": qid}, files={}, headers=h)
    assert r.status_code == 422  # no file -> urlencoded body, treated as invalid JSON
    r = client.post(
        url(sid, "/answer"), data={"question_id": "nope"},
        files={"audio": ("a.webm", WEBM, "audio/webm")}, headers=h,
    )  # fmt: skip
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    r = client.post(
        url(sid, "/answer"), data={"question_id": qid},
        files={"other": ("a.webm", WEBM, "audio/webm")}, headers=h,
    )  # fmt: skip
    assert r.status_code == 422


def test_voice_answer_stt_outage_is_503_and_retryable(voice_env) -> None:  # type: ignore[no-untyped-def]
    client, db, _, stt = voice_env
    sid, h, qid = started(client, db)
    stt["handler"] = lambda _: httpx.Response(503)
    r = post_audio(client, sid, h, qid)
    assert r.status_code == 503 and r.json()["error"]["code"] == "stt_unavailable"
    assert db.rows("answers") == []
    stt["handler"] = ok()
    r = post_audio(client, sid, h, qid)  # same question, retried upload
    assert r.status_code == 200 and r.json()["question"]["order"] == 2


def test_voice_answer_silence_and_too_long(voice_env) -> None:  # type: ignore[no-untyped-def]
    client, db, _, stt = voice_env
    sid, h, qid = started(client, db)
    stt["handler"] = ok({"text": "  ", "duration": 4.0, "segments": []})
    r = post_audio(client, sid, h, qid)
    assert r.status_code == 422 and r.json()["error"]["code"] == "no_speech"
    stt["handler"] = ok(verbose_json(duration=140.0))
    r = post_audio(client, sid, h, qid)
    assert r.status_code == 422 and r.json()["error"]["code"] == "audio_too_long"
    assert db.rows("answers") == []


def test_voice_answer_wrong_question_and_ownership(voice_env) -> None:  # type: ignore[no-untyped-def]
    client, db, _, stt = voice_env
    sid, h, qid = started(client, db)
    _, other = new_session(client, db)
    assert post_audio(client, sid, other, qid).status_code == 404
    assert stt["requests"] == 0  # ownership is checked before transcription
    r = post_audio(client, sid, h, "00000000-0000-4000-8000-000000000000")
    assert r.status_code == 400 and r.json()["error"]["code"] == "wrong_question"


def test_voice_and_text_share_the_answer_quota(voice_env) -> None:  # type: ignore[no-untyped-def]
    client, db, _, stt = voice_env
    sid, h, qid = started(client, db)
    db.usage[(sid, "interview_answer")] = 40
    r = post_audio(client, sid, h, qid)
    assert r.status_code == 429 and r.json()["error"]["code"] == "quota_exceeded"
    assert stt["requests"] == 0
    r = client.post(url(sid, "/answer"), json={"question_id": qid, "text": "x"}, headers=h)
    assert r.status_code == 429


def test_json_answer_errors_keep_their_shape(voice_env) -> None:  # type: ignore[no-untyped-def]
    client, db, _, _ = voice_env
    sid, h, qid = started(client, db)
    r = client.post(url(sid, "/answer"), json={"question_id": qid}, headers=h)
    assert r.status_code == 422 and r.json()["error"]["message"] == "Invalid input: body.text"
    r = client.post(
        url(sid, "/answer"),
        content=b"{not json",
        headers={**h, "content-type": "application/json"},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_openapi_documents_both_bodies(voice_env) -> None:  # type: ignore[no-untyped-def]
    client, *_ = voice_env
    spec = client.get("/api/v1/openapi.json")
    assert spec.status_code == 200
    path = next(p for p in spec.json()["paths"] if p.endswith("/interview/answer"))
    content = spec.json()["paths"][path]["post"]["requestBody"]["content"]
    assert {"application/json", "multipart/form-data"} <= set(content)
