"""File import routes for the Data Source Builder.

Three acquisition methods (local upload, HTTPS URL, approved UNC/SMB path)
produce the same durable import job, which the builder then finalizes through
``/data-sources/upload/finalize``. Administration of the approved network
locations lives here too, behind an admin role.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.database import get_db
from app.models.network_file_connection import NetworkFileConnection
from app.models.network_file_host import NetworkFileHost
from app.services import file_ingestion
from app.services.crypto import encrypt_secret
from app.services.file_ingestion import FileImportError
from app.services.smb_gateway import (
    NetworkPathError,
    check_network_access,
    get_approved_smb_hosts,
    list_network_path,
)
from app.services.tenant_network_source_ip import get_tenant_source_ip

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/data-sources/imports", tags=["file-imports"])

_STATUS_BY_CODE = {
    "FILE_TOO_LARGE": 413,
    "SCANNER_UNAVAILABLE": 503,
    "URL_IMPORT_DISABLED": 403,
    "NETWORK_IMPORT_DISABLED": 403,
    "CONNECTION_NOT_FOUND": 404,
    "FILE_NOT_FOUND": 404,
    "STAGED_FILE_MISSING": 410,
    "HOST_UNREACHABLE": 502,
    "TIMEOUT": 504,
    "ACCESS_DENIED": 403,
    "AUTH_FAILED": 403,
}


def _http_error(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=_STATUS_BY_CODE.get(code, 422), detail=message)


async def _profile_and_commit(
    session: AsyncSession,
    job: Any,
    staged: Any,
    *,
    context: RequestContext,
    project_id: int | None,
    source_name: str | None,
) -> dict[str, Any]:
    payload = await file_ingestion.profile_staged_file(
        session,
        job,
        staged,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        project_id=project_id,
        source_name=source_name,
    )
    await session.commit()
    return payload


# ── Capabilities ─────────────────────────────────────────────────────────


@router.get("/capabilities")
async def get_capabilities(
    context: RequestContext = Depends(require_role(Role.EDITOR)),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Tell the builder which acquisition methods are usable right now."""
    settings = get_settings()
    connections = (
        await session.scalars(
            select(NetworkFileConnection).where(
                NetworkFileConnection.tenant_id == context.tenant_id,
                NetworkFileConnection.archived.is_(False),
                NetworkFileConnection.enabled.is_(True),
            )
        )
    ).all()
    hosts = (
        await session.scalars(
            select(NetworkFileHost).where(
                NetworkFileHost.tenant_id == context.tenant_id,
                NetworkFileHost.archived.is_(False),
            ).order_by(NetworkFileHost.name)
        )
    ).all()
    return {
        "local_upload_enabled": True,
        "url_import_enabled": settings.file_import_url_enabled,
        "network_import_enabled": settings.file_import_network_enabled,
        "max_file_size_bytes": settings.file_import_max_bytes,
        "malware_scanning_enabled": settings.file_import_malware_scan_enabled,
        "network_connections": [
            {"id": c.id, "name": c.name, "label": c.label} for c in connections
        ],
        "network_hosts": [h.to_dict() for h in hosts],
    }


# ── Acquisition ──────────────────────────────────────────────────────────


@router.post("/local")
async def import_local(
    file: UploadFile = File(...),
    project_id: int | None = Form(None),
    source_name: str | None = Form(None),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Stage and profile a locally uploaded file."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")
    content = await file.read()
    try:
        job, staged = await file_ingestion.acquire_local_upload(
            session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            project_id=project_id,
            filename=file.filename,
            data=content,
            content_type=file.content_type,
        )
        return await _profile_and_commit(
            session,
            job,
            staged,
            context=context,
            project_id=project_id,
            source_name=source_name,
        )
    except FileImportError as exc:
        await session.rollback()
        raise _http_error(exc.code, exc.message) from exc


class UrlImportRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    project_id: int | None = None
    source_name: str | None = None


