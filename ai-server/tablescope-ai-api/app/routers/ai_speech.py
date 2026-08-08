"""Private speech-to-text endpoint.

Receives base64 audio from the platform API, verifies the HMAC signature, and
transcribes with the locally hosted faster-whisper model. No audio is retained.
"""

from __future__ import annotations

import base64
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.core.activity import update_activity
from app.core.config import settings
from app.core.security import verify_signature
from app.services.speech_service import transcribe_base64

router = APIRouter(prefix="/speech", tags=["speech"])


class TranscribeRequest(BaseModel):
    tenant_id: int
    user_id: int
    project_id: int | None = None
    mime_type: str
    audio_base64: str = Field(..., min_length=1)
    timestamp: float
    signature: str


class TranscribeResponse(BaseModel):
    transcript: str
    duration_ms: int | None = None


def _decode_and_measure(payload: dict[str, Any]) -> bytes:
    """Decode base64 and enforce payload size limits."""
    try:
        raw = base64.b64decode(payload["audio_base64"], validate=True)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid base64 audio payload.",
        ) from exc
    if len(raw) > settings.voice_max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Audio payload exceeds maximum size.",
        )
    return raw


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe_audio(req: TranscribeRequest) -> TranscribeResponse:
    update_activity()

    payload = req.model_dump(exclude={"signature"})
    verify_signature(payload, req.signature)

    _decode_and_measure(payload)

    result = transcribe_base64(req.audio_base64, req.mime_type)
    error = result.get("error")
    status_code = result.get("status_code", 503)
    if error:
        raise HTTPException(
            status_code=status_code,
            detail=error,
        )
    return TranscribeResponse(
        transcript=result["transcript"],
        duration_ms=result.get("duration_ms"),
    )
