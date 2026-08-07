"""Periodic QuickBooks OAuth2 token refresh and Teiid re-registration.

Runs as an arq cron job every ~15 minutes. It refreshes access tokens for
QuickBooks connector credentials that have a refresh token, persists the
rotated tokens, and re-deploys the live translator VDB block so queries keep
working after token expiry.
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
from app.models.database_data_source import DatabaseDataSource, DataSourceColumn
from app.models.saas_object_data_source import SaasObjectDataSource
from app.models.user_vdb import UserVDB
from app.services import database_introspection_service as intro
from app.services.crypto import encrypt_secret
from app.services.saas_source_service import SaasSourceError, decrypt_config
from app.services.teiid_registration_service import (
    TeiidRegistrationService,
    generate_teiid_names,
    generate_view_name,
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
    re_registered = 0
    async with SessionLocal() as session:
        stmt = select(SaasObjectDataSource).where(
            SaasObjectDataSource.credential_id == credential.id,
            SaasObjectDataSource.connector_type == "quickbooks",
            SaasObjectDataSource.sync_mode == "live",
        )
        saas_rows = list((await session.scalars(stmt)).all())
        if not saas_rows:
            return 0

        config = decrypt_config(credential)
        access_token = config.get("access_token", "")
        realm_id = str(config.get("realm_id") or "").strip()
        environment = str(config.get("environment") or "production").lower()

        for saas in saas_rows:
            ds = await session.get(DatabaseDataSource, saas.database_data_source_id)
            if ds is None:
                continue
            if ds.created_by is None:
                continue
            user_vdb = await session.scalar(
                select(UserVDB).where(
                    UserVDB.tenant_id == credential.tenant_id,
                    UserVDB.user_id == ds.created_by,
                )
            )
            if user_vdb is None:
                continue

            col_rows = list(
                (
                    await session.scalars(
                        select(DataSourceColumn)
                        .where(DataSourceColumn.data_source_id == ds.id)
                        .order_by(DataSourceColumn.ordinal_position)
                    )
                ).all()
            )
            columns = [
                {
                    "name": c.column_name,
                    "name_in_source": intro.source_identifier(ds.db_type, c.column_name),
                    "teiid_type": intro.map_to_teiid_type(c.data_type or "text"),
                }
                for c in col_rows
            ]

            names = generate_teiid_names(
                data_source_id=ds.id, db_type=ds.db_type, table_name=ds.table_name
            )
            view_name = ds.teiid_view_name or generate_view_name(
                display_name=ds.display_name, db_type=ds.db_type
            )

            reg = TeiidRegistrationService()
            try:
                await reg.register_quickbooks_source(
                    vdb_id=user_vdb.vdb_id,
                    org_id=credential.tenant_id,
                    user_id=ds.created_by,
                    access_token=access_token,
                    realm_id=realm_id,
                    environment=environment,
                    object_type=ds.table_name,
                    model_name=names["model_name"],
                    teiid_table_name=names["teiid_table_name"],
                    ds_name=names["ds_name"],
                    jndi_name=names["jndi_name"],
                    view_name=view_name,
                    columns=columns,
                )
                re_registered += 1
            except SaasSourceError:
                raise
            except Exception as exc:
                logger.warning(
                    "Failed to re-register QuickBooks source %s: %s",
                    saas.id,
                    exc,
                )
            finally:
                await reg.aclose()

    return re_registered


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
                    credential.id,
                    exc,
                )
    return {"refreshed": refreshed, "re_registered": re_registered}


refresh_quickbooks_tokens.keep_result = 0  # type: ignore[attr-defined]
