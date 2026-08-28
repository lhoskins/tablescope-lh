"""HMAC signature verification for requests from the Tablescope app server.

The app server signs every AI request with a shared secret (AI_SIGNING_SECRET).
The AI server verifies the signature before processing. This ensures that only
the trusted app server (which has already validated user permissions) can call
the AI API. The frontend never calls the AI server directly.
"""

import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import HTTPException, status

from app.core.config import settings

SIGNATURE_MAX_AGE_SECONDS = 300  # 5 minutes


def sign_request(payload: dict[str, Any]) -> str:
    """Generate HMAC-SHA256 signature for a request payload."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hmac.new(
        settings.ai_signing_secret.encode(),
        canonical.encode(),
        hashlib.sha256,
    ).hexdigest()


def verify_signature(payload: dict[str, Any], signature: str) -> None:
    """Verify HMAC signature. Raises 403 if invalid.

    An empty secret must never silently disable verification -- that is
    exactly the failure mode this function used to have (TS-ISO-007): it
    turned "the operator forgot to configure a secret" into "every request
    is accepted, signed or not." Deployments (including local dev, via
    docker-compose's shared default) must set a real, non-empty
    AI_SIGNING_SECRET; there is no unsigned fallback.
    """
    if not settings.ai_signing_secret:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="AI_SIGNING_SECRET is not configured",
        )

    # Check timestamp freshness
    timestamp = payload.get("timestamp", 0)
    if abs(time.time() - timestamp) > SIGNATURE_MAX_AGE_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request signature expired",
        )

    expected = sign_request(payload)
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid request signature",
        )
