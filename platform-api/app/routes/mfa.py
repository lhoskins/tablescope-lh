"""SMS MFA (Twilio Verify) status + enroll/challenge endpoints.

* ``GET /api/mfa/status`` — tells the client whether the caller's role requires
  MFA, whether the current session already satisfies it (aal2), and whether a
  verified phone exists (so the client can route to setup vs challenge).
  Reachable at aal1 (it is on the MFA-exempt allowlist).

* ``POST /api/mfa/phone/start`` — send an OTP via Twilio Verify (cost-controlled
  + audited). Used for both enrollment and challenge.

* ``POST /api/mfa/phone/verify`` — check the OTP via Twilio Verify; on success,
  persist the verified phone factor and return a fresh first-party token
  elevated to ``aal2``.

* ``DELETE /api/mfa/phone`` — remove the verified phone (disable MFA), unless the
  caller's role requires it.

OTP codes are never logged or stored; phone numbers are stored masked + hashed.
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.jwt import create_access_token
from app.auth.membership import require_membership
from app.auth.mfa_policy import (
    AAL2,
    PREFERRED_FACTOR_TYPE,
    role_requires_mfa,
    session_has_mfa,
)
from app.config import get_settings
from app.database import get_db
from app.models.mfa_sms_event import MFA_SMS_FACTOR_REMOVED
from app.models.tenant import Tenant
from app.models.user import User
from app.services.mfa_phone_service import (
    deactivate_factor,
    get_active_factor,
    phone_matches_factor,
    upsert_verified_factor,
)
from app.services.mfa_sms_service import (
    MfaRateLimitedError,
    check_mfa_verification,
    record_event,
    start_mfa_verification,
)
from app.services.twilio_sms_service import TwilioConfigError, mask_phone
from app.services.twilio_verify_service import TwilioVerifyError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mfa"])

E164 = re.compile(r"^\+[1-9]\d{7,14}$")
CODE = re.compile(r"^\d{4,10}$")


class MfaStatusResponse(BaseModel):
    role: str
    roleRequiresMfa: bool
    tenantRequiresMfa: bool
    aal: str | None
    mfaSatisfied: bool
    hasVerifiedFactor: bool
    maskedPhone: str | None
    preferredFactorType: str
    requiredAction: str | None


class PhoneStartRequest(BaseModel):
    phone: str


class PhoneStartResponse(BaseModel):
    maskedPhone: str
    cooldownSeconds: int
    status: str


class PhoneVerifyRequest(BaseModel):
    phone: str
    code: str


class PhoneVerifyResponse(BaseModel):
    verified: bool
    access_token: str
    token_type: str
    expires_in: int
    aal: str
    maskedPhone: str | None


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/mfa/status", response_model=MfaStatusResponse)
async def mfa_status(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_membership),
) -> MfaStatusResponse:
    """Report the caller's MFA requirement + whether the session satisfies it."""
    user = await session.get(User, context.user_id)
    role = (user.role if user else context.role) or "viewer"
    tenant = await session.get(Tenant, context.tenant_id)
    settings = get_settings()
    # roleRequiresMfa reflects *effective* enforcement: only true when the master
    # switch is on, so the frontend gate doesn't redirect before MFA is live.
    role_requires = settings.mfa_enforcement_enabled and role_requires_mfa(role)
    # tenantRequiresMfa is true when the tenant has mandated 2FA for every member
    # (including non-admin roles). It is also gated by the platform MFA switch.
    tenant_requires = (
        settings.mfa_enforcement_enabled
        and bool(tenant.enforce_2fa if tenant else False)
    )
    satisfied = session_has_mfa(context.aal)
    factor = await get_active_factor(session, context.user_id)
    has_factor = factor is not None
    required_action: str | None = None
    if (role_requires or tenant_requires) and not satisfied:
        required_action = "challenge" if has_factor else "setup"
    return MfaStatusResponse(
        role=role,
        roleRequiresMfa=role_requires,
        tenantRequiresMfa=tenant_requires,
        aal=context.aal,
        mfaSatisfied=satisfied,
        hasVerifiedFactor=has_factor,
        maskedPhone=factor.masked_phone if factor else None,
        preferredFactorType=PREFERRED_FACTOR_TYPE,
        requiredAction=required_action,
    )


