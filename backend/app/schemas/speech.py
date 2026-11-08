"""Speech metrics for a voice answer (SPEC 6.4). Stored in the `answers` table columns."""

from pydantic import BaseModel, Field


class SpeechMetrics(BaseModel):
    duration_seconds: float | None = Field(description="Length of the recording (from Whisper)")
    speaking_seconds: float | None = Field(
        description="First word to last word: leading/trailing silence is not counted"
    )
    word_count: int
    words_per_minute: float | None = Field(description="null when there is too little speech")
    filler_count: int
    filler_breakdown: dict[str, int] = Field(description="filler -> count, only non-zero ones")
    long_pauses: int = Field(description="Silences longer than 2 seconds between words/segments")
    longest_pause_seconds: float
