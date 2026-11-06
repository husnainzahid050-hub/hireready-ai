"""Speech-to-text with Groq Whisper (SPEC 6.4). Audio is never stored.

The audio bytes live only in memory for the length of one request: they are validated here,
posted to Groq, and dropped when the request ends. Nothing is written to disk, the database or
the logs (we log sizes and timings only).

Groq's transcription endpoint is OpenAI-compatible (docs: console.groq.com/docs/speech-to-text,
checked Nov 2026):
- POST https://api.groq.com/openai/v1/audio/transcriptions, multipart/form-data
- fields: file, model, language (ISO-639-1), prompt (<= 224 tokens), temperature,
  response_format (json | verbose_json | text), timestamp_granularities[] (segment | word;
  needs verbose_json)
- file types: flac, mp3, mp4, mpeg, mpga, m4a, ogg, wav, webm; max 25 MB on the free tier;
  requests shorter than 10 s are billed as 10 s.
- verbose_json returns {text, language, duration, segments: [{id, start, end, text,
  avg_logprob, no_speech_prob, ...}], words: [{word, start, end}]}.

Whisper tends to "clean up" disfluencies and silently drop "um"/"uh". A short `prompt` written
in a disfluent style nudges it to keep them verbatim, which the filler-word metric depends on.
"""

import time
from dataclasses import dataclass
from typing import Any, Final

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.http import get_http_client, request_with_retry
from app.core.logging import get_logger

log = get_logger(__name__)

GROQ_STT_URL: Final = "https://api.groq.com/openai/v1/audio/transcriptions"

# Well under Vercel's 4.5 MB request body limit (multipart overhead + other fields fit easily).
# The browser records opus at ~48 kbit/s, so 120 s is ~0.7 MB; 3 MB leaves room for Safari's
# AAC (audio/mp4) and short WAV uploads.
MAX_AUDIO_BYTES: Final = 3_000_000
MIN_AUDIO_BYTES: Final = 1_000  # anything smaller is a header with no sound
MAX_AUDIO_SECONDS: Final = 120.0
DURATION_TOLERANCE_S: Final = 5.0  # container timing jitter; the recorder stops at exactly 120 s

# Interviews are in English. Passing the language improves accuracy and latency; Urdu/Hinglish
# fillers then come back transliterated (e.g. "matlab", "yani"), which speech_metrics counts.
STT_LANGUAGE: Final = "en"
STT_PROMPT: Final = (
    "Um, so, uh, I basically worked on, like, you know, the backend. Matlab, it was, uh, "
    "kind of hard."
)

# Groq bills short clips as 10 s and the audio quota is per hour; one retry is enough.
_STT_TIMEOUT_S: Final = 30.0


# --------------------------------------------------------------- file validation


@dataclass(frozen=True)
class AudioFormat:
    ext: str  # filename extension Groq uses to pick a decoder
    mime: str


_FORMATS: Final = {
    "webm": AudioFormat("webm", "audio/webm"),
    "ogg": AudioFormat("ogg", "audio/ogg"),
    "mp4": AudioFormat("m4a", "audio/mp4"),
    "wav": AudioFormat("wav", "audio/wav"),
    "mp3": AudioFormat("mp3", "audio/mpeg"),
    "flac": AudioFormat("flac", "audio/flac"),
}

# Declared Content-Type (parameters like ";codecs=opus" stripped) -> container we expect.
# Browsers label MediaRecorder output inconsistently (Chrome may say video/webm, Safari
# audio/mp4 or video/mp4), so both are accepted; the magic bytes decide.
_ALLOWED_MIME: Final = {
    "audio/webm": "webm",
    "video/webm": "webm",
    "audio/ogg": "ogg",
    "audio/opus": "ogg",
    "audio/mp4": "mp4",
    "audio/m4a": "mp4",
    "audio/x-m4a": "mp4",
    "audio/aac": "mp4",
    "video/mp4": "mp4",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/vnd.wave": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/flac": "flac",
    "audio/x-flac": "flac",
}


