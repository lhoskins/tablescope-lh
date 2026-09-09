"""Periodic QuickBooks OAuth2 token refresh and Teiid re-registration.

Runs as an arq cron job every ~15 minutes. It refreshes access tokens for
QuickBooks connector credentials that have a refresh token, persists the
rotated tokens, and re-registers every live-translator source backed by that
credential (``reregister_live_saas_sources_for_credential``, shared with the
manual-reconnect path in ``saas_sources.py``'s ``update_credential``) so
queries keep working after token expiry.
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import UTC, datetime

import httpx
from sqlalchemy import select

from app.database import SessionLocal
from app.models.connector_credential import ConnectorCredential
from app.services.crypto import encrypt_secret
from app.services.saas_source_service import (
    decrypt_config,
    reregister_live_saas_sources_for_credential,
)

logger = logging.getLogger(__name__)

_REFRESH_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
_PRODUCTION_BASE = "https://quickbooks.api.intuit.com"
_SANDBOX_BASE = "https://sandbox-quickbooks.api.intuit.com"


def _base_url(environment: str) -> str:
    return _SANDBOX_BASE if str(environment).lower() == "sandbox" else _PRODUCTION_BASE


async def _refresh_quickbooks_credential(credential: ConnectorCredential) -> bool:
    """Refresh a single QuickBooks credential and return True if changed."""
    config = decrypt_config(credential)
    refresh_token = config.get("refresh_token")
    client_id = config.get("client_id")
    client_secret = config.get("client_secret")
    if not refresh_token or not client_id or not client_secret:
        logger.debug(
            "QuickBooks credential %s missing refresh material; skipping.", credential.id
        )
        return False

    basic = base64.b64encode(
        f"{client_id}:{client_secret}".encode()
    ).decode()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                _REFRESH_URL,
                headers={
                    "Authorization": f"Basic {basic}",
                    "Accept": "application/json",
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
            )
            resp.raise_for_status()
            tokens = resp.json()
    except Exception as exc:
        logger.warning(
            "QuickBooks token refresh failed for credential %s: %s",
            credential.id,
            exc,
        )
        return False

    config["access_token"] = tokens.get("access_token", config.get("access_token", ""))
    if "refresh_token" in tokens:
        config["refresh_token"] = tokens["refresh_token"]
    if "expires_in" in tokens:
        config["expires_at"] = (
            datetime.now(UTC).timestamp() + tokens["expires_in"]
        )
    credential.secret_encrypted = encrypt_secret(json.dumps(config))
    return True


async def _reregister_live_quickbooks_sources(credential: ConnectorCredential) -> int:
    """Re-register every live QuickBooks source backed by this credential."""
    async with SessionLocal() as session:
        return await reregister_live_saas_sources_for_credential(session, credential)


async def refresh_quickbooks_tokens(ctx: dict[str, object]) -> dict[str, int]:
    """Cron entrypoint: refresh QuickBooks tokens and re-register live sources."""
    refreshed = 0
    re_registered = 0
    async with SessionLocal() as session:
        stmt = select(ConnectorCredential).where(
            ConnectorCredential.connector_type == "quickbooks"
        )
        credentials = list((await session.scalars(stmt)).all())
        for credential in credentials:
            try:
                # An earlier credential's failure and rollback in this same
                # loop expires every object in the session -- including
                # every column, id included -- regardless of
                # expire_on_commit. Refresh must run, inside this awaited
                # context, before ANY attribute of this credential (even
                # credential.id below) is read synchronously, or that read
                # hits an unawaited refresh and raises MissingGreenlet.
                await session.refresh(credential)
                credential_id = credential.id
                if await _refresh_quickbooks_credential(credential):
                    refreshed += 1
                    re_registered += await _reregister_live_quickbooks_sources(
                        credential
                    )
                await session.commit()
            except Exception as exc:
                await session.rollback()
                logger.warning(
                    "QuickBooks token refresh error for credential %s: %s",
                    credential_id,
                    exc,
                )
    return {"refreshed": refreshed, "re_registered": re_registered}


refresh_quickbooks_tokens.keep_result = 0  # type: ignore[attr-defined]
