"""Speech transcription schemas."""

from pydantic import BaseModel


class TranscribeResponse(BaseModel):
    transcript: str
    duration_ms: int | None = None
