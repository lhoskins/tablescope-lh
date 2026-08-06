
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.file_import_job import FileImportJob
from app.models.network_file_connection import NetworkFileConnection
from app.services.safe_remote_fetch import RemoteFetchError
from app.services.smb_gateway import NetworkPathError, resolve_network_path
from app.services.tenant_network_source_ip import get_tenant_source_ip

from .staging import FileImportError, SafeProvenance, StagedFile, _new_job, _stage


async def acquire_local_upload(
    session: AsyncSession,
    *,
    tenant_id: int,
    user_id: int,
    project_id: int | None,
    filename: str,
    data: bytes,
    content_type: str | None = None,
    allowed_families: tuple[str, ...] = ("tabular",),
) -> tuple[FileImportJob, StagedFile]:
    job = _new_job(
        tenant_id=tenant_id, user_id=user_id, project_id=project_id,
        method="local_upload",
    )
    session.add(job)
    await session.flush()
    staged = await _stage(
        session,
        job,
        data=data,
        original_filename=filename,
        # A browser's declared type is unreliable for CSV/Excel, and the magic
        # bytes are checked regardless, so it is not used as a gate here.
        declared_mime_type=None if content_type == "application/octet-stream"
        else content_type,
        provenance=SafeProvenance(),
        allowed_families=allowed_families,
    )
    return job, staged


async def acquire_url(
    session: AsyncSession,
    *,
    tenant_id: int,
    user_id: int,
    project_id: int | None,
    url: str,
    allowed_families: tuple[str, ...] = ("tabular",),
) -> tuple[FileImportJob, StagedFile]:
    settings = get_settings()
    if not settings.file_import_url_enabled:
        raise FileImportError(
            "URL_IMPORT_DISABLED",
            "URL import is disabled. Ask an administrator to enable it.",
        )
    job = _new_job(
        tenant_id=tenant_id, user_id=user_id, project_id=project_id, method="url"
    )
    session.add(job)
    await session.flush()
    job.status = "fetching"
    import app.services.file_ingestion as _fi

    try:
        data, metadata = await _fi.fetch_remote_file(url)
    except RemoteFetchError as exc:
        raise FileImportError(exc.code, exc.message) from exc

    filename = metadata.filename or "download"
    provenance = SafeProvenance(
        source_host=metadata.url_host,
        locator_redacted=metadata.locator_redacted,
        remote_etag=metadata.etag,
        remote_last_modified=metadata.last_modified,
    )
    staged = await _stage(
        session,
        job,
        data=data,
        original_filename=filename,
        declared_mime_type=metadata.content_type,
        provenance=provenance,
        allowed_families=allowed_families,
    )
    return job, staged


async def acquire_network_path(
    session: AsyncSession,
    *,
    tenant_id: int,
    user_id: int,
    project_id: int | None,
    connection: NetworkFileConnection,
    path: str,
    allowed_families: tuple[str, ...] = ("tabular",),
) -> tuple[FileImportJob, StagedFile]:
    settings = get_settings()
    if not settings.file_import_network_enabled:
        raise FileImportError(
            "NETWORK_IMPORT_DISABLED",
            "Network import is disabled. Ask an administrator to enable it.",
        )
    if connection.tenant_id != tenant_id:
        raise FileImportError("CONNECTION_NOT_FOUND", "That network location was not found.")

    job = _new_job(
        tenant_id=tenant_id, user_id=user_id, project_id=project_id,
        method="network_path",
    )
    session.add(job)
    await session.flush()
    try:
        resolved = resolve_network_path(path, connection)
        job.status = "fetching"
        source_ip = await get_tenant_source_ip(session, tenant_id)
        import app.services.file_ingestion as _fi

        data = await _fi.read_network_file(
            resolved, connection, source_ip=source_ip
        )
    except NetworkPathError as exc:
        raise FileImportError(exc.code, exc.message) from exc

    provenance = SafeProvenance(
        source_host=resolved.host,
        locator_redacted=resolved.redacted_locator,
        network_connection_id=connection.id,
    )
    staged = await _stage(
        session,
        job,
        data=data,
        original_filename=resolved.filename,
        declared_mime_type=None,
        provenance=provenance,
        allowed_families=allowed_families,
    )
    return job, staged
