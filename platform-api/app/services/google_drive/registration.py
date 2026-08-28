"""Persist a confirmed Google Sheet range as a live Teiid data source.

Workstream E: turn a ``SpreadsheetTableMapping`` into a query-builder-visible
``FileSourceMeta`` backed by the dormant Teiid google-spreadsheet translator.
"""

from __future__ import annotations

import logging
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.connector_credential import ConnectorCredential
from app.models.file_source_meta import FileSourceMeta
from app.models.spreadsheet_table_mapping import (
    SpreadsheetColumnMapping,
    SpreadsheetTableMapping,
)
from app.models.user_vdb import UserVDB
from app.services.auto_query import ensure_datasource_query
from app.services.saas_source_service import decrypt_config
from app.services.teiid_registration_service import (
    TeiidRegistrationError,
    TeiidRegistrationService,
    generate_teiid_names,
    generate_view_name,
    sanitize_identifier,
)
from app.services.vdb_warming import warm_vdb

logger = logging.getLogger(__name__)


class GoogleSheetsRegistrationError(Exception):
    """User-facing registration error."""


async def _register_google_sheet(
    session: AsyncSession,
    *,
    credential: ConnectorCredential,
    file_id: str,
    mapping: SpreadsheetTableMapping,
    child: FileSourceMeta,
    tenant_id: int,
    user_id: int,
) -> FileSourceMeta:
    """Register ``child`` as the live Teiid source for ``mapping``.

    Shared by first-time confirm and token-refresh re-registration.  The caller
    must have already flushed ``child`` so ``child.id`` is assigned.
    """
    parent = await session.get(FileSourceMeta, mapping.file_source_meta_id)
    if parent is None:
        raise GoogleSheetsRegistrationError("Parent file source record missing.")

    live_params = parent.live_source_params or {}
    if live_params.get("spreadsheet_id") != file_id:
        raise GoogleSheetsRegistrationError("Mapping does not belong to this file.")

    config = decrypt_config(credential)
    refresh_token = config.get("refresh_token")
    if not refresh_token:
        raise GoogleSheetsRegistrationError("No refresh token available; reconnect Google Drive.")

    settings = get_settings()
    client_id = settings.google_drive_client_id
    client_secret = settings.google_drive_client_secret
    if not client_id or not client_secret:
        raise GoogleSheetsRegistrationError("Google Drive OAuth client is not configured.")

    user_vdb = await session.scalar(
        select(UserVDB).where(
            UserVDB.tenant_id == tenant_id, UserVDB.user_id == user_id
        )
    )
    if user_vdb is None:
        raise GoogleSheetsRegistrationError("No VDB found for this user.")

    columns = list(
        (
            await session.scalars(
                select(SpreadsheetColumnMapping)
                .where(SpreadsheetColumnMapping.table_mapping_id == mapping.id)
                .order_by(SpreadsheetColumnMapping.ordinal)
            )
        ).all()
    )
    if not columns:
        raise GoogleSheetsRegistrationError("No columns found for this mapping.")

    sheet_name = mapping.sheet_name_at_creation
    safe_table = sanitize_identifier(sheet_name)
    names = generate_teiid_names(
        data_source_id=child.id,
        db_type="google-sheets",
        table_name=safe_table,
    )
    teiid_columns = [
        {
            "name": col.relational_name,
            "name_in_source": col.physical_column_ref,
            "teiid_type": col.teiid_type,
        }
        for col in columns
    ]

    reg = TeiidRegistrationService()
    try:
        body = await reg.register_google_sheets_source(
            vdb_id=user_vdb.vdb_id,
            org_id=tenant_id,
            user_id=user_id,
            spreadsheet_id=file_id,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            sheet_name=mapping.range_a1,
            teiid_table_name=names["teiid_table_name"],
            model_name=names["model_name"],
            ds_name=names["ds_name"],
            jndi_name=names["jndi_name"],
            view_name=child.view_name,
            columns=teiid_columns,
        )
    except TeiidRegistrationError as exc:
        raise GoogleSheetsRegistrationError(str(exc)) from exc
    finally:
        await reg.aclose()

    if isinstance(body, dict) and body.get("view_name"):
        child.view_name = str(body["view_name"])

    mapping.datasource_id = child.id
    mapping.project_id = child.project_id or mapping.project_id
    mapping.user_confirmed = True
    mapping.status = "confirmed"

    # Keep the child's live-source metadata in sync.
    child.live_source_params = {
        **live_params,
        "range_a1": mapping.range_a1,
        "connector_credential_id": credential.id,
    }
    child.column_types = [
        {
            "name": col.source_label,
            "field": col.relational_name,
            "type": col.classification or "string",
        }
        for col in columns
    ]

    try:
        await warm_vdb(
            user_vdb.vdb_id,
            vdb_host=settings.teiid_pg_host,
            vdb_port=settings.teiid_pg_port,
            connect_timeout=60.0,
            timeout=15.0,
            warm_views=False,
            max_concurrent_views=1,
            max_attempts=1,
            retry_delay=2.0,
        )
    except Exception as exc:  # pragma: no cover - best-effort warm
        logger.warning("Best-effort VDB warm failed for %s: %s", user_vdb.vdb_id, exc)

    if child.project_id is not None:
        await ensure_datasource_query(
            session,
            project_id=child.project_id,
            owner_id=user_id,
            display_name=child.file_name,
            view_name=child.view_name,
            columns=[col.relational_name for col in columns],
        )

    await session.commit()
    return child


