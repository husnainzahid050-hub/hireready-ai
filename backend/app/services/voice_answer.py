"""Voice answers (SPEC 6.4): read the multipart upload in memory, validate, transcribe with
Whisper, compute speech metrics, then hand the transcript to the SAME `submit_answer` used by
text answers (so scoring, follow-ups and persistence are identical, and the transcript is
fenced as untrusted data exactly like typed text).

The audio is never stored: the multipart parser below keeps the file in memory (Starlette's
default spools parts larger than 1 MB to a temp file on disk), and the bytes are dropped when
the request ends.
"""

from typing import Any, Final
from uuid import UUID

from fastapi import Request
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from app.core.body_limit import DEFAULT_MAX_BODY_BYTES
from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.client import SupabaseRest
from app.schemas.interview import InterviewTurn
from app.services import interview as interview_service
from app.services.embeddings import Embedder
from app.services.llm import LLMClient
from app.services.speech_metrics import compute_metrics
from app.services.stt import (
    DURATION_TOLERANCE_S,
    MAX_AUDIO_BYTES,
    MAX_AUDIO_SECONDS,
    STTClient,
    validate_audio,
)

log = get_logger(__name__)

MAX_TRANSCRIPT_CHARS: Final = 5000  # same cap as typed answers (AnswerRequest.text)
_MULTIPART_OVERHEAD: Final = 64 * 1024  # boundaries, headers and the question_id field


class _InMemoryMultiPartParser(MultiPartParser):
    # Keep the file in memory instead of a temp file on disk. The body-size middleware caps
    # every request at DEFAULT_MAX_BODY_BYTES (even chunked ones without Content-Length), so
    # this bound is never exceeded and the file can never roll over to disk.
    spool_max_size = DEFAULT_MAX_BODY_BYTES


def _too_large() -> AppError:
    return AppError(
        "audio_too_large",
        f"The recording is too large (max {MAX_AUDIO_BYTES // 1_000_000} MB). "
        "Keep answers under 2 minutes.",
        status_code=413,
    )


async def read_audio_form(request: Request) -> tuple[UUID, bytes, str | None]:
    """Parse `question_id` + `audio` from a multipart body. Returns (question_id, bytes, mime)."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_AUDIO_BYTES + _MULTIPART_OVERHEAD:
        raise _too_large()
    parser = _InMemoryMultiPartParser(
        request.headers, request.stream(), max_files=1, max_fields=4, max_part_size=1024
    )
    try:
        form = await parser.parse()
    except MultiPartException as exc:
        raise AppError("validation_error", "Invalid upload.", status_code=422) from exc
    try:
        audio: Any = form.get("audio")
        raw_qid = form.get("question_id")
        if not isinstance(audio, UploadFile) or not isinstance(raw_qid, str):
            raise AppError("validation_error", "Invalid input: question_id, audio", status_code=422)
        try:
            question_id = UUID(raw_qid)
        except ValueError as exc:
            raise AppError(
                "validation_error", "Invalid input: question_id", status_code=422
            ) from exc
        data = await audio.read(MAX_AUDIO_BYTES + 1)  # at most 1 byte past the limit
        if len(data) > MAX_AUDIO_BYTES:
            raise _too_large()
        return question_id, data, audio.content_type
    finally:
        await form.close()


async def submit_voice_answer(
    db: SupabaseRest,
    llm: LLMClient,
    embedder: Embedder,
    stt: STTClient,
    session: dict[str, Any],
    question_id: UUID,
    audio: bytes,
    content_type: str | None,
    *,
    charge: interview_service.Charge,
) -> InterviewTurn:
    """Validate -> check the question is the pending one -> charge -> transcribe -> answer.

    The quota/rate limit is charged before Whisper (the costly call), but after the cheap checks,
    so an invalid file or a stale/duplicate upload costs nothing.
    """
    fmt = validate_audio(audio, content_type)
    state = await interview_service.load_state(db, UUID(session["id"]))
    interview_service._check_answerable(state, question_id)  # noqa: SLF001 (same feature)
    await charge()
    result = await stt.transcribe(audio, fmt)
    del audio  # nothing keeps the bytes after this point
    if result.duration is not None and result.duration > MAX_AUDIO_SECONDS + DURATION_TOLERANCE_S:
        raise AppError(
            "audio_too_long",
            "That recording is longer than 2 minutes. Please give a shorter answer.",
            status_code=422,
        )
    text = result.text.strip()
    if not text:
        raise AppError(
            "no_speech",
            "We couldn't hear any speech in that recording. Check your microphone and try "
            "again, or switch to typing.",
            status_code=422,
        )
    metrics = compute_metrics(
        text,
        result.duration,
        segments=[(s.start, s.end) for s in result.segments],
        words=[(w.start, w.end) for w in result.words],
    )
    log.info(
        "voice_answer_metrics",
        extra={
            "extra_fields": {
                "session_id": session["id"],
                "words": metrics.word_count,
                "wpm": metrics.words_per_minute,
                "fillers": metrics.filler_count,
                "long_pauses": metrics.long_pauses,
            }
        },
    )
    return await interview_service.submit_answer(
        db,
        llm,
        embedder,
        session,
        question_id,
        text[:MAX_TRANSCRIPT_CHARS],
        speech=metrics,
    )
