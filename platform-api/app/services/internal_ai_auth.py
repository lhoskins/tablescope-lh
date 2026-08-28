"""HMAC authentication for ai-server -> platform-api internal callbacks.

Mirrors the existing platform-api -> ai-server signing scheme
(``ai_proxy_shared._sign_payload`` / ``ai_intelligence_client.transport``)
for the reverse direction, using the same shared secret
(``tablescope_ai_signing_secret`` here, ``AI_SIGNING_SECRET`` on ai-server).

Security fix for TS-ISO-001: ``/api/ai/permissions`` previously accepted
caller-supplied tenant/user/project identifiers with no authentication at
all. This gives ai-server (the only intended caller) a way to prove the
request is really from it -- reachability through the public ``/api/``
nginx location no longer matters once every request must carry a valid,
fresh, single-use signature that only ai-server can produce.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any

from fastapi import HTTPException, status

from app.config import get_settings

logger = logging.getLogger(__name__)

#: How stale a signed request's timestamp may be before it's rejected.
#: Generous enough for clock skew and network latency, tight enough that a
#: captured request can't be replayed indefinitely.
MAX_SIGNATURE_AGE_SECONDS = 120


class InternalAuthError(HTTPException):
    """A constant, minimal 403 -- never echoes back why, so a caller probing
    for a valid signature/timestamp combination gets no signal either way."""

    def __init__(self) -> None:
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


def sign_internal_payload(payload: dict[str, Any], secret: str) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def _verify_signature(payload: dict[str, Any], secret: str) -> None:
    """Raise :class:`InternalAuthError` unless ``payload["signature"]``
    matches the HMAC of every other field, using constant-time comparison."""
    signature = payload.get("signature")
    if not signature or not isinstance(signature, str):
        raise InternalAuthError()
    unsigned = {k: v for k, v in payload.items() if k != "signature"}
    expected = sign_internal_payload(unsigned, secret)
    if not hmac.compare_digest(signature, expected):
        raise InternalAuthError()


def _verify_timestamp(payload: dict[str, Any]) -> None:
    timestamp = payload.get("timestamp")
    if not isinstance(timestamp, int | float):
        raise InternalAuthError()
    age = time.time() - float(timestamp)
    if age < -10 or age > MAX_SIGNATURE_AGE_SECONDS:
        raise InternalAuthError()


async def _check_and_record_replay(payload: dict[str, Any]) -> None:
    """Reject a signature this window has already seen once.

    Keyed on the signature itself (unguessable without the shared secret, and
    unique per request since every signed payload embeds a fresh timestamp) --
    no separate request-id field is required from the caller. Fails open
    (logs and allows) if Redis is unavailable, matching every other
    best-effort cache in this codebase; the timestamp window above is the
    primary defense and does not depend on Redis.
    """
    signature = payload.get("signature")
    if not signature:
        return
    try:
        from app.services.home_intel_queue import get_redis

        redis_client = get_redis()
        key = f"internal-auth:replay:{signature}"
        was_set = await redis_client.set(
            key, "1", nx=True, ex=MAX_SIGNATURE_AGE_SECONDS + 30
        )
        if not was_set:
            raise InternalAuthError()
    except InternalAuthError:
        raise
    except Exception:
        logger.warning("Replay-protection check failed open (Redis unavailable)")


async def verify_internal_ai_request(payload: dict[str, Any]) -> None:
    """Verify a request body signed by ai-server's outbound HMAC signer.

    Raises :class:`InternalAuthError` (403) unless the signature is valid,
    fresh, and not a replay. Call this before touching the database or
    building any response -- no partial/advisory result on failure.
    """
    settings = get_settings()
    secret = settings.tablescope_ai_signing_secret
    if not secret:
        # An empty secret must never silently disable verification (that was
        # exactly TS-ISO-007's failure mode on the other leg of this same
        # HMAC scheme). App startup already refuses to boot in production
        # with this unset (see app.main's startup check) -- this is the
        # non-production fallback, and it must fail closed, not open.
        raise InternalAuthError()
    _verify_signature(payload, secret)
    _verify_timestamp(payload)
    await _check_and_record_replay(payload)
