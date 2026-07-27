"""JWT issuance and validation.

Tokens carry the following standard claims:

- `sub`: external user identifier
- `tenant_id`: numeric tenant (organization) id
- `user_id`: numeric user id within the platform-api database
- `org_id`: alias for `tenant_id` kept for redash-era compatibility
- `role`: one of `admin`, `editor`, `viewer`
- `permissions`: optional list of fine-grained permission strings
- `iss`, `aud`, `iat`, `exp`: standard JWT claims
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt
from pydantic import BaseModel, Field, ValidationError

from app.config import get_settings


class AuthError(Exception):
    """Raised when token decoding/validation fails."""


class TokenClaims(BaseModel):
    """Validated set of claims extracted from a JWT."""

    sub: str
    tenant_id: int
    user_id: int
    org_id: int | None = None
    role: str = "viewer"
    permissions: list[str] = Field(default_factory=list)
    aal: str | None = None
    #: Epoch seconds when this *session* began. Preserved across renewals so a
    #: sliding session still has an absolute lifetime.
    ses: int | None = None
    iss: str | None = None
    aud: str | None = None
    iat: int | None = None
    exp: int | None = None


def create_access_token(
    *,
    sub: str,
    tenant_id: int,
    user_id: int,
    role: str = "viewer",
    permissions: list[str] | None = None,
    expires_minutes: int | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Mint a new HS256 access token."""
    settings = get_settings()
    now = datetime.now(tz=UTC)
    ttl = expires_minutes if expires_minutes is not None else settings.jwt_access_token_ttl_minutes
    payload: dict[str, Any] = {
        "sub": sub,
        "tenant_id": tenant_id,
        "org_id": tenant_id,
        "user_id": user_id,
        "role": role,
        "permissions": permissions or [],
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl)).timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> TokenClaims:
    """Decode and validate a token. Raises `AuthError` on any failure."""
    settings = get_settings()
    try:
        raw = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
        )
    except JWTError as exc:
        raise AuthError(f"Invalid token: {exc}") from exc

    try:
        return TokenClaims.model_validate(raw)
    except ValidationError as exc:
        raise AuthError(f"Token missing required claims: {exc}") from exc


def renew_access_token(token: str) -> str | None:
    """Re-issue a still-valid token that is past halfway through its life.

    Sessions were a hard 60 minutes with no refresh path of any kind: the first
    request after the hour returned 401 and the client cleared its token and
    bounced to the login page. Anyone working for longer than an hour — reading
    a long analysis, waiting on an insight refresh — was logged out mid-task
    with no warning and no way to prevent it.

    Renewal here follows *activity*: any authenticated request past the halfway
    mark gets a fresh token carrying **every** existing claim. Preserving the
    claims wholesale matters — ``aal`` records that the user cleared 2FA, and
    re-minting without it would quietly downgrade a verified session.

    An idle session still dies on schedule (no requests, no renewal), and
    ``jwt_session_absolute_ttl_minutes`` caps how long activity can extend one
    before real re-authentication is required.

    Returns ``None`` when the token is not eligible — the caller keeps using the
    token it already has.
    """
    settings = get_settings()
    try:
        raw = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
        )
    except JWTError:
        return None

    iat, exp = raw.get("iat"), raw.get("exp")
    if not isinstance(iat, int) or not isinstance(exp, int):
        return None
    lifetime = exp - iat
    if lifetime <= 0:
        return None

    now = int(time.time())
    # Still in the first half of its life — nothing to do. This keeps renewal
    # off the hot path for the majority of requests.
    if exp - now > lifetime // 2:
        return None

    # Tokens minted before this feature have no `ses`; treat their issue time as
    # the session start so they are capped rather than renewable forever.
    session_start = raw.get("ses")
    if not isinstance(session_start, int):
        session_start = iat
    if now - session_start >= settings.jwt_session_absolute_ttl_minutes * 60:
        return None

    payload = {k: v for k, v in raw.items() if k not in {"iat", "exp"}}
    payload["ses"] = session_start
    payload["iat"] = now
    payload["exp"] = now + lifetime
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
