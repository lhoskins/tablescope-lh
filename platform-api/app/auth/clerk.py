"""Clerk / Supabase JWKS-backed token verification.

The default JWT scheme uses an HS256 secret shared between platform-api and
internal issuers. When the user authenticates via Clerk or Supabase, we
accept their RS256-signed tokens by fetching JWKS from the issuer and
verifying signatures against the public keys.

The verified third-party claims are then exchanged for a first-party
platform-api token via the `/api/auth/exchange` route (defined in
`app.routes.auth`).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from jose import JWTError, jwk, jwt
from jose.utils import base64url_decode

from app.auth.jwt import AuthError
from app.config import get_settings

logger = logging.getLogger(__name__)

_JWKS_CACHE_TTL_SECONDS = 600


@dataclass(slots=True)
class _CachedJWKS:
    keys: dict[str, dict[str, Any]] = field(default_factory=dict)
    fetched_at: float = 0.0


_cache: dict[str, _CachedJWKS] = {}


async def _load_jwks(jwks_url: str) -> dict[str, dict[str, Any]]:
    cached = _cache.get(jwks_url)
    now = time.time()
    if cached and (now - cached.fetched_at) < _JWKS_CACHE_TTL_SECONDS:
        return cached.keys

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(jwks_url)
        response.raise_for_status()
        payload = response.json()

    keys = {key["kid"]: key for key in payload.get("keys", []) if "kid" in key}
    _cache[jwks_url] = _CachedJWKS(keys=keys, fetched_at=now)
    return keys


async def verify_external_token(token: str, *, provider: str) -> dict[str, Any]:
    """Verify an RS256 JWT issued by Clerk or Supabase.

    Returns the decoded claims dict on success. Raises `AuthError` otherwise.
    """
    settings = get_settings()
    if provider == "clerk":
        jwks_url = settings.clerk_jwks_url
        issuer = settings.clerk_issuer
    elif provider == "supabase":
        jwks_url = settings.supabase_jwks_url
        issuer = settings.supabase_issuer
    else:
        raise AuthError(f"Unknown auth provider: {provider}")

    if not jwks_url or not issuer:
        raise AuthError(f"{provider} authentication is not configured")

    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise AuthError(f"Malformed token header: {exc}") from exc

    kid = unverified_header.get("kid")
    if not kid:
        raise AuthError("Token header missing `kid`")

    keys = await _load_jwks(jwks_url)
    key_data = keys.get(kid)
    if not key_data:
        # Refresh once in case the signing key rotated.
        _cache.pop(jwks_url, None)
        keys = await _load_jwks(jwks_url)
        key_data = keys.get(kid)
        if not key_data:
            raise AuthError(f"No JWKS key found for kid {kid}")

    try:
        public_key = jwk.construct(key_data)
    except JWTError as exc:
        raise AuthError(f"Invalid JWKS key: {exc}") from exc

    message, encoded_signature = token.rsplit(".", 1)
    decoded_signature = base64url_decode(encoded_signature.encode("utf-8"))
    if not public_key.verify(message.encode("utf-8"), decoded_signature):
        raise AuthError("Signature verification failed")

    try:
        claims = jwt.get_unverified_claims(token)
    except JWTError as exc:
        raise AuthError(f"Could not decode claims: {exc}") from exc

    if claims.get("iss") != issuer:
        raise AuthError(f"Unexpected issuer: {claims.get('iss')}")

    exp = claims.get("exp")
    if exp is not None and exp < int(time.time()):
        raise AuthError("Token expired")

    return claims
