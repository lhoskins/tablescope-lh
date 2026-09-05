"""Google OAuth 2.0 authorization-code flow for the Drive Spreadsheet connector.

Tablescope registers ONE Google Cloud OAuth client (``google_drive_client_id``/
``google_drive_client_secret``) shared across every tenant -- each user
authorizes Tablescope's app against their own Drive account through Google's
standard consent screen; tenants never register their own OAuth app. Scopes
are read-only for this release (see the implementation plan section 12).

This mirrors the QuickBooks refresh-token pattern already used in this
codebase (``app/tasks/quickbooks_token_refresh.py``): tokens are stored as an
encrypted JSON blob on a ``ConnectorCredential`` row
(``connector_type="google_drive"``), never returned to the UI, and refreshed
periodically by a background task.
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.services.crypto import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"

#: How long an authorize -> callback round-trip has to complete. Generous
#: because it's bounded by the user actually clicking through Google's
#: consent screen, not a machine-to-machine call.
_STATE_TOKEN_MAX_AGE_SECONDS = 600


class GoogleOAuthError(Exception):
    """Raised when Google's OAuth endpoints reject a request.

    ``requires_reauth`` marks a failure the stored credential itself cannot
    recover from -- Google explicitly rejected the refresh grant (revoked/
    expired), as opposed to a transient network/connectivity failure -- so a
    caller can prompt the user to reconnect Google Drive instead of
    surfacing a dead-end error.
    """

    def __init__(self, message: str, *, requires_reauth: bool = False) -> None:
        super().__init__(message)
        self.requires_reauth = requires_reauth


class InvalidStateTokenError(GoogleOAuthError):
    """Raised when the ``state`` round-tripped from Google fails validation."""


def is_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.google_drive_client_id
        and settings.google_drive_client_secret
        and settings.google_drive_redirect_uri
    )


def create_state_token(
    *, tenant_id: int, user_id: int, credential_id: int | None = None
) -> str:
    """An authenticated, single-use, time-boxed CSRF token for the OAuth
    redirect round-trip.

    Stateless by design (no Redis/session dependency): the token IS the
    encrypted payload (tenant_id, user_id, a random nonce, issued-at), reusing
    the same Fernet primitive every other secret in this codebase is
    encrypted with. ``verify_state_token`` below re-derives and checks it on
    the way back from Google -- there is nothing else to keep server-side.

    ``credential_id``, when given, round-trips through the same encrypted
    payload so the callback can update that *existing* connection's tokens
    in place (a reconnect/reauthorize) instead of always creating a new
    ``ConnectorCredential`` row.
    """
    payload = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "credential_id": credential_id,
        "nonce": secrets.token_urlsafe(16),
        "iat": datetime.now(UTC).timestamp(),
    }
    return encrypt_secret(json.dumps(payload))


def verify_state_token(token: str, *, tenant_id: int, user_id: int) -> int | None:
    """Raise :class:`InvalidStateTokenError` unless ``token`` is a state
    token this same tenant/user issued within the allowed window.

    Returns the ``credential_id`` the token was created for (or ``None`` for
    a fresh-connection flow).
    """
    try:
        payload = json.loads(decrypt_secret(token))
    except Exception as exc:
        raise InvalidStateTokenError("Invalid or corrupted state token.") from exc
    if payload.get("tenant_id") != tenant_id or payload.get("user_id") != user_id:
        raise InvalidStateTokenError("State token does not match the caller.")
    age = datetime.now(UTC).timestamp() - float(payload.get("iat", 0))
    if age < 0 or age > _STATE_TOKEN_MAX_AGE_SECONDS:
        raise InvalidStateTokenError("State token has expired.")
    return payload.get("credential_id")


def build_authorization_url(*, state: str) -> str:
    """Return the URL to send the browser to for the Google consent screen."""
    settings = get_settings()
    if not is_configured():
        raise GoogleOAuthError(
            "Google Drive connector is not configured "
            "(google_drive_client_id/client_secret/redirect_uri)."
        )
    params = {
        "client_id": settings.google_drive_client_id,
        "redirect_uri": settings.google_drive_redirect_uri,
        "response_type": "code",
        "scope": settings.google_drive_oauth_scopes,
        "access_type": "offline",
        # Force a refresh token even if the user has authorized before --
        # without this, a re-consent can come back with no refresh_token.
        "prompt": "consent",
        "state": state,
        "include_granted_scopes": "true",
    }
    return f"{_AUTH_URL}?{urlencode(params)}"


async def exchange_code_for_tokens(*, code: str) -> dict[str, Any]:
    """Exchange a one-time authorization code for access/refresh tokens."""
    settings = get_settings()
    if not is_configured():
        raise GoogleOAuthError("Google Drive connector is not configured.")
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(
                _TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.google_drive_client_id,
                    "client_secret": settings.google_drive_client_secret,
                    "redirect_uri": settings.google_drive_redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
        except httpx.RequestError as exc:
            raise GoogleOAuthError(f"Failed to contact Google OAuth: {exc}") from exc
    if resp.status_code >= 400:
        logger.warning("Google OAuth code exchange rejected: %s", resp.text[:500])
        raise GoogleOAuthError("Google rejected the authorization code.")
    tokens = resp.json()
    if "refresh_token" not in tokens:
        # Happens when the user has already granted consent and Google skips
        # issuing a new refresh token -- prompt=consent above is meant to
        # prevent this, but callers should treat it as a hard requirement.
        raise GoogleOAuthError(
            "Google did not return a refresh token. Revoke Tablescope's "
            "access in your Google Account and reconnect."
        )
    return _normalize_token_response(tokens)


async def refresh_access_token(*, refresh_token: str) -> dict[str, Any]:
    """Exchange a stored refresh token for a new short-lived access token."""
    settings = get_settings()
    if not is_configured():
        raise GoogleOAuthError("Google Drive connector is not configured.")
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(
                _TOKEN_URL,
                data={
                    "refresh_token": refresh_token,
                    "client_id": settings.google_drive_client_id,
                    "client_secret": settings.google_drive_client_secret,
                    "grant_type": "refresh_token",
                },
                headers={"Accept": "application/json"},
            )
        except httpx.RequestError as exc:
            raise GoogleOAuthError(f"Failed to contact Google OAuth: {exc}") from exc
    if resp.status_code >= 400:
        logger.warning("Google OAuth token refresh rejected: %s", resp.text[:500])
        raise GoogleOAuthError("Google rejected the refresh token.", requires_reauth=True)
    tokens = resp.json()
    # A refresh grant does not always return a new refresh_token; keep the
    # caller's existing one in that case.
    tokens.setdefault("refresh_token", refresh_token)
    return _normalize_token_response(tokens)


def _normalize_token_response(tokens: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(tokens)
    expires_in = tokens.get("expires_in")
    if expires_in is not None:
        normalized["expires_at"] = datetime.now(UTC).timestamp() + float(expires_in)
    return normalized
