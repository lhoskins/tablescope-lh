"""Structured ``MFA_REQUIRED`` error + handler.

When an admin-role caller reaches a protected route with only an ``aal1``
session, the API returns the contract body documented in the MFA spec so the
client can redirect to setup/challenge:

    {
      "error": "MFA_REQUIRED",
      "message": "SMS multi-factor authentication is required for administrator access.",
      "requiresMfa": true,
      "requiredAction": "setup_or_challenge",
      "preferredFactorType": "phone"
    }
"""

from __future__ import annotations

from fastapi import Request, status
from fastapi.responses import JSONResponse

from app.auth.mfa_policy import PREFERRED_FACTOR_TYPE

MFA_REQUIRED_MESSAGE = (
    "SMS multi-factor authentication is required for administrator access."
)


def mfa_required_body() -> dict[str, object]:
    return {
        "error": "MFA_REQUIRED",
        "message": MFA_REQUIRED_MESSAGE,
        "requiresMfa": True,
        "requiredAction": "setup_or_challenge",
        "preferredFactorType": PREFERRED_FACTOR_TYPE,
    }


class MfaRequiredError(Exception):
    """Raised by enforcement when an admin session is missing aal2."""


async def mfa_required_handler(_: Request, __: MfaRequiredError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=mfa_required_body())
