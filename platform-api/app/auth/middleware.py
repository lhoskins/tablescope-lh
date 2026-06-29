"""Authentication middleware.

Resolves credentials in priority order:

1. `X-API-Key` header  → service-to-service caller (synthesizes claims)
2. `Authorization: Bearer <jwt>` → user/JWT token

If a credential is present and valid, `request.state.context` is populated
with a `RequestContext` so downstream dependencies can read tenant/user info.
Anonymous requests are allowed through; route-level dependencies decide
whether anonymous access is acceptable.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth.context import RequestContext
from app.auth.jwt import AuthError, TokenClaims, decode_access_token
from app.config import get_settings

logger = logging.getLogger(__name__)

_ANONYMOUS_PATH_PREFIXES = (
    "/health",
    "/metrics",
    "/openapi.json",
    "/docs",
    "/redoc",
    "/api/auth/login",
    "/api/auth/exchange",
    "/api/auth/hooks/send-sms",
    "/api/billing/catalog",
    "/api/billing/checkout/session",
    "/api/billing/stripe/webhook",
    "/api/provisioning/status",
)

# Avatars are served by opaque URL for <img> tags (which cannot send a bearer
# token); reads are anonymous, uploads remain authenticated.
_ANONYMOUS_PATH_RE = re.compile(r"^/api/users/\d+/avatar/?$")


def _is_anonymous_path(path: str) -> bool:
    if any(path.startswith(prefix) for prefix in _ANONYMOUS_PATH_PREFIXES):
        return True
    return bool(_ANONYMOUS_PATH_RE.match(path))


def _synthesize_service_claims(api_key: str) -> TokenClaims:
    """Build a `TokenClaims` object for a trusted service caller.

    Service callers do not have a real tenant; they get tenant_id=0 and
    user_id=0 with role=admin. Routes that should not be reachable by
    services must check `context.is_service` explicitly.
    """
    return TokenClaims(
        sub=f"service:{api_key[:8]}",
        tenant_id=0,
        user_id=0,
        org_id=0,
        role="admin",
        permissions=["service:*"],
    )


class AuthMiddleware(BaseHTTPMiddleware):
    """Populates `request.state.context` from API key or Bearer token."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        settings = get_settings()
        path = request.url.path

        if _is_anonymous_path(path):
            return await call_next(request)

        api_key = request.headers.get("x-api-key")
        if api_key and api_key in settings.service_api_key_set:
            request.state.context = RequestContext(
                claims=_synthesize_service_claims(api_key),
                is_service=True,
            )
            return await call_next(request)

        authorization = request.headers.get("authorization")
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization.split(" ", 1)[1].strip()
            try:
                claims = decode_access_token(token)
            except AuthError as exc:
                logger.info("Rejected JWT: %s", exc)
                return JSONResponse(
                    {"detail": "Invalid or expired token"},
                    status_code=401,
                )
            request.state.context = RequestContext(claims=claims, is_service=False)

        return await call_next(request)
