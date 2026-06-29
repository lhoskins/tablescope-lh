"""MFA status + Twilio Send-SMS hook.

* ``GET /api/mfa/status`` — tells the client whether the caller's role requires
  MFA and whether the current session already satisfies it (aal2). Reachable at
  aal1 (it is on the MFA-exempt allowlist) so the client can decide whether to
  route to setup or challenge.

* ``POST /api/auth/hooks/send-sms`` — Supabase **Send SMS Hook**. Supabase calls
  this with the OTP it generated; we deliver it via the Twilio Messaging Service.
  The hook secret is validated, the OTP is never logged, the phone is masked, and
  cost controls + audit are applied. This route is anonymous (it authenticates
  itself via the hook secret).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.membership import require_membership
from app.auth.mfa_policy import (
    PREFERRED_FACTOR_TYPE,
    role_requires_mfa,
    session_has_mfa,
)
from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.services.mfa_sms_service import MfaRateLimitedError, send_mfa_sms

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mfa"])


class MfaStatusResponse(BaseModel):
    role: str
    roleRequiresMfa: bool
    aal: str | None
    mfaSatisfied: bool
    preferredFactorType: str
    requiredAction: str | None


@router.get("/mfa/status", response_model=MfaStatusResponse)
async def mfa_status(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_membership),
) -> MfaStatusResponse:
    """Report the caller's MFA requirement + whether the session satisfies it."""
    user = await session.get(User, context.user_id)
    role = (user.role if user else context.role) or "viewer"
    # roleRequiresMfa reflects *effective* enforcement: only true when the master
    # switch is on, so the frontend gate doesn't redirect before MFA is live.
    requires = get_settings().mfa_enforcement_enabled and role_requires_mfa(role)
    satisfied = session_has_mfa(context.aal)
    required_action: str | None = None
    if requires and not satisfied:
        required_action = "setup_or_challenge"
    return MfaStatusResponse(
        role=role,
        roleRequiresMfa=requires,
        aal=context.aal,
        mfaSatisfied=satisfied,
        preferredFactorType=PREFERRED_FACTOR_TYPE,
        requiredAction=required_action,
    )


def _verify_hook_signature(request: Request, raw_body: bytes) -> bool:
    """Validate the Supabase Send-SMS hook secret.

    Supports the Standard Webhooks signature (``webhook-id`` /
    ``webhook-timestamp`` / ``webhook-signature`` headers signed with a
    base64 ``v1,whsec_...`` secret) and a simple bearer-secret fallback.
    """
    settings = get_settings()
    secret = settings.supabase_send_sms_hook_secret
    if not secret:
        # Not configured → reject (fail closed) so we never deliver unauthenticated.
        return False

    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer ") and hmac.compare_digest(
        auth.split(" ", 1)[1].strip(), secret
    ):
        return True

    webhook_id = request.headers.get("webhook-id")
    timestamp = request.headers.get("webhook-timestamp")
    signature_header = request.headers.get("webhook-signature")
    if not (webhook_id and timestamp and signature_header):
        return False

    secret_bytes = secret
    if secret_bytes.startswith("v1,whsec_"):
        secret_bytes = secret_bytes.split("whsec_", 1)[1]
    elif secret_bytes.startswith("whsec_"):
        secret_bytes = secret_bytes.split("whsec_", 1)[1]
    try:
        key = base64.b64decode(secret_bytes)
    except Exception:
        key = secret.encode()

    signed_content = f"{webhook_id}.{timestamp}.{raw_body.decode()}".encode()
    expected = base64.b64encode(
        hmac.new(key, signed_content, hashlib.sha256).digest()
    ).decode()
    # Header may contain space-separated "v1,<sig>" entries.
    for part in signature_header.split(" "):
        candidate = part.split(",", 1)[-1]
        if hmac.compare_digest(candidate, expected):
            return True
    return False


@router.post("/auth/hooks/send-sms")
async def send_sms_hook(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Deliver a Supabase-generated MFA OTP via Twilio (Send SMS Hook)."""
    raw_body = await request.body()
    if not _verify_hook_signature(request, raw_body):
        return JSONResponse(
            status_code=401,
            content={"error": {"http_code": 401, "message": "Invalid hook signature"}},
        )

    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"error": {"http_code": 400, "message": "Invalid JSON body"}},
        )

    user_obj = payload.get("user") or {}
    sms_obj = payload.get("sms") or {}
    phone = user_obj.get("phone") or sms_obj.get("phone")
    otp = sms_obj.get("otp")
    if not phone or not otp:
        return JSONResponse(
            status_code=400,
            content={"error": {"http_code": 400, "message": "Missing phone or otp"}},
        )

    # Best-effort map to a local user/tenant for tenant-scoped tracking.
    tenant_id: int | None = None
    user_id: int | None = None
    supa_id = user_obj.get("id")
    if supa_id:
        local = await session.scalar(
            select(User).where(User.supabase_user_id == str(supa_id))
        )
        if local is not None:
            tenant_id = local.tenant_id
            user_id = local.id

    message = f"Your Tablescope verification code is {otp}"
    try:
        await send_mfa_sms(
            session,
            phone=phone,
            message=message,
            tenant_id=tenant_id,
            user_id=user_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        await session.commit()
    except MfaRateLimitedError as exc:
        await session.commit()
        return JSONResponse(
            status_code=429,
            content={
                "error": {
                    "http_code": 429,
                    "message": "Too many SMS requests. Please wait and try again.",
                    "reason": exc.reason,
                    "retryAfterSeconds": exc.retry_after_seconds,
                }
            },
        )
    except Exception as exc:  # pragma: no cover - Twilio/network failure
        await session.rollback()
        logger.warning("MFA SMS hook delivery failed: %s", type(exc).__name__)
        return JSONResponse(
            status_code=502,
            content={"error": {"http_code": 502, "message": "SMS delivery failed"}},
        )

    return JSONResponse(status_code=200, content={})
