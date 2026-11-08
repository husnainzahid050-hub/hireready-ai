"""Security re-audit (Nov 2026) regressions: audio duration bombs, voice over-length strikes,
interview turn races, and the docs-path CSP. See docs/SECURITY.md, "Re-audit findings"."""

import random
import struct
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.services.interview as interview_service
from app.core.errors import AppError
from app.core.headers import SecurityHeadersMiddleware
from app.services.audio_duration import UnsupportedCodecError, estimate_duration_s
from app.services.stt import validate_audio
from tests.test_interview import GOOD, env, new_session, url  # noqa: F401 (fixture)
from tests.test_voice import WEBM, ok, post_audio, started, verbose_json, voice_env  # noqa: F401

# ------------------------------------------------------------------ crafted containers


def wav(seconds: float, *, tag: int = 1, rate: int = 16_000, bits: int = 16) -> bytes:
    frame = bits // 8
    n = int(seconds * rate) * frame
    fmt = struct.pack("<HHIIHH", tag, 1, rate, rate * frame, frame, bits)
    return (
        b"RIFF"
        + struct.pack("<I", 36 + n)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", 16)
        + fmt
        + b"data"
        + struct.pack("<I", n)
        + b"\x00" * n
    )


def ogg_opus(seconds: float) -> bytes:
    first = b"OggS\x00\x02" + struct.pack("<q", 0) + b"\x00" * 12 + b"\x01\x13"
    first += b"OpusHead\x01\x01" + b"\x00" * 9
    last = b"OggS\x00\x04" + struct.pack("<q", int(seconds * 48_000)) + b"\x00" * 13
    return first + b"\x00" * 3000 + last


def flac(seconds: float, rate: int = 16_000) -> bytes:
    packed = (rate << 44) | (0 << 41) | (15 << 36) | int(seconds * rate)
    info = b"\x10\x00\x10\x00" + b"\x00" * 6 + packed.to_bytes(8, "big") + b"\x00" * 16
    return b"fLaC" + b"\x00\x00\x00\x22" + info + b"\x00" * 3000


def mp4(seconds: float, timescale: int = 1000) -> bytes:
    mvhd = (
        b"mvhd"
        + b"\x00" * 4
        + b"\x00" * 8
        + struct.pack(">II", timescale, int(seconds * timescale))
    )
    return (
        b"\x00\x00\x00\x20ftypM4A "
        + b"\x00" * 16
        + struct.pack(">I", len(mvhd) + 4)
        + mvhd
        + (b"\x00" * 3000)
    )


def webm(seconds: float) -> bytes:
    info = b"\x2a\xd7\xb1\x83\x0f\x42\x40" + b"\x44\x89\x88" + struct.pack(">d", seconds * 1000)
    return b"\x1a\x45\xdf\xa3" + b"\x00" * 20 + info + b"\x1f\x43\xb6\x75" + b"\x00" * 3000


def mp3_cbr(kbps_index: int, size: int) -> bytes:
    # MPEG-1 Layer III, 44.1 kHz, no CRC; index 1 = 32 kbit/s.
    header = bytes([0xFF, 0xFB, (kbps_index << 4) | 0x00, 0xC0])
    return header + b"\x00" * (size - 4)


def mp3_xing(frames: int) -> bytes:
    header = bytes([0xFF, 0xFB, 0x90, 0xC0])  # 128 kbit/s, mono
    return header + b"\x00" * 17 + b"Xing" + struct.pack(">II", 1, frames) + b"\x00" * 3000


# ------------------------------------------------------------------ estimator (unit)


@pytest.mark.parametrize(
    ("data", "container", "expected"),
    [
        (wav(30), "wav", 30.0),
        (ogg_opus(300), "ogg", 300.0),
        (flac(200), "flac", 200.0),
        (mp4(95.5), "mp4", 95.5),
        (webm(400), "webm", 400.0),
        (mp3_xing(38_281), "mp3", pytest.approx(1000.0, rel=0.01)),  # 38281 * 1152 / 44100
        (mp3_cbr(1, 2_000_000), "mp3", pytest.approx(500.0, rel=0.01)),  # 2 MB at 32 kbit/s
    ],
)
def test_declared_duration_is_read_from_headers(data: bytes, container: str, expected: Any) -> None:
    assert estimate_duration_s(data, container) == expected


def test_unknown_duration_is_none_never_an_exception() -> None:
    assert estimate_duration_s(WEBM, "webm") is None  # Chrome's WebM: no Duration element
    assert estimate_duration_s(mp4(0), "mp4") is None  # fragmented MP4: duration unset
    rng = random.Random(7)  # noqa: S311 (deterministic fuzz input, not crypto)
    for container in ("wav", "ogg", "flac", "mp4", "webm", "mp3"):
        for size in (0, 1, 5, 30, 200, 5000):
            junk = bytes(rng.getrandbits(8) for _ in range(size))
            for prefix in (b"", b"RIFF\x00\x00\x00\x00WAVE", b"OggS", b"fLaC", b"ID3\x04"):
                value = _safe(prefix + junk, container)
                assert value is None or value >= 0


def _safe(data: bytes, container: str) -> float | None:
    try:
        return estimate_duration_s(data, container)
    except UnsupportedCodecError:
        return None


def test_compressed_wav_is_refused() -> None:
    for tag in (0x0002, 0x0011, 0x0031, 0x0055):  # MS ADPCM, IMA ADPCM, GSM 6.10, MP3-in-WAV
        with pytest.raises(AppError) as e:
            validate_audio(wav(1, tag=tag), "audio/wav")
        assert e.value.code == "unsupported_audio"