async def confirm_and_register_google_sheet(
    session: AsyncSession,
    *,
    credential: ConnectorCredential,
    file_id: str,
    mapping: SpreadsheetTableMapping,
    display_name: str,
    project_id: int | None,
    tenant_id: int,
    user_id: int,
) -> FileSourceMeta:
    """Confirm a proposed mapping and register it in Teiid.

    Creates a new ``FileSourceMeta`` child row for the confirmed range, then
    calls the shared ``_register_google_sheet`` helper.
    """
    parent = await session.get(FileSourceMeta, mapping.file_source_meta_id)
    if parent is None:
        raise GoogleSheetsRegistrationError("Parent file source record missing.")

    if parent.tenant_id != tenant_id or parent.owner_id != user_id:
        raise GoogleSheetsRegistrationError("Not authorized to confirm this mapping.")

    effective_project_id = project_id or mapping.project_id
    child_view_name = f"{generate_view_name(display_name=display_name, db_type='GOOGLE')}_{secrets.token_hex(4)}"
    child = FileSourceMeta(
        tenant_id=tenant_id,
        owner_id=user_id,
        project_id=effective_project_id,
        view_name=child_view_name,
        file_name=display_name,
        vdb_type="user",
        source_format="google_sheet",
        acquisition_method="google_drive",
        live_source_params=parent.live_source_params or {},
    )
    session.add(child)
    await session.flush()  # assign child.id for deterministic Teiid names

    return await _register_google_sheet(
        session,
        credential=credential,
        file_id=file_id,
        mapping=mapping,
        child=child,
        tenant_id=tenant_id,
        user_id=user_id,
    )


async def reregister_google_sheet(
    session: AsyncSession,
    *,
    credential: ConnectorCredential,
    mapping: SpreadsheetTableMapping,
) -> FileSourceMeta:
    """Re-register an already-confirmed Google Sheet mapping (token refresh).

    The mapping's existing ``FileSourceMeta`` child is reused; only the
    Teiid/WildFly registration block is redeployed with the rotated token.
    """
    if mapping.datasource_id is None:
        raise GoogleSheetsRegistrationError("Mapping has not been confirmed yet.")

    child = await session.get(FileSourceMeta, mapping.datasource_id)
    if child is None:
        raise GoogleSheetsRegistrationError("Data source record for mapping missing.")

    live_params = child.live_source_params or {}
    file_id = live_params.get("spreadsheet_id")
    if not file_id:
        raise GoogleSheetsRegistrationError("No spreadsheet_id in data source params.")

    return await _register_google_sheet(
        session,
        credential=credential,
        file_id=file_id,
        mapping=mapping,
        child=child,
        tenant_id=child.tenant_id,
        user_id=child.owner_id,
    )
