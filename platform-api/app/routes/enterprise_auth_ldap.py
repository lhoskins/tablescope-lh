"""LDAP connection, directory preview/sync, and group mapping routes."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.directory_group_role_mapping import DirectoryGroupRoleMapping
from app.models.ldap_connection import LdapConnection
from app.models.tenant import Tenant
from app.schemas.enterprise_auth import (
    DirectoryGroupRoleMappingCreate,
    DirectoryGroupRoleMappingRead,
    DirectoryGroupRoleMappingUpdate,
    LdapConnectionCreate,
    LdapConnectionRead,
    LdapConnectionTestResponse,
    LdapPreviewResponse,
    LdapSyncResponse,
)
from app.services.enterprise_auth import (
    audit_enterprise_auth_event,
    encrypt_ldap_bind_secret,
    get_enterprise_auth_settings,
    update_enterprise_auth_settings,
)
from app.services.ldap_client import preview_ldap_directory, test_ldap_connection

router = APIRouter(prefix="/tenants/current/enterprise-auth/ldap", tags=["enterprise-auth"])


def _dict(connection: LdapConnection) -> LdapConnectionRead:
    data = connection.to_safe_dict()
    data["has_ca_certificate"] = bool(connection.ca_certificate)
    return LdapConnectionRead.model_validate(data)


@router.get("/connection", response_model=LdapConnectionRead | None)
async def get_ldap_connection(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> LdapConnectionRead | None:
    settings = await get_enterprise_auth_settings(session, context.tenant_id)
    if settings.ldap_connection_id is None:
        return None
    conn = await session.get(LdapConnection, settings.ldap_connection_id)
    if conn is None or conn.archived:
        return None
    return _dict(conn)


@router.put("/connection", response_model=LdapConnectionRead)
async def create_or_update_ldap_connection(
    payload: LdapConnectionCreate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> LdapConnectionRead:
    settings = await get_enterprise_auth_settings(session, context.tenant_id)
    tenant = await session.get(Tenant, context.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if context.aal != "aal2" and not tenant.enforce_2fa:
        # Require step-up for creating/updating an LDAP bind credential.
        raise HTTPException(
            status_code=409,
            detail="Verify your own phone (step-up authentication) before saving an LDAP connection.",
        )

    updates = payload.model_dump(exclude_unset=True)
    bind_secret = updates.pop("bind_secret", None)

    if settings.ldap_connection_id:
        conn = await session.get(LdapConnection, settings.ldap_connection_id)
    else:
        conn = None

    if conn is None:
        conn = LdapConnection(tenant_id=context.tenant_id, created_by=context.user_id)
        session.add(conn)
    else:
        if conn.tenant_id != context.tenant_id:
            raise HTTPException(status_code=403, detail="Not allowed")

    for key, value in updates.items():
        setattr(conn, key, value)

    if bind_secret is not None:
        conn.bind_secret_encrypted = encrypt_ldap_bind_secret(bind_secret)

    await session.flush()
    settings.ldap_connection_id = conn.id
    await update_enterprise_auth_settings(session, context.tenant_id, {"updated_by": context.user_id})
    await audit_enterprise_auth_event(
        session,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        scope="ldap_connection",
        title=f"LDAP connection {conn.name!r} saved",
    )
    await session.commit()
    return _dict(conn)


@router.post("/connection/test", response_model=LdapConnectionTestResponse)
async def test_ldap_connection_endpoint(
    payload: LdapConnectionCreate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> LdapConnectionTestResponse:
    # Build a transient connection object from payload; do not commit.
    conn = LdapConnection(**payload.model_dump(exclude_unset=True), tenant_id=context.tenant_id)
    conn.bind_secret_encrypted = encrypt_ldap_bind_secret(payload.bind_secret) if payload.bind_secret else None
    result = await test_ldap_connection(conn)
    return LdapConnectionTestResponse(**result)


@router.post("/connection/preview", response_model=LdapPreviewResponse)
async def preview_ldap_connection(
    payload: LdapConnectionCreate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> LdapPreviewResponse:
    conn = LdapConnection(**payload.model_dump(exclude_unset=True), tenant_id=context.tenant_id)
    conn.bind_secret_encrypted = encrypt_ldap_bind_secret(payload.bind_secret) if payload.bind_secret else None
    try:
        preview = await preview_ldap_directory(conn)
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return LdapPreviewResponse(**preview)


@router.post("/connection/{connection_id}/test", response_model=LdapConnectionTestResponse)
async def test_saved_ldap_connection(
    connection_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> LdapConnectionTestResponse:
    conn = await session.get(LdapConnection, connection_id)
    if conn is None or conn.tenant_id != context.tenant_id or conn.archived:
        raise HTTPException(status_code=404, detail="LDAP connection not found")
    result = await test_ldap_connection(conn)
    conn.last_test_status = result["status"]
    conn.last_test_message_safe = result["message"]
    conn.last_tested_at = datetime.now(tz=UTC)
    await session.commit()
    return LdapConnectionTestResponse(**result)


@router.post("/sync", response_model=LdapSyncResponse)
async def trigger_ldap_sync(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> LdapSyncResponse:
    settings = await get_enterprise_auth_settings(session, context.tenant_id)
    if settings.ldap_connection_id is None:
        raise HTTPException(status_code=404, detail="No LDAP connection configured")
    # TODO: enqueue durable worker job. For Phase 1/2 the endpoint returns the
    # connection id as the job key and writes no directory rows.
    return LdapSyncResponse(
        sync_run_id=None,
        status="queued",
        message="LDAP sync is queued (full worker implementation pending).",
    )


# ---------------------------------------------------------------------------
# Directory group role mappings
# ---------------------------------------------------------------------------


@router.get("/group-mappings", response_model=list[DirectoryGroupRoleMappingRead])
async def list_group_mappings(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> list[DirectoryGroupRoleMappingRead]:
    rows = await session.scalars(
        select(DirectoryGroupRoleMapping).where(
            DirectoryGroupRoleMapping.tenant_id == context.tenant_id,
        )
    )
    return [DirectoryGroupRoleMappingRead.model_validate(r) for r in rows]


@router.post("/group-mappings", response_model=DirectoryGroupRoleMappingRead)
async def create_group_mapping(
    payload: DirectoryGroupRoleMappingCreate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> DirectoryGroupRoleMappingRead:
    settings = await get_enterprise_auth_settings(session, context.tenant_id)
    if settings.ldap_connection_id is None:
        raise HTTPException(status_code=400, detail="Configure an LDAP connection first")
    mapping = DirectoryGroupRoleMapping(
        tenant_id=context.tenant_id,
        connection_id=settings.ldap_connection_id,
        directory_group_guid=payload.directory_group_guid,
        group_display_name=payload.group_display_name,
        target_type=payload.target_type,
        target_project_id=payload.target_project_id,
        mapped_role=payload.mapped_role,
        enabled=payload.enabled,
        created_by=context.user_id,
        updated_by=context.user_id,
    )
    session.add(mapping)
    await session.flush()
    await audit_enterprise_auth_event(
        session,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        scope="ldap_group_mapping",
        title=f"LDAP group {payload.directory_group_guid} mapped to {payload.mapped_role}",
    )
    await session.commit()
    return DirectoryGroupRoleMappingRead.model_validate(mapping)


@router.put("/group-mappings/{mapping_id}", response_model=DirectoryGroupRoleMappingRead)
async def update_group_mapping(
    mapping_id: int,
    payload: DirectoryGroupRoleMappingUpdate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> DirectoryGroupRoleMappingRead:
    mapping = await session.get(DirectoryGroupRoleMapping, mapping_id)
    if mapping is None or mapping.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Mapping not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(mapping, key, value)
    mapping.updated_by = context.user_id
    await session.commit()
    return DirectoryGroupRoleMappingRead.model_validate(mapping)


@router.delete("/group-mappings/{mapping_id}")
async def delete_group_mapping(
    mapping_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> dict[str, str]:
    mapping = await session.get(DirectoryGroupRoleMapping, mapping_id)
    if mapping is None or mapping.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Mapping not found")
    await session.delete(mapping)
    await audit_enterprise_auth_event(
        session,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        scope="ldap_group_mapping",
        title=f"LDAP group mapping {mapping_id} deleted",
    )
    await session.commit()
    return {"status": "deleted"}