@router.post("/mfa/phone/start", response_model=PhoneStartResponse)
async def start_phone(
    payload: PhoneStartRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_membership),
) -> PhoneStartResponse:
    """Send an SMS verification code via Twilio Verify (enroll or challenge)."""
    settings = get_settings()
    phone = payload.phone.strip()
    if not E164.match(phone):
        raise HTTPException(
            status_code=400,
            detail="Enter a phone number in international format, e.g. +16615551212.",
        )

    # If a phone is already enrolled, a new number can't be used to challenge it;
    # the user must remove the old factor first (prevents silent takeover).
    existing = await get_active_factor(session, context.user_id)
    if existing is not None and not phone_matches_factor(existing, phone):
        raise HTTPException(
            status_code=400,
            detail="This number doesn't match the phone on file for your account.",
        )

    try:
        await start_mfa_verification(
            session,
            phone=phone,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        await session.commit()
    except MfaRateLimitedError as exc:
        await session.commit()
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please wait before requesting another code.",
            headers=(
                {"Retry-After": str(exc.retry_after_seconds)}
                if exc.retry_after_seconds
                else None
            ),
        ) from exc
    except TwilioConfigError as exc:
        await session.rollback()
        logger.warning("Twilio Verify not configured: %s", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="SMS verification isn't available yet. Contact your administrator.",
        ) from exc
    except TwilioVerifyError as exc:
        await session.rollback()
        logger.warning("Twilio Verify start failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail="We couldn't send the code. Please try again in a moment.",
        ) from exc

    return PhoneStartResponse(
        maskedPhone=mask_phone(phone),
        cooldownSeconds=settings.mfa_sms_resend_cooldown_seconds,
        status="pending",
    )


@router.post("/mfa/phone/verify", response_model=PhoneVerifyResponse)
async def verify_phone(
    payload: PhoneVerifyRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_membership),
) -> PhoneVerifyResponse:
    """Verify an SMS code; on success mint an aal2 token + persist the factor."""
    settings = get_settings()
    phone = payload.phone.strip()
    code = payload.code.strip()
    if not E164.match(phone):
        raise HTTPException(status_code=400, detail="Invalid phone number.")
    if not CODE.match(code):
        raise HTTPException(
            status_code=400, detail="Enter the numeric code from the text message."
        )

    existing = await get_active_factor(session, context.user_id)
    if existing is not None and not phone_matches_factor(existing, phone):
        raise HTTPException(
            status_code=400,
            detail="This number doesn't match the phone on file for your account.",
        )

    try:
        approved = await check_mfa_verification(
            session,
            phone=phone,
            code=code,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except TwilioConfigError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=503,
            detail="SMS verification isn't available yet. Contact your administrator.",
        ) from exc

    if not approved:
        # Persist the failed-attempt audit row before surfacing the error.
        await session.commit()
        raise HTTPException(
            status_code=400,
            detail="That code is incorrect or expired. Request a new one and try again.",
        )

    factor = await upsert_verified_factor(
        session,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        phone=phone,
    )
    await session.commit()

    token = create_access_token(
        sub=context.claims.sub,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        role=context.role,
        permissions=context.permissions,
        extra_claims={"aal": AAL2},
    )
    return PhoneVerifyResponse(
        verified=True,
        access_token=token,
        token_type="bearer",
        expires_in=settings.jwt_access_token_ttl_minutes * 60,
        aal=AAL2,
        maskedPhone=factor.masked_phone,
    )


@router.delete("/mfa/phone", status_code=status.HTTP_204_NO_CONTENT)
async def remove_phone(
    request: Request,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_membership),
) -> Response:
    """Remove the verified phone (disable MFA), unless the role requires it."""
    settings = get_settings()
    user = await session.get(User, context.user_id)
    role = (user.role if user else context.role) or "viewer"
    if settings.mfa_enforcement_enabled and role_requires_mfa(role):
        raise HTTPException(
            status_code=400,
            detail="SMS verification is required for your role and can't be removed.",
        )
    removed = await deactivate_factor(session, context.user_id)
    if removed:
        await record_event(
            session,
            event_type=MFA_SMS_FACTOR_REMOVED,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            status="removed",
        )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
