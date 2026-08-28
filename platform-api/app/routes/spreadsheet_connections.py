"""Google Drive Spreadsheet connector routes (Data Source Builder).

Increment 1 of the implementation plan: OAuth connection + read-only file/
tab/range discovery. Deliberately stops short of creating a Teiid data
source -- that requires a live-environment spike against the Teiid
registration servlet (see ``TeiidRegistrationService`` and the Devin handoff
notes) that could not be verified in this environment.

All routes are gated by ``settings.google_drive_connector_v1_enabled``
(default off) in addition to normal tenant/role authorization, so this ships
dark until explicitly turned on per the plan's rollout section.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.database import get_db
from app.models.connector_credential import ConnectorCredential
from app.models.file_source_meta import FileSourceMeta
from app.models.spreadsheet_table_mapping import (
    SpreadsheetColumnMapping,
    SpreadsheetTableMapping,
)
from app.services import google_drive as gd
from app.services.crypto import encrypt_secret
from app.services.google_drive.detection import detect_google_sheet_tables
from app.services.google_drive.registration import (
    GoogleSheetsRegistrationError,
    confirm_and_register_google_sheet,
)
from app.services.saas_source_service import decrypt_config
from app.services.teiid_registration_service.naming import sanitize_identifier

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/spreadsheet-connections", tags=["spreadsheet-connector"])

_CONNECTOR_TYPE = "google_drive"


def _require_feature_enabled() -> None:
    if not get_settings().google_drive_connector_v1_enabled:
        raise HTTPException(
            status_code=404,
            detail="The Google Drive Spreadsheet connector is not enabled.",
        )


def _parent_view_name(file_id: str, sheet_name: str) -> str:
    h = hashlib.sha256(file_id.encode()).hexdigest()[:16]
    return f"gdrive_{h}_{sanitize_identifier(sheet_name)}"


async def _load_credential(
    session: AsyncSession, credential_id: int, tenant_id: int
) -> ConnectorCredential:
    credential = await session.scalar(
        select(ConnectorCredential).where(
            ConnectorCredential.id == credential_id,
            ConnectorCredential.tenant_id == tenant_id,
            ConnectorCredential.connector_type == _CONNECTOR_TYPE,
        )
    )
    if credential is None:
        raise HTTPException(status_code=404, detail="Connection not found.")
    return credential


async def _valid_access_token(
    session: AsyncSession, credential: ConnectorCredential
) -> str:
    """Return a non-expired access token, refreshing and persisting it first
    if the stored one is expired or about to expire."""
    config = decrypt_config(credential)
    access_token = config.get("access_token", "")
    expires_at = float(config.get("expires_at", 0) or 0)
    # Refresh a little early so a request in flight doesn't race expiry.
    if access_token and datetime.now(UTC).timestamp() < expires_at - 60:
        return access_token

    refresh_token = config.get("refresh_token")
    if not refresh_token:
        raise HTTPException(
            status_code=409,
            detail="This connection has no refresh token; reconnect Google Drive.",
        )
    try:
        tokens = await gd.refresh_access_token(refresh_token=refresh_token)
    except gd.GoogleOAuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    config["access_token"] = tokens["access_token"]
    config["refresh_token"] = tokens.get("refresh_token", refresh_token)
    if "expires_at" in tokens:
        config["expires_at"] = tokens["expires_at"]
    credential.secret_encrypted = encrypt_secret(json.dumps(config))
    await session.commit()
    return config["access_token"]


class AuthorizeResponse(BaseModel):
    authorizationUrl: str
    state: str


@router.post("/authorize", response_model=AuthorizeResponse)
async def start_authorization(
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> AuthorizeResponse:
    """Step 1 of the OAuth flow: return the URL to send the browser to.

    The frontend redirects the user there; Google redirects back to
    ``settings.google_drive_redirect_uri`` with ``code``/``state``, which the
    frontend then posts to ``/callback`` below.
    """
    _require_feature_enabled()
    if not gd.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Google Drive connector is not configured on this server.",
        )
    state = gd.create_state_token(tenant_id=context.tenant_id, user_id=context.user_id)
    return AuthorizeResponse(
        authorizationUrl=gd.build_authorization_url(state=state), state=state
    )


class CallbackRequest(BaseModel):
    code: str = Field(min_length=1)
    state: str = Field(min_length=1)
    display_name: str = Field(default="Google Drive", max_length=255)


@router.post("/callback")
async def complete_authorization(
    req: CallbackRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Step 2: exchange the authorization code and persist the connection."""
    _require_feature_enabled()
    try:
        gd.verify_state_token(
            req.state, tenant_id=context.tenant_id, user_id=context.user_id
        )
    except gd.InvalidStateTokenError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        tokens = await gd.exchange_code_for_tokens(code=req.code)
    except gd.GoogleOAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    credential = ConnectorCredential(
        tenant_id=context.tenant_id,
        created_by=context.user_id,
        connector_type=_CONNECTOR_TYPE,
        display_name=req.display_name,
        secret_encrypted=encrypt_secret(json.dumps(tokens)),
    )
    session.add(credential)
    await session.commit()
    return credential.to_dict()


