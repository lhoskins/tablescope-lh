"""Voice transcription route.

The browser records audio locally and uploads it here. The platform validates
membership, tenant/project scope, feature flags, and rate limits, then forwards
the audio to the private AI-server STT endpoint with an HMAC signature.
"""

from __future__ import annotations

import base64
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.membership import require_membership
from app.config import get_settings
from app.database import get_db
from app.models.audit_event import AuditEvent
from app.models.project import Project
from app.models.tenant import Tenant
from app.schemas.ai_speech import TranscribeResponse
from app.services import ai_intelligence_client as aic

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["AI Speech"])

_ALLOWED_MIME_PREFIXES = ("audio/webm", "audio/mp4", "audio/mpeg", "audio/wav", "audio/ogg")


def _error_response(message: str) -> dict[str, Any]:
    return {"detail": message}


async def _check_voice_rate_limit(
    session: AsyncSession,
    user_id: int,
    tenant_id: int,
    settings: Any,
) -> bool:
    """Rolling-window per-user cap on transcription requests."""
    window = datetime.now(UTC) - timedelta(seconds=settings.voice_rate_limit_window_seconds)
    recent = await session.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.event_type == "voice_transcription",
            AuditEvent.user_id == user_id,
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.created_at >= window,
        )
    )
    return (recent or 0) < settings.voice_rate_limit_max_per_window


async def _audit_voice_event(
    session: AsyncSession,
    *,
    tenant_id: int,
    user_id: int,
    project_id: int | None,
    status: str,
    duration_ms: int | None,
    mime_type: str,
    error: str | None = None,
) -> None:
    """Append-only audit row with no transcript text and no raw audio."""
    audit = AuditEvent(
        tenant_id=tenant_id,
        user_id=user_id,
        project_id=project_id,
        event_type="voice_transcription",
        prompt_type=mime_type,
        scope=status,
        title=error,
        duration_ms=duration_ms,
        tables_queried=[],
        documents_read=[],
    )
    session.add(audit)
    await session.commit()


@router.post("/speech/transcribe", response_model=TranscribeResponse)
async def transcribe_speech(
    request: Request,
    audio: UploadFile = File(...),
    mime_type: str = Form(""),
    project_id: int | None = Form(None),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_membership),
) -> TranscribeResponse:
    settings = get_settings()
    tenant = await session.get(Tenant, context.tenant_id)

    if not settings.voice_input_enabled or not (tenant and tenant.voice_input_enabled):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Voice input is not enabled for this tenant.",
        )

    if project_id is not None:
        project = await session.get(Project, project_id)
        if project is None or project.tenant_id != context.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found.",
            )

    if not mime_type or not any(mime_type.startswith(p) for p in _ALLOWED_MIME_PREFIXES):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported audio format.",
        )

    raw = await audio.read()
    if len(raw) > settings.voice_max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Audio upload exceeds maximum size.",
        )
    if len(raw) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty audio payload.",
        )

    if not await _check_voice_rate_limit(session, context.user_id, context.tenant_id, settings):
        await _audit_voice_event(
            session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            project_id=project_id,
            status="rate_limited",
            duration_ms=None,
            mime_type=mime_type,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Voice transcription rate limit exceeded. Try again later.",
        )

    if not aic.is_enabled():
        await _audit_voice_event(
            session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            project_id=project_id,
            status="ai_unavailable",
            duration_ms=None,
            mime_type=mime_type,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice transcription is temporarily unavailable.",
        )

    signed_payload = {
        "tenant_id": context.tenant_id,
        "user_id": context.user_id,
        "project_id": project_id,
        "mime_type": mime_type,
        "audio_base64": base64.b64encode(raw).decode("utf-8"),
        "timestamp": time.time(),
    }
    signed_payload["signature"] = aic._sign_payload(
        signed_payload, settings.tablescope_ai_signing_secret
    )

    url = f"{settings.tablescope_ai_api_url}/ai/speech/transcribe"
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(settings.voice_ai_timeout_seconds, connect=10.0)
        ) as client:
            resp = await client.post(
                url,
                json=signed_payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("AI server STT returned %s: %s", exc.response.status_code, exc.response.text)
        await _audit_voice_event(
            session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            project_id=project_id,
            status="ai_error",
            duration_ms=int((time.monotonic() - started) * 1000),
            mime_type=mime_type,
            error=f"status:{exc.response.status_code}",
        )
        if exc.response.status_code == 503:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Voice transcription is temporarily unavailable.",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Transcription service returned an error.",
        ) from exc
    except httpx.TimeoutException as exc:
        logger.warning("AI server STT timed out: %s", exc)
        await _audit_voice_event(
            session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            project_id=project_id,
            status="ai_timeout",
            duration_ms=int((time.monotonic() - started) * 1000),
            mime_type=mime_type,
        )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Voice transcription timed out. Try again.",
        ) from exc
    except httpx.TransportError as exc:
        logger.warning("AI server STT transport error: %s", exc)
        await _audit_voice_event(
            session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            project_id=project_id,
            status="ai_unavailable",
            duration_ms=int((time.monotonic() - started) * 1000),
            mime_type=mime_type,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice transcription is temporarily unavailable.",
        ) from exc

    transcript = data.get("transcript", "")
    duration_ms = int((time.monotonic() - started) * 1000)
    await _audit_voice_event(
        session,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        project_id=project_id,
        status="success",
        duration_ms=duration_ms,
        mime_type=mime_type,
    )
    return TranscribeResponse(transcript=transcript, duration_ms=duration_ms)
