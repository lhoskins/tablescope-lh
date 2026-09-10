"""Periodic Google Drive OAuth2 token refresh.

Mirrors ``app/tasks/quickbooks_token_refresh.py``: runs as an arq cron job,
refreshes access tokens for connector credentials that have a refresh token,
persists the rotated tokens, and re-registers every live Teiid source backed
by that credential (``reregister_live_sources_for_credential``) so an
already-registered source picks up the new token instead of continuing to
run on the one it was confirmed with.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import select

from app.database import SessionLocal
from app.models.connector_credential import ConnectorCredential
from app.services import google_drive as gd
from app.services.crypto import encrypt_secret
from app.services.google_drive.registration import reregister_live_sources_for_credential
from app.services.saas_source_service import decrypt_config

logger = logging.getLogger(__name__)

_CONNECTOR_TYPE = "google_drive"


async def _refresh_google_drive_credential(credential: ConnectorCredential) -> bool:
    """Refresh a single Google Drive credential. Returns True if changed."""
    config = decrypt_config(credential)
    refresh_token = config.get("refresh_token")
    if not refresh_token:
        logger.debug(
            "Google Drive credential %s has no refresh token; skipping.",
            credential.id,
        )
        return False

    try:
        tokens = await gd.refresh_access_token(refresh_token=refresh_token)
    except gd.GoogleOAuthError as exc:
        logger.warning(
            "Google Drive token refresh failed for credential %s: %s",
            credential.id,
            exc,
        )
        return False

    config["access_token"] = tokens["access_token"]
    config["refresh_token"] = tokens.get("refresh_token", refresh_token)
    if "expires_at" in tokens:
        config["expires_at"] = tokens["expires_at"]
    credential.secret_encrypted = encrypt_secret(json.dumps(config))
    return True


async def _reregister_live_google_drive_sources(
    credential: ConnectorCredential,
) -> int:
    """Re-register every confirmed Google Drive mapping backed by this credential."""
    async with SessionLocal() as session:
        return await reregister_live_sources_for_credential(session, credential)


async def refresh_google_drive_tokens(ctx: dict[str, object]) -> dict[str, int]:
    """Cron entrypoint: refresh every Google Drive connector credential."""
    refreshed = 0
    re_registered = 0
    async with SessionLocal() as session:
        stmt = select(ConnectorCredential).where(
            ConnectorCredential.connector_type == _CONNECTOR_TYPE
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
                if await _refresh_google_drive_credential(credential):
                    refreshed += 1
                    re_registered += await _reregister_live_google_drive_sources(
                        credential
                    )
                await session.commit()
            except Exception as exc:
                await session.rollback()
                logger.warning(
                    "Google Drive token refresh error for credential %s: %s",
                    credential_id,
                    exc,
                )
    return {"refreshed": refreshed, "re_registered": re_registered}


refresh_google_drive_tokens.keep_result = 0  # type: ignore[attr-defined]
