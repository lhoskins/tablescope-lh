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