@pytest.mark.parametrize(
    ("data", "mime"),
    [
        (wav(126, rate=8_000, bits=8), "audio/wav"),
        (ogg_opus(3600), "audio/ogg"),
        (flac(600), "audio/flac"),
        (mp4(900), "audio/mp4"),
        (webm(3000), "audio/webm"),
        (mp3_cbr(1, 2_900_000), "audio/mpeg"),  # ~12 minutes in 2.9 MB
    ],
)
def test_validate_audio_refuses_declared_over_limit(data: bytes, mime: str) -> None:
    with pytest.raises(AppError) as e:
        validate_audio(data, mime)
    assert e.value.code == "audio_too_long" and e.value.status_code == 422


def test_validate_audio_accepts_declared_under_limit() -> None:
    for data, mime in (
        (wav(60), "audio/wav"),
        (ogg_opus(119), "audio/ogg"),
        (webm(124), "video/webm"),
    ):
        validate_audio(data, mime)


# ------------------------------------------------------------------ endpoint


def test_long_declared_audio_is_free_and_never_reaches_groq(voice_env) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    client, db, _, stt = voice_env
    sid, h, qid = started(client, db)
    r = post_audio(client, sid, h, qid, ogg_opus(3600), "audio/ogg")
    assert r.status_code == 422 and r.json()["error"]["code"] == "audio_too_long"
    assert stt["requests"] == 0 and (sid, "interview_answer") not in db.usage


def test_over_length_strikes_turn_voice_off(voice_env) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    client, db, _, stt = voice_env
    sid, h, qid = started(client, db)
    stt["handler"] = ok(verbose_json(duration=3600.0))
    for _ in range(2):  # a crafted file whose headers hide an hour of audio
        r = post_audio(client, sid, h, qid)
        assert r.status_code == 422 and r.json()["error"]["code"] == "audio_too_long"
    assert db.usage[(sid, "audio_overlong")] == 2
    r = post_audio(client, sid, h, qid)
    assert r.status_code == 429 and r.json()["error"]["code"] == "voice_disabled"
    assert stt["requests"] == 2 and db.usage[(sid, "interview_answer")] == 2  # third: not charged
    # Typed answers keep working.
    r = client.post(url(sid, "/answer"), json={"question_id": qid, "text": GOOD}, headers=h)
    assert r.status_code == 200


# ------------------------------------------------------------------ turn races


def test_parallel_answers_to_one_question_record_only_one(env, monkeypatch) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    client, db, llm = env
    sid, h = new_session(client, db)
    qid = client.post(url(sid, "/start"), json={}, headers=h).json()["question"]["id"]
    stale = db.rows("interview_state")[0]["state"]
    questions_before = len(db.rows("questions"))

    r1 = client.post(url(sid, "/answer"), json={"question_id": qid, "text": GOOD}, headers=h)
    assert r1.status_code == 200
    winner = db.rows("interview_state")[0]["state"]
    questions_after_first = len(db.rows("questions"))

    # The second request loaded the state before the first one committed (two tabs / retry).
    from app.agents.interviewer.state import InterviewState

    async def stale_state(_db: Any, _sid: Any) -> InterviewState:
        return InterviewState.model_validate(stale)

    monkeypatch.setattr(interview_service, "load_state", stale_state)
    r2 = client.post(url(sid, "/answer"), json={"question_id": qid, "text": GOOD}, headers=h)
    assert r2.status_code == 409 and r2.json()["error"]["code"] == "turn_conflict"
    assert db.rows("interview_state")[0]["state"] == winner  # first commit untouched
    assert len(db.rows("answers")) == 1  # the loser's answer row was removed
    assert len(db.rows("questions")) == questions_after_first >= questions_before


def test_parallel_starts_plan_once(env, monkeypatch) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    client, db, _ = env
    sid, h = new_session(client, db)
    first = client.post(url(sid, "/start"), json={}, headers=h).json()
    plan_rows = len(db.rows("questions"))

    real = interview_service.load_state
    calls = {"n": 0}

    async def racing(db_: Any, sid_: Any) -> Any:
        calls["n"] += 1
        return None if calls["n"] == 1 else await real(db_, sid_)  # 1st load: "no state yet"

    monkeypatch.setattr(interview_service, "load_state", racing)
    second = client.post(url(sid, "/start"), json={}, headers=h)
    assert second.status_code == 200
    assert second.json()["question"]["id"] == first["question"]["id"]  # the winner's plan
    assert len(db.rows("interview_state")) == 1 and len(db.rows("questions")) == plan_rows


# ------------------------------------------------------------------ headers


def _probe(docs_enabled: bool, path: str) -> dict[str, str]:
    api = FastAPI(docs_url=None, openapi_url=None)
    api.add_middleware(SecurityHeadersMiddleware, docs_enabled=docs_enabled)
    return dict(TestClient(api).get(path).headers)


def test_docs_paths_keep_strict_csp_in_production() -> None:
    assert "content-security-policy" in _probe(False, "/api/v1/docs")
    assert "content-security-policy" in _probe(False, "/api/v1/openapi.json")
    assert "content-security-policy" not in _probe(True, "/api/v1/docs")
    assert "content-security-policy" in _probe(True, "/api/v1/docsevil")  # exact match only


def test_audio_bytes_and_transcripts_never_hit_the_logs(voice_env, caplog) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    client, db, _, _ = voice_env
    sid, h, qid = started(client, db)
    marker = uuid.uuid4().hex
    data = WEBM + marker.encode()
    with caplog.at_level("DEBUG"):
        post_audio(client, sid, h, qid, data)
    text = "\n".join(r.getMessage() + str(getattr(r, "extra_fields", "")) for r in caplog.records)
    assert marker not in text and "RAG chatbot" not in text