@router.post("/url")
async def import_from_url(
    req: UrlImportRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Fetch an approved HTTPS URL server-side, then stage and profile it."""
    try:
        job, staged = await file_ingestion.acquire_url(
            session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            project_id=req.project_id,
            url=req.url,
        )
        return await _profile_and_commit(
            session,
            job,
            staged,
            context=context,
            project_id=req.project_id,
            source_name=req.source_name,
        )
    except FileImportError as exc:
        await session.rollback()
        raise _http_error(exc.code, exc.message) from exc


class NetworkImportRequest(BaseModel):
    connection_id: int
    path: str = Field(min_length=3, max_length=2048)
    project_id: int | None = None
    source_name: str | None = None


class NetworkTestRequest(BaseModel):
    connection_id: int
    path: str | None = None


async def _load_connection(
    session: AsyncSession, connection_id: int, tenant_id: int
) -> NetworkFileConnection:
    connection = await session.get(NetworkFileConnection, connection_id)
    if connection is None or connection.tenant_id != tenant_id or connection.archived:
        raise HTTPException(status_code=404, detail="Network location not found")
    return connection


@router.post("/network/test")
async def test_network_path(
    req: NetworkTestRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Check that an approved network location (or one path) is reachable."""
    if not get_settings().file_import_network_enabled:
        raise HTTPException(status_code=403, detail="Network import is disabled.")
    connection = await _load_connection(
        session, req.connection_id, context.tenant_id
    )
    source_ip = await get_tenant_source_ip(session, context.tenant_id)
    approved_hosts = await get_approved_smb_hosts(session, context.tenant_id)
    try:
        return await check_network_access(
            connection, req.path, source_ip=source_ip, approved_hosts=approved_hosts
        )
    except NetworkPathError as exc:
        raise _http_error(exc.code, exc.message) from exc


@router.post("/network")
async def import_from_network(
    req: NetworkImportRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Read a file from an approved network location, stage it, and profile it."""
    connection = await _load_connection(
        session, req.connection_id, context.tenant_id
    )
    try:
        job, staged = await file_ingestion.acquire_network_path(
            session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            project_id=req.project_id,
            connection=connection,
            path=req.path,
        )
        return await _profile_and_commit(
            session,
            job,
            staged,
            context=context,
            project_id=req.project_id,
            source_name=req.source_name,
        )
    except FileImportError as exc:
        await session.rollback()
        raise _http_error(exc.code, exc.message) from exc


# ── Job lifecycle ────────────────────────────────────────────────────────


@router.get("/{import_job_id}")
async def get_import_job(
    import_job_id: str,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Return safe job state so the builder can restore after a refresh."""
    job = await file_ingestion.get_job_for_user(
        session, import_job_id, tenant_id=context.tenant_id, user_id=context.user_id
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Import not found")
    payload = job.to_dict()
    profile = job.profile_json or {}
    if job.status == "ready" and profile.get("file_profile"):
        payload["preview"] = file_ingestion.build_preview_payload(
            job,
            profile["file_profile"],
            profile.get("ai_result") or {},
            profile.get("catalog_result") or {},
        )
    return payload


@router.delete("/{import_job_id}")
async def cancel_import_job(
    import_job_id: str,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Cancel an import and delete its quarantined bytes."""
    job = await file_ingestion.get_job_for_user(
        session, import_job_id, tenant_id=context.tenant_id, user_id=context.user_id
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Import not found")
    if job.status == "completed":
        raise HTTPException(
            status_code=409, detail="That import has already been finalized."
        )
    file_ingestion.discard_quarantine(job)
    job.status = "cancelled"
    await session.commit()
    return {"import_job_id": job.id, "status": job.status}


# ── Network connection administration ────────────────────────────────────

connections_router = APIRouter(
    prefix="/network-file-connections", tags=["file-imports"]
)


class ConnectionUpsertRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    host: str = Field(min_length=1, max_length=255)
    share_name: str = Field(min_length=1, max_length=255)
    approved_root_path: str = Field(default="", max_length=1024)
    port: int = 445
    domain: str | None = None
    username: str | None = None
    #: Write-only. Omit on update to keep the stored credential.
    password: str | None = None
    require_signing: bool = True
    require_encryption: bool = True
    enabled: bool = True


@connections_router.get("")
async def list_connections(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(NetworkFileConnection)
            .where(
                NetworkFileConnection.tenant_id == context.tenant_id,
                NetworkFileConnection.archived.is_(False),
            )
            .order_by(NetworkFileConnection.name)
        )
    ).all()
    return [c.to_dict() for c in rows]


@connections_router.post("")
async def create_connection(
    req: ConnectionUpsertRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> dict[str, Any]:
    connection = NetworkFileConnection(
        tenant_id=context.tenant_id,
        created_by=context.user_id,
        name=req.name,
        host=req.host.strip().lower(),
        port=req.port,
        share_name=req.share_name.strip(),
        approved_root_path=req.approved_root_path.strip(),
        domain=req.domain,
        username=req.username,
        secret_encrypted=encrypt_secret(req.password) if req.password else None,
        require_signing=req.require_signing,
        require_encryption=req.require_encryption,
        enabled=req.enabled,
    )
    session.add(connection)
    await session.commit()
    return connection.to_dict()


@connections_router.patch("/{connection_id}")
async def update_connection(
    connection_id: int,
    req: ConnectionUpsertRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> dict[str, Any]:
    connection = await _load_connection(session, connection_id, context.tenant_id)
    connection.name = req.name
    connection.host = req.host.strip().lower()
    connection.port = req.port
    connection.share_name = req.share_name.strip()
    connection.approved_root_path = req.approved_root_path.strip()
    connection.domain = req.domain
    connection.username = req.username
    if req.password:
        connection.secret_encrypted = encrypt_secret(req.password)
    connection.require_signing = req.require_signing
    connection.require_encryption = req.require_encryption
    connection.enabled = req.enabled
    await session.commit()
    return connection.to_dict()


@connections_router.post("/{connection_id}/test")
async def test_connection(
    connection_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> dict[str, Any]:
    from datetime import UTC, datetime

    connection = await _load_connection(session, connection_id, context.tenant_id)
    approved_hosts = await get_approved_smb_hosts(session, context.tenant_id)
    try:
        result = await check_network_access(connection, approved_hosts=approved_hosts)
    except NetworkPathError as exc:
        connection.last_test_status = "failed"
        connection.last_test_message_safe = exc.message
        connection.last_tested_at = datetime.now(UTC)
        await session.commit()
        raise _http_error(exc.code, exc.message) from exc
    connection.last_test_status = "ok"
    connection.last_test_message_safe = None
    connection.last_tested_at = datetime.now(UTC)
    await session.commit()
    return result


@connections_router.get("/{connection_id}/browse")
async def browse_connection(
    connection_id: int,
    path: str | None = None,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """List files and folders in an approved network location.

    ``path`` is the share-relative directory to open; when omitted the share
    root (or ``approved_root_path`` if configured) is listed.
    """
    if not get_settings().file_import_network_enabled:
        raise HTTPException(status_code=403, detail="Network import is disabled.")
    connection = await _load_connection(
        session, connection_id, context.tenant_id
    )
    source_ip = await get_tenant_source_ip(session, context.tenant_id)
    approved_hosts = await get_approved_smb_hosts(session, context.tenant_id)
    if path:
        browse_path = path
    else:
        root = connection.approved_root_path.strip().strip("\\/")
        browse_path = (
            f"\\\\{connection.host}\\{connection.share_name}"
            if not root
            else f"\\\\{connection.host}\\{connection.share_name}\\{root}"
        )
    try:
        entries = await list_network_path(
            connection,
            browse_path,
            source_ip=source_ip,
            approved_hosts=approved_hosts,
        )
    except NetworkPathError as exc:
        raise _http_error(exc.code, exc.message) from exc
    return {"entries": entries, "path": browse_path}


@connections_router.delete("/{connection_id}")
async def delete_connection(
    connection_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> dict[str, str]:
    connection = await _load_connection(session, connection_id, context.tenant_id)
    connection.archived = True
    connection.enabled = False
    await session.commit()
    return {"status": "archived"}


# ── Approved SMB host administration ─────────────────────────────────────

hosts_router = APIRouter(prefix="/network-file-hosts", tags=["file-imports"])


class HostUpsertRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    host: str = Field(min_length=1, max_length=255)
    enabled: bool = True


@hosts_router.get("")
async def list_hosts(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(NetworkFileHost)
            .where(
                NetworkFileHost.tenant_id == context.tenant_id,
                NetworkFileHost.archived.is_(False),
            )
            .order_by(NetworkFileHost.name)
        )
    ).all()
    return [h.to_dict() for h in rows]


@hosts_router.post("")
async def create_host(
    req: HostUpsertRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> dict[str, Any]:
    host = NetworkFileHost(
        tenant_id=context.tenant_id,
        created_by=context.user_id,
        name=req.name,
        host=req.host.strip().lower(),
        enabled=req.enabled,
    )
    session.add(host)
    await session.commit()
    return host.to_dict()


@hosts_router.patch("/{host_id}")
async def update_host(
    host_id: int,
    req: HostUpsertRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> dict[str, Any]:
    row = await session.get(NetworkFileHost, host_id)
    if row is None or row.tenant_id != context.tenant_id or row.archived:
        raise HTTPException(status_code=404, detail="Host not found")
    row.name = req.name
    row.host = req.host.strip().lower()
    row.enabled = req.enabled
    await session.commit()
    return row.to_dict()


@hosts_router.delete("/{host_id}")
async def delete_host(
    host_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> dict[str, str]:
    row = await session.get(NetworkFileHost, host_id)
    if row is None or row.tenant_id != context.tenant_id or row.archived:
        raise HTTPException(status_code=404, detail="Host not found")
    row.archived = True
    row.enabled = False
    await session.commit()
    return {"status": "archived"}
