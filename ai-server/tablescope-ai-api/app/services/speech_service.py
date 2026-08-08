"""Private speech-to-text service.

Uses faster-whisper on CPU by default. The model is loaded lazily and cached
for the lifetime of the process. If the package or model is unavailable, the
router returns a 503 so the platform can fall back to typed input.
"""

from __future__ import annotations

import base64
import logging
import os
import tempfile
import time
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_model: Any | None = None
_model_lock = False


def _load_model() -> Any:
    """Lazy-load the faster-whisper model once per process."""
    global _model, _model_lock
    if _model is not None:
        return _model
    # Simple import-time gate to avoid concurrent model loads.
    if _model_lock:
        # Return None to signal callers to retry; in practice loads are fast.
        return None
    _model_lock = True
    try:
        from faster_whisper import WhisperModel

        model_path = settings.voice_transcription_model_path or settings.voice_transcription_model
        local_files_only = bool(settings.voice_transcription_model_path)
        _model = WhisperModel(
            model_path,
            device=settings.voice_transcription_device,
            compute_type=settings.voice_transcription_compute_type,
            local_files_only=local_files_only,
        )
        logger.info("Loaded faster-whisper model from %s", model_path)
    except Exception as exc:  # pragma: no cover - model/dependency may be absent
        logger.warning("Could not load faster-whisper model: %s", exc)
        _model = False  # cache the failure
    finally:
        _model_lock = False
    return _model


def _write_audio_to_temp(audio_base64: str, mime_type: str) -> str:
    """Decode base64 audio to a temporary file with a sensible extension."""
    ext = ".webm"
    if "mp4" in mime_type or "m4a" in mime_type:
        ext = ".m4a"
    elif "wav" in mime_type:
        ext = ".wav"
    elif "ogg" in mime_type:
        ext = ".ogg"
    raw = base64.b64decode(audio_base64)
    fd, path = tempfile.mkstemp(suffix=ext)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
    except Exception:
        os.close(fd)
        raise
    return path


def transcribe_base64(audio_base64: str, mime_type: str) -> dict[str, Any]:
    """Transcribe base64-encoded audio to text.

    Returns ``{"transcript": str}`` on success or
    ``{"error": "...", "status_code": 503}`` on failure.
    """
    if not settings.voice_transcription_enabled:
        return {"error": "Voice transcription is not enabled.", "status_code": 503}

    model = _load_model()
    if model is None or model is False:
        return {"error": "Voice transcription model is not available.", "status_code": 503}

    temp_path = _write_audio_to_temp(audio_base64, mime_type)
    started = time.monotonic()
    try:
        segments, _ = model.transcribe(
            temp_path,
            beam_size=settings.voice_transcription_beam_size,
            best_of=1,
            condition_on_previous_text=False,
        )
        transcript = " ".join(segment.text.strip() for segment in segments).strip()
        return {"transcript": transcript, "duration_ms": int((time.monotonic() - started) * 1000)}
    except Exception as exc:  # pragma: no cover - ffmpeg/decode/model errors
        logger.warning("Transcription failed: %s", exc)
        return {"error": "Transcription failed.", "status_code": 503}
    finally:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