@router.get("")
async def list_connections(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[dict[str, Any]]:
    _require_feature_enabled()
    rows = (
        await session.scalars(
            select(ConnectorCredential)
            .where(
                ConnectorCredential.tenant_id == context.tenant_id,
                ConnectorCredential.connector_type == _CONNECTOR_TYPE,
            )
            .order_by(ConnectorCredential.display_name)
        )
    ).all()
    return [c.to_dict() for c in rows]


@router.delete("/{connection_id}")
async def delete_connection(
    connection_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    credential = await _load_credential(session, connection_id, context.tenant_id)
    await session.delete(credential)
    await session.commit()
    return {"deleted": True}


@router.get("/{connection_id}/files")
async def list_files(
    connection_id: int,
    page_token: str | None = None,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """List Drive files this connection can access, filtered to supported
    types (native Sheets, Excel, CSV)."""
    _require_feature_enabled()
    credential = await _load_credential(session, connection_id, context.tenant_id)
    access_token = await _valid_access_token(session, credential)
    client = gd.GoogleDriveClient(access_token)
    try:
        return await client.list_supported_files(page_token=page_token)
    except gd.GoogleDriveError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{connection_id}/files/{file_id}/tabs")
async def list_file_tabs(
    connection_id: int,
    file_id: str,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """List tabs for a native Google Sheets file. Excel/CSV each expose one
    logical tab named after the file (plan section 5, Step 4) -- the caller
    should skip this call for those MIME types and use the file itself."""
    _require_feature_enabled()
    credential = await _load_credential(session, connection_id, context.tenant_id)
    access_token = await _valid_access_token(session, credential)
    client = gd.GoogleDriveClient(access_token)
    try:
        tabs = await client.list_sheet_tabs(file_id)
    except gd.GoogleDriveError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"tabs": tabs}


class PreviewRangeRequest(BaseModel):
    range_a1: str = Field(min_length=1, max_length=128)


@router.post("/{connection_id}/files/{file_id}/preview-range")
async def preview_range(
    connection_id: int,
    file_id: str,
    req: PreviewRangeRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Preview a range's current values. Uses UNFORMATTED_VALUE so a
    too-narrow column showing "#####" in Sheets/Excel is read as its real
    underlying number, never as literal "#####" text (plan section 6.3, 10)."""
    _require_feature_enabled()
    credential = await _load_credential(session, connection_id, context.tenant_id)
    access_token = await _valid_access_token(session, credential)
    client = gd.GoogleDriveClient(access_token)
    try:
        values = await client.get_range_values(file_id, req.range_a1)
    except gd.GoogleDriveError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"rangeA1": req.range_a1, "values": values}


class DetectTablesRequest(BaseModel):
    sheet_name: str | None = None
    max_rows: int = Field(default=1000, ge=1, le=50000)
    project_id: int | None = None


@router.post("/{connection_id}/files/{file_id}/detect-tables")
async def detect_tables(
    connection_id: int,
    file_id: str,
    req: DetectTablesRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Detect a single rectangular table on a sheet (Workstream D fallback).

    Creates a proposed ``SpreadsheetTableMapping`` and child
    ``SpreadsheetColumnMapping`` rows for the first (or requested) tab.  The
    mapping is not registered in Teiid until ``confirm`` is called.
    """
    _require_feature_enabled()
    credential = await _load_credential(session, connection_id, context.tenant_id)
    access_token = await _valid_access_token(session, credential)
    client = gd.GoogleDriveClient(access_token)

    try:
        detected = await detect_google_sheet_tables(
            client,
            file_id,
            sheet_name=req.sheet_name,
            max_rows=req.max_rows,
        )
    except gd.GoogleDriveError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    parent_view = _parent_view_name(file_id, detected["sheet_name"])
    parent = await session.scalar(
        select(FileSourceMeta).where(
            FileSourceMeta.tenant_id == context.tenant_id,
            FileSourceMeta.owner_id == context.user_id,
            FileSourceMeta.view_name == parent_view,
        )
    )
    if parent is None:
        parent = FileSourceMeta(
            tenant_id=context.tenant_id,
            owner_id=context.user_id,
            project_id=req.project_id,
            view_name=parent_view,
            file_name=detected["file_name"],
            vdb_type="user",
            source_format="google_sheet",
            acquisition_method="google_drive",
            live_source_params={
                "spreadsheet_id": file_id,
                "sheet_name": detected["sheet_name"],
            },
        )
        session.add(parent)
        await session.flush()

    mapping = await session.scalar(
        select(SpreadsheetTableMapping).where(
            SpreadsheetTableMapping.file_source_meta_id == parent.id,
            SpreadsheetTableMapping.range_a1 == detected["range_a1"],
        )
    )
    if mapping is None:
        mapping = SpreadsheetTableMapping(
            tenant_id=context.tenant_id,
            project_id=req.project_id,
            file_source_meta_id=parent.id,
            sheet_stable_id=None,
            sheet_name_at_creation=detected["sheet_name"],
            table_name=detected["table_name"],
            range_a1=detected["range_a1"],
            range_policy="dynamic_rows",
            header_row_index=detected["header_row_index"],
            data_start_row_index=detected["data_start_row_index"],
            anchor_fingerprint=detected["anchor_fingerprint"],
            detection_method=detected["detection_method"],
            detection_confidence=1.0,
            user_confirmed=False,
            status="proposed",
        )
        session.add(mapping)
        await session.flush()

        for col in detected["columns"]:
            session.add(
                SpreadsheetColumnMapping(
                    table_mapping_id=mapping.id,
                    ordinal=col["ordinal"],
                    source_label=col["source_label"],
                    physical_column_ref=col["physical_column_ref"],
                    relational_name=col["relational_name"],
                    teiid_type=col["teiid_type"],
                    classification=col["classification"],
                )
            )
        await session.flush()

    columns = list(
        (
            await session.scalars(
                select(SpreadsheetColumnMapping)
                .where(SpreadsheetColumnMapping.table_mapping_id == mapping.id)
                .order_by(SpreadsheetColumnMapping.ordinal)
            )
        ).all()
    )

    await session.commit()
    return {
        "fileSourceMetaId": parent.id,
        "mapping": mapping.to_dict(),
        "columns": [c.to_dict() for c in columns],
    }


class ConfirmTableRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)
    project_id: int | None = None


@router.post("/{connection_id}/files/{file_id}/tables/{mapping_id}/confirm")
async def confirm_table(
    connection_id: int,
    file_id: str,
    mapping_id: int,
    req: ConfirmTableRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Confirm a proposed table mapping and register it as a live Teiid source.

    This is Workstream E: it creates the query-builder-visible ``FileSourceMeta``
    row, calls the google-spreadsheet translator via the Teiid servlet, and
    optionally auto-creates a project saved query.
    """
    _require_feature_enabled()
    credential = await _load_credential(session, connection_id, context.tenant_id)
    mapping = await session.get(SpreadsheetTableMapping, mapping_id)
    if mapping is None or mapping.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Table mapping not found.")

    try:
        child = await confirm_and_register_google_sheet(
            session,
            credential=credential,
            file_id=file_id,
            mapping=mapping,
            display_name=req.display_name,
            project_id=req.project_id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
    except GoogleSheetsRegistrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return child.to_dict()
