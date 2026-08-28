"""Periodic Google Drive OAuth2 token refresh.

Mirrors ``app/tasks/quickbooks_token_refresh.py``: runs as an arq cron job,
refreshes access tokens for connector credentials that have a refresh token,
and persists the rotated tokens. Unlike the QuickBooks task, this does not
yet re-register any live Teiid source -- Workstream E (Teiid range-aware
execution) has not landed, so there is nothing live to re-register against
token rotation yet. Add that step here once it does, following the same
pattern as ``_reregister_live_quickbooks_sources``.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import select

from app.database import SessionLocal
from app.models.connector_credential import ConnectorCredential
from app.models.file_source_meta import FileSourceMeta
from app.models.spreadsheet_table_mapping import SpreadsheetTableMapping
from app.services import google_drive as gd
from app.services.crypto import encrypt_secret
from app.services.google_drive.registration import (
    GoogleSheetsRegistrationError,
    reregister_google_sheet,
)
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
    re_registered = 0
    async with SessionLocal() as session:
        stmt = select(SpreadsheetTableMapping).where(
            SpreadsheetTableMapping.tenant_id == credential.tenant_id,
            SpreadsheetTableMapping.status == "confirmed",
            SpreadsheetTableMapping.datasource_id.is_not(None),
        )
        mappings = list((await session.scalars(stmt)).all())
        for mapping in mappings:
            child = await session.get(FileSourceMeta, mapping.datasource_id)
            if child is None:
                continue
            live_params = child.live_source_params or {}
            if live_params.get("connector_credential_id") != credential.id:
                continue
            try:
                await reregister_google_sheet(
                    session, credential=credential, mapping=mapping
                )
                re_registered += 1
            except GoogleSheetsRegistrationError as exc:
                logger.warning(
                    "Failed to re-register Google Drive mapping %s after token refresh: %s",
                    mapping.id,
                    exc,
                )
    return re_registered


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
                    credential.id,
                    exc,
                )
    return {"refreshed": refreshed, "re_registered": re_registered}


refresh_google_drive_tokens.keep_result = 0  # type: ignore[attr-defined]