def sniff_container(data: bytes) -> str | None:
    """Identify the audio container from its magic bytes (None = not an audio file we accept)."""
    if data.startswith(b"\x1a\x45\xdf\xa3"):  # EBML header (WebM / Matroska)
        return "webm"
    if data.startswith(b"OggS"):
        return "ogg"
    if len(data) >= 12 and data[4:8] == b"ftyp":  # ISO BMFF (mp4 / m4a)
        return "mp4"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "wav"
    if data.startswith(b"fLaC"):
        return "flac"
    if data.startswith(b"ID3") or (len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "mp3"
    return None


def validate_audio(data: bytes, content_type: str | None) -> AudioFormat:
    """Check size, declared MIME type AND magic bytes (they must agree). Raises AppError."""
    if len(data) > MAX_AUDIO_BYTES:
        raise AppError(
            "audio_too_large",
            f"The recording is too large (max {MAX_AUDIO_BYTES // 1_000_000} MB). "
            "Keep answers under 2 minutes.",
            status_code=413,
        )
    if len(data) < MIN_AUDIO_BYTES:
        raise AppError(
            "audio_empty", "The recording is empty. Please record your answer again.", 422
        )
    mime = (content_type or "").split(";")[0].strip().lower()
    declared = _ALLOWED_MIME.get(mime)
    sniffed = sniff_container(data)
    if declared is None or sniffed is None or declared != sniffed:
        raise AppError(
            "unsupported_audio",
            "Unsupported audio format. Please record again, or switch to typing.",
            status_code=415,
        )
    return _FORMATS[sniffed]


# --------------------------------------------------------------- response models


class Segment(BaseModel):
    start: float
    end: float
    text: str
    no_speech_prob: float | None = None
    avg_logprob: float | None = None


class Word(BaseModel):
    word: str
    start: float
    end: float


class Transcription(BaseModel):
    text: str
    duration: float | None = None
    language: str | None = None
    segments: list[Segment] = []
    words: list[Word] = []


# Whisper "hears" phrases like "Thank you." in silence; such segments come back with a high
# no-speech probability and a low log-probability. We drop them so silence isn't an answer.
_NO_SPEECH_PROB: Final = 0.8
_LOW_LOGPROB: Final = -1.0


def _is_hallucinated_silence(s: Segment) -> bool:
    return (s.no_speech_prob or 0.0) > _NO_SPEECH_PROB and (s.avg_logprob or 0.0) < _LOW_LOGPROB


def clean_transcription(t: Transcription) -> Transcription:
    """Drop silence segments (and their words); rebuild the text from what is left."""
    if not t.segments:
        return t.model_copy(update={"text": t.text.strip()})
    kept = [s for s in t.segments if not _is_hallucinated_silence(s)]
    if len(kept) == len(t.segments):
        return t.model_copy(update={"text": t.text.strip()})
    words = [w for w in t.words if any(s.start - 0.05 <= w.start <= s.end + 0.05 for s in kept)]
    text = " ".join(s.text.strip() for s in kept).strip()
    return t.model_copy(update={"text": text, "segments": kept, "words": words})


# --------------------------------------------------------------- client


def stt_unavailable() -> AppError:
    return AppError(
        "stt_unavailable",
        "We couldn't transcribe your recording right now. Your recording is kept on this page: "
        "try uploading it again in a moment, or switch to typing.",
        status_code=503,
    )


class STTClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._s = settings
        self._client = client

    async def transcribe(self, data: bytes, fmt: AudioFormat) -> Transcription:
        model = self._s.groq_stt_model
        if not self._s.groq_api_key or not model:
            log.error("stt_not_configured")
            raise stt_unavailable()
        headers = {"Authorization": f"Bearer {self._s.groq_api_key.get_secret_value()}"}
        form: list[tuple[str, str]] = [
            ("model", model),
            ("response_format", "verbose_json"),
            ("timestamp_granularities[]", "segment"),
            ("timestamp_granularities[]", "word"),
            ("language", STT_LANGUAGE),
            ("temperature", "0"),
            ("prompt", STT_PROMPT),
        ]
        files = {"file": (f"answer.{fmt.ext}", data, fmt.mime)}

        async def send() -> httpx.Response:
            return await self._client.post(
                GROQ_STT_URL,
                data=dict_multi(form),
                files=files,
                headers=headers,
                timeout=_STT_TIMEOUT_S,
            )

        started = time.perf_counter()
        try:
            resp = await request_with_retry(send, what="groq stt", max_attempts=2, max_delay=2.0)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            log.warning("stt_failed", extra={"extra_fields": {"error": type(exc).__name__}})
            raise stt_unavailable() from exc
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        if resp.status_code != 200:
            log.warning(
                "stt_failed",
                extra={"extra_fields": {"status": resp.status_code, "stt_ms": elapsed_ms}},
            )
            if resp.status_code in (400, 413, 415, 422):  # Groq rejected the audio itself
                raise AppError(
                    "audio_unreadable",
                    "We couldn't read that recording. Please record your answer again.",
                    status_code=422,
                )
            raise stt_unavailable()
        try:
            result = Transcription.model_validate(resp.json())
        except (ValueError, ValidationError) as exc:
            log.warning("stt_bad_response", extra={"extra_fields": {"stt_ms": elapsed_ms}})
            raise stt_unavailable() from exc
        log.info(
            "stt_done",
            extra={
                "extra_fields": {
                    "model": model,
                    "bytes": len(data),
                    "audio_s": result.duration,
                    "segments": len(result.segments),
                    "stt_ms": elapsed_ms,
                }
            },
        )
        return clean_transcription(result)


def dict_multi(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    """httpx `data=` takes lists for repeated fields: [("a","1"),("a","2")] -> {"a": ["1","2"]}."""
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            prev = out[key]
            out[key] = [*prev, value] if isinstance(prev, list) else [prev, value]
        else:
            out[key] = value
    return out


def get_stt(settings: Settings | None = None) -> STTClient:
    return STTClient(settings or get_settings(), get_http_client())
