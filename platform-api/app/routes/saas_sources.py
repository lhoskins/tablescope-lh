"""SaaS connector routes (HubSpot, Salesforce).

Mirrors the database-table workflow but for SaaS apps:

    create credential -> test -> objects -> fields -> preview -> create -> sync

A created SaaS source syncs the selected object into a local Postgres staging
table which is registered in Teiid through the database-table pipeline, so it
lists, queries and joins like any other source.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.connectors.base import SaasConnectorError
from app.connectors.registry import get_connector, supported_connectors
from app.database import get_db
from app.models.connector_credential import ConnectorCredential
from app.models.database_data_source import DatabaseDataSource
from app.models.saas_object_data_source import SaasObjectDataSource
from app.schemas.saas_source import (
    CreateCredentialRequest,
    CreateSaasSourceRequest,
    FieldsRequest,
    ObjectsRequest,
    PreviewRequest,
    SyncRequest,
    TestCredentialRequest,
    UpdateCredentialRequest,
)
from app.services.crypto import encrypt_secret
from app.services.saas_source_service import (
    SaasSourceError,
    create_saas_source,
    decrypt_config,
    run_sync,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/saas-sources", tags=["saas-sources"])


@router.get("/connectors")
async def list_connectors(
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict:
    return {"connectors": supported_connectors()}


# --- Credentials ---------------------------------------------------------


@router.post("/credentials")
async def create_credential(
    body: CreateCredentialRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    if body.connector_type not in supported_connectors():
        raise HTTPException(
            status_code=400, detail=f"Unknown connector: {body.connector_type}"
        )
    cred = ConnectorCredential(
        tenant_id=context.tenant_id,
        created_by=context.user_id,
        connector_type=body.connector_type,
        display_name=body.display_name,
        secret_encrypted=encrypt_secret(json.dumps(body.config or {})),
        last_tested_at=datetime.now(UTC),
    )
    session.add(cred)
    await session.commit()
    await session.refresh(cred)
    return cred.to_dict()


@router.patch("/credentials/{credential_id}")
async def update_credential(
    credential_id: int,
    body: UpdateCredentialRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    cred = await session.get(ConnectorCredential, credential_id)
    if cred is None or cred.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Credential not found")
    if body.display_name:
        cred.display_name = body.display_name
    if body.config is not None:
        cred.secret_encrypted = encrypt_secret(json.dumps(body.config))
        cred.last_tested_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(cred)
    return cred.to_dict()


@router.get("/credentials")
async def list_credentials(
    connector_type: str | None = None,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[dict]:
    stmt = select(ConnectorCredential).where(
        ConnectorCredential.tenant_id == context.tenant_id
    )
    if connector_type:
        stmt = stmt.where(ConnectorCredential.connector_type == connector_type)
    rows = (await session.scalars(stmt)).all()
    return [r.to_dict() for r in rows]


@router.delete("/credentials/{credential_id}")
async def delete_credential(
    credential_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    cred = await session.get(ConnectorCredential, credential_id)
    if cred is None or cred.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Credential not found")
    in_use = await session.scalar(
        select(SaasObjectDataSource).where(
            SaasObjectDataSource.credential_id == credential_id
        )
    )
    if in_use is not None:
        raise HTTPException(
            status_code=409,
            detail="Credential is in use by one or more data sources.",
        )
    await session.delete(cred)
    await session.commit()
    return {"status": "deleted", "id": credential_id}


async def _resolve_config(
    body: TestCredentialRequest,
    session: AsyncSession,
    tenant_id: int,
) -> tuple[str, dict]:
    if body.credential_id is not None:
        cred = await session.get(ConnectorCredential, body.credential_id)
        if cred is None or cred.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Credential not found")
        return cred.connector_type, decrypt_config(cred)
    if body.connector_type and body.config is not None:
        return body.connector_type, body.config
    raise HTTPException(
        status_code=400,
        detail="Provide either credential_id or connector_type + config.",
    )


# --- Discovery -----------------------------------------------------------


@router.post("/test")
async def test_connection(
    body: TestCredentialRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    connector_type, config = await _resolve_config(body, session, context.tenant_id)
    connector = get_connector(connector_type)
    try:
        info = await connector.test_connection(config)
    except SaasConnectorError as exc:
        return {"success": False, "message": str(exc)}
    if body.credential_id is not None:
        cred = await session.get(ConnectorCredential, body.credential_id)
        if cred is not None and cred.tenant_id == context.tenant_id:
            cred.last_tested_at = datetime.now(UTC)
            await session.commit()
    return {"success": True, "message": "Connection successful", "info": info}


@router.post("/objects")
async def list_objects(
    body: ObjectsRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    cred = await session.get(ConnectorCredential, body.credential_id)
    if cred is None or cred.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Credential not found")
    connector = get_connector(cred.connector_type)
    try:
        objects = await connector.list_objects(decrypt_config(cred))
    except SaasConnectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"objects": [{"name": o.name, "label": o.label} for o in objects]}


@router.post("/fields")
async def list_fields(
    body: FieldsRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    cred = await session.get(ConnectorCredential, body.credential_id)
    if cred is None or cred.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Credential not found")
    connector = get_connector(cred.connector_type)
    try:
        fields = await connector.list_fields(decrypt_config(cred), body.object_type)
    except SaasConnectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "fields": [
            {
                "name": f.name,
                "label": f.label,
                "saas_type": f.saas_type,
                "pg_type": f.pg_type,
            }
            for f in fields
        ]
    }


@router.post("/preview")
async def preview(
    body: PreviewRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    cred = await session.get(ConnectorCredential, body.credential_id)
    if cred is None or cred.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Credential not found")
    connector = get_connector(cred.connector_type)
    try:
        result = await connector.preview(
            decrypt_config(cred),
            body.object_type,
            body.selected_fields,
            limit=body.limit,
        )
    except SaasConnectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"columns": result.columns, "rows": result.rows}


# --- Sources -------------------------------------------------------------


@router.post("")
async def create_source(
    body: CreateSaasSourceRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    if not body.selected_fields:
        raise HTTPException(
            status_code=400, detail="Select at least one field to sync."
        )
    try:
        saas = await create_saas_source(
            session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            project_id=body.project_id,
            connector_type=body.connector_type,
            credential_id=body.credential_id,
            object_type=body.object_type,
            selected_fields=body.selected_fields,
            display_name=body.display_name,
        )
    except SaasSourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SaasConnectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Kick off the initial sync in the background (best-effort enqueue).
    enqueued = False
    try:
        from app.tasks.workflows import enqueue_sync_saas_object

        await enqueue_sync_saas_object(saas_source_id=saas.id, limit=None)
        enqueued = True
    except Exception as exc:  # pragma: no cover - redis not reachable
        logger.warning("Could not enqueue initial SaaS sync: %s", exc)

    result = saas.to_dict()
    result["sync_enqueued"] = enqueued
    return result


@router.get("")
async def list_saas_sources(
    project_id: int | None = None,
    include_archived: bool = False,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[dict]:
    stmt = select(SaasObjectDataSource).where(
        SaasObjectDataSource.tenant_id == context.tenant_id
    )
    rows = (await session.scalars(stmt)).all()
    out: list[dict] = []
    for r in rows:
        d = r.to_dict()
        ds = await session.get(DatabaseDataSource, r.database_data_source_id)
        if ds is not None:
            if not include_archived and ds.archived:
                continue
            if project_id is not None and ds.project_id != project_id:
                continue
            d["id"] = ds.id
            d["archived"] = ds.archived
            d["display_name"] = ds.display_name
            d["teiid_view_name"] = ds.teiid_view_name
            d["status"] = ds.status
            d["project_id"] = ds.project_id
        out.append(d)
    return out


@router.post("/{saas_source_id}/sync")
async def sync_source(
    saas_source_id: int,
    body: SyncRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    saas = await session.get(SaasObjectDataSource, saas_source_id)
    if saas is None or saas.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="SaaS data source not found")

    if body.wait:
        try:
            return await run_sync(
                session, saas_source_id=saas_source_id, limit=body.limit
            )
        except SaasSourceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except SaasConnectorError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    enqueued = False
    try:
        from app.tasks.workflows import enqueue_sync_saas_object

        await enqueue_sync_saas_object(
            saas_source_id=saas_source_id, limit=body.limit
        )
        enqueued = True
    except Exception as exc:  # pragma: no cover - redis not reachable
        logger.warning("Could not enqueue SaaS sync: %s", exc)
    return {"status": "enqueued" if enqueued else "failed", "id": saas_source_id}
