"""Canonical file-ingestion service shared by all three acquisition methods.

Local upload, HTTPS URL, and UNC/SMB network path differ only in how bytes
arrive. They converge here on one :class:`StagedFile` contract and then follow
the pre-existing destination pipelines unchanged: tabular files profile into
Teiid + ``FileSourceMeta`` + a saved query, documents go to Project Assets.

The staged bytes live in tenant-scoped quarantine on disk and the job state
lives in Postgres, so an import survives an API restart and is not bound to
one Python process the way the old in-memory upload-session dict was.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.file_import_job import FileImportJob
from app.models.file_source_meta import FileSourceMeta
from app.models.network_file_connection import NetworkFileConnection
from app.services import malware_scan
from app.services.ai_file_analysis_service import analyze_file_with_ai
from app.services.file_profile_service import profile_uploaded_file
from app.services.file_sources import sanitize_filename
from app.services.file_validation import (
    FileValidationError,
    validate_content,
)
from app.services.safe_remote_fetch import (
    RemoteFetchError,
    fetch_remote_file,
)
from app.services.smb_gateway import (
    NetworkPathError,
    read_network_file,
    resolve_network_path,
)
from app.services.upload_ai_profiler_service import (
    profile_uploaded_file as catalog_profile_file,
)

logger = logging.getLogger(__name__)


class FileImportError(Exception):
    """An import failed. ``code`` is a safe category, ``message`` is safe text."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(slots=True)
class SafeProvenance:
    source_host: str | None = None
    locator_redacted: str | None = None
    network_connection_id: int | None = None
    remote_etag: str | None = None
    remote_last_modified: str | None = None


@dataclass(slots=True)
class StagedFile:
    """The single contract every acquisition method produces."""

    import_job_id: str
    content_path: Path
    original_filename: str
    sanitized_filename: str
    detected_extension: str
    detected_mime_type: str
    content_family: str
    size_bytes: int
    sha256: str
    acquisition_method: str
    safe_provenance: SafeProvenance


# ── Quarantine ───────────────────────────────────────────────────────────


def quarantine_dir(tenant_id: int, user_id: int, job_id: str) -> Path:
    base = Path(get_settings().file_import_quarantine_path)
    return base / str(tenant_id) / str(user_id) / job_id


def _write_quarantine(
    tenant_id: int, user_id: int, job_id: str, filename: str, data: bytes
) -> Path:
    directory = quarantine_dir(tenant_id, user_id, job_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_bytes(data)
    path.chmod(0o600)
    return path


def discard_quarantine(job: FileImportJob) -> None:
    """Remove a job's staged bytes. Safe to call more than once."""
    if not job.storage_key:
        return
    directory = Path(job.storage_key).parent
    shutil.rmtree(directory, ignore_errors=True)
    job.storage_key = None


def read_staged_bytes(job: FileImportJob) -> bytes:
    if not job.storage_key:
        raise FileImportError("STAGED_FILE_MISSING", "The staged file is no longer available.")
    path = Path(job.storage_key)
    if not path.is_file():
        raise FileImportError("STAGED_FILE_MISSING", "The staged file is no longer available.")
    return path.read_bytes()


# ── Acquisition ──────────────────────────────────────────────────────────


def _new_job(
    *,
    tenant_id: int,
    user_id: int,
    project_id: int | None,
    method: str,
) -> FileImportJob:
    settings = get_settings()
    return FileImportJob(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        requested_by=user_id,
        project_id=project_id,
        method=method,
        status="validating",
        expires_at=datetime.now(UTC)
        + timedelta(seconds=settings.file_import_job_ttl_seconds),
    )


async def _stage(
    session: AsyncSession,
    job: FileImportJob,
    *,
    data: bytes,
    original_filename: str,
    declared_mime_type: str | None,
    provenance: SafeProvenance,
    allowed_families: tuple[str, ...],
) -> StagedFile:
    """Validate, scan, fingerprint, and quarantine acquired bytes."""
    settings = get_settings()
    if len(data) > settings.file_import_max_bytes:
        raise FileImportError(
            "FILE_TOO_LARGE",
            f"That file exceeds the {settings.file_import_max_bytes // (1024 * 1024)}"
            "MB limit.",
        )

    sanitized = sanitize_filename(original_filename)
    try:
        validated = validate_content(
            data,
            sanitized,
            declared_mime_type=declared_mime_type,
            allowed_families=allowed_families,
        )
    except FileValidationError as exc:
        raise FileImportError(exc.code, exc.message) from exc

    job.status = "scanning"
    try:
        scan = await malware_scan.scan_bytes(data)
    except malware_scan.MalwareScanError as exc:
        raise FileImportError(exc.code, exc.message) from exc
    if scan.is_blocking:
        logger.warning(
            "malware scan blocked import job=%s tenant=%s signature=%s",
            job.id,
            job.tenant_id,
            scan.signature,
        )
        raise FileImportError(
            "SECURITY_BLOCKED", "That file was blocked by the security scanner."
        )

    digest = hashlib.sha256(data).hexdigest()
    path = _write_quarantine(
        job.tenant_id, job.requested_by, job.id, sanitized, data
    )

    job.original_file_name = original_filename[:512]
    job.sanitized_file_name = sanitized
    job.detected_extension = validated.extension
    job.detected_mime_type = validated.mime_type
    job.content_family = validated.content_family
    job.file_size_bytes = len(data)
    job.sha256 = digest
    job.storage_key = str(path)
    job.source_host = provenance.source_host
    job.source_locator_redacted = provenance.locator_redacted
    job.network_connection_id = provenance.network_connection_id
    job.remote_etag = provenance.remote_etag
    job.remote_last_modified = provenance.remote_last_modified
    job.retrieved_at = datetime.now(UTC)
    job.status = "profiling"
    await session.flush()

    logger.info(
        "file import staged job=%s tenant=%s method=%s family=%s locator=%s",
        job.id,
        job.tenant_id,
        job.method,
        job.content_family,
        job.source_locator_redacted or "local",
    )

    return StagedFile(
        import_job_id=job.id,
        content_path=path,
        original_filename=original_filename,
        sanitized_filename=sanitized,
        detected_extension=validated.extension,
        detected_mime_type=validated.mime_type,
        content_family=validated.content_family,
        size_bytes=len(data),
        sha256=digest,
        acquisition_method=job.method,
        safe_provenance=provenance,
    )


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
    try:
        data, metadata = await fetch_remote_file(url)
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
        data = await read_network_file(resolved, connection)
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


# ── Profiling ────────────────────────────────────────────────────────────


async def profile_staged_file(
    session: AsyncSession,
    job: FileImportJob,
    staged: StagedFile,
    *,
    tenant_id: int,
    user_id: int,
    project_id: int | None,
    source_name: str | None = None,
) -> dict[str, Any]:
    """Profile a staged tabular file and run the existing AI/catalog analysis.

    Returns the same preview payload the builder already consumes, with
    ``import_job_id`` added alongside the legacy ``upload_session_id``.
    """
    data = read_staged_bytes(job)
    file_name = staged.sanitized_filename
    try:
        file_profile = profile_uploaded_file(data, file_name, staged.detected_extension)
    except Exception as exc:
        raise FileImportError("PARSE_FAILED", f"Could not parse file: {exc}") from exc
    if file_profile["column_count"] == 0:
        raise FileImportError("NO_COLUMNS", "No columns detected in file")

    ai_result = await analyze_file_with_ai(
        file_profile,
        tenant_id=tenant_id,
        user_id=user_id,
        project_id=project_id or 0,
    )

    columns_for_catalog = [
        {"name": f["field_name"], "type": f.get("detected_type", "string")}
        for f in file_profile.get("fields", [])
    ]
    catalog_result = await catalog_profile_file(
        session=session,
        tenant_id=tenant_id,
        user_id=user_id,
        project_id=project_id or 0,
        source_id=0,
        view_name=file_name.rsplit(".", 1)[0] if "." in file_name else file_name,
        file_name=file_name,
        columns=columns_for_catalog,
        sample_rows=file_profile.get("sample_rows", []),
        persist=False,
    )

    job.profile_json = {
        "file_profile": file_profile,
        "ai_result": ai_result,
        "catalog_result": catalog_result,
        "source_name": source_name,
    }
    job.status = "ready"
    await session.flush()

    return build_preview_payload(job, file_profile, ai_result, catalog_result)


def build_preview_payload(
    job: FileImportJob,
    file_profile: dict[str, Any],
    ai_result: dict[str, Any],
    catalog_result: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the builder's preview response for a profiled import job."""
    return {
        "import_job_id": job.id,
        # Legacy alias kept until every caller migrates to import_job_id.
        "upload_session_id": job.id,
        "acquisition_method": job.method,
        "content_family": job.content_family,
        "source_host": job.source_host,
        "source_locator_redacted": job.source_locator_redacted,
        "sha256": job.sha256,
        "file": {
            "file_name": file_profile["file_name"],
            "file_type": file_profile["file_type"],
            "file_size_bytes": file_profile["file_size_bytes"],
            "row_count": file_profile["row_count"],
            "column_count": file_profile["column_count"],
            "sheet_name": file_profile.get("sheet_name"),
        },
        "summary": {
            "ai_summary": catalog_result.get("summary") or ai_result.get("summary", ""),
            "ai_usage_summary": ai_result.get("usage_summary", ""),
            "ai_quality_summary": ai_result.get("quality_summary", ""),
            "business_domain": catalog_result.get("business_domain", ""),
            "process_area": catalog_result.get("process_area", ""),
        },
        "fields": [
            {
                **pf,
                "ai_description": next(
                    (
                        af["description"]
                        for af in ai_result.get("fields", [])
                        if af["field_name"] == pf["field_name"]
                    ),
                    "",
                ),
                "ai_quality_notes": next(
                    (
                        af["quality_notes"]
                        for af in ai_result.get("fields", [])
                        if af["field_name"] == pf["field_name"]
                    ),
                    "",
                ),
            }
            for pf in file_profile["fields"]
        ],
        "tags": [
            {**t, "source": "catalog", "accepted": True}
            for t in catalog_result.get("suggested_tags", [])
        ]
        or [
            {**t, "source": "ai", "accepted": True}
            for t in ai_result.get("tags", [])
        ],
        "kpis": [
            {**k, "source": "catalog", "accepted": True}
            for k in catalog_result.get("suggested_kpis", [])
        ],
        "relationship_hints": catalog_result.get("relationship_hints", []),
        "data_quality_notes": catalog_result.get("data_quality_notes", []),
        "recommendations": [
            {**r, "client_id": f"rec_{i}", "status": "pending"}
            for i, r in enumerate(ai_result.get("recommendations", []))
        ],
        "status": "analysis_complete",
    }


# ── Job lookup and lifecycle ─────────────────────────────────────────────


async def get_job_for_user(
    session: AsyncSession, job_id: str, *, tenant_id: int, user_id: int
) -> FileImportJob | None:
    """Tenant- and requester-scoped lookup. Every route must use this."""
    return await session.scalar(
        select(FileImportJob).where(
            FileImportJob.id == job_id,
            FileImportJob.tenant_id == tenant_id,
            FileImportJob.requested_by == user_id,
        )
    )


def apply_provenance(meta: FileSourceMeta, job: FileImportJob) -> None:
    """Copy a job's safe provenance onto the finalized data-source record."""
    meta.acquisition_method = job.method
    meta.import_job_id = job.id
    meta.source_host = job.source_host
    meta.source_locator_redacted = job.source_locator_redacted
    meta.network_connection_id = job.network_connection_id
    meta.content_sha256 = job.sha256
    meta.remote_etag = job.remote_etag
    meta.remote_last_modified = job.remote_last_modified
    meta.retrieved_at = job.retrieved_at


@dataclass(slots=True)
class FinalizeOptions:
    project_id: int | None = None
    display_name: str | None = None
    accepted_tags: list[dict[str, Any]] | None = None
    accepted_tag_keys: list[str] | None = None
    rejected_tag_keys: list[str] | None = None
    accepted_kpi_keys: list[str] | None = None
    rejected_kpi_keys: list[str] | None = None
    recommendation_decisions: list[dict[str, Any]] | None = None
    user_notes: str | None = None
    user_nuances: str | None = None


async def finalize_tabular_import(
    session: AsyncSession,
    job: FileImportJob,
    options: FinalizeOptions,
    *,
    tenant_id: int,
    user_id: int,
) -> dict[str, Any]:
    """Register a staged tabular file as a data source.

    Sanitizes/converts the file, imports it into the tenant's Teiid VDB,
    persists ``FileSourceMeta`` with acquisition provenance, applies the AI /
    catalog metadata, and creates the auto saved query — the same sequence
    local uploads have always followed. Re-finalizing a completed job returns
    the stored result instead of creating a second view.
    """
    import httpx

    from app.models.project import Project
    from app.models.tenant import Tenant
    from app.models.user import User
    from app.services.file_sources import (
        compute_view_name,
        detect_column_types,
        display_source,
        prepare_upload_content,
    )
    from app.services.tenant_teiid_resolver import TenantTeiidResolver

    if job.status == "completed" and job.result_json:
        return job.result_json
    if job.status in ("cancelled", "expired"):
        raise FileImportError(
            "JOB_NOT_AVAILABLE", "That import was cancelled and cannot be finalized."
        )
    if job.content_family != "tabular":
        raise FileImportError(
            "WRONG_CONTENT_FAMILY",
            "That file is a document; assign it to a project instead.",
        )

    profile = job.profile_json or {}
    file_profile = profile.get("file_profile")
    ai_result = dict(profile.get("ai_result") or {})
    catalog_result = profile.get("catalog_result") or {}
    if not file_profile:
        raise FileImportError("NOT_PROFILED", "That import has not been profiled yet.")

    job.status = "finalizing"
    content = read_staged_bytes(job)
    file_name = job.sanitized_file_name or "upload.csv"
    project_id = options.project_id or job.project_id

    user = await session.get(User, user_id)
    if user is None:
        raise FileImportError("USER_NOT_FOUND", "User not found")
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise FileImportError("TENANT_NOT_FOUND", "Tenant not found")

    original_format = job.detected_extension
    final_filename, content, _ = prepare_upload_content(file_name, content)
    display_name, _ = display_source(final_filename, original_format)

    endpoint = await TenantTeiidResolver(session).resolve_for_org(tenant_id)
    servlet_url = f"{endpoint.servlet_url}/TeiidExcelImporterTest/upload"
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=10.0)
        ) as client:
            resp = await client.post(
                servlet_url,
                data={
                    "org_id": str(tenant.id),
                    "user_id": str(user.id),
                    "vdb_type": "user",
                    "replace": "true",
                },
                files={
                    "file": (final_filename, content, "application/octet-stream")
                },
            )
    except httpx.RequestError as exc:
        raise FileImportError("TEIID_UNREACHABLE", f"Teiid unreachable: {exc}") from exc

    if resp.status_code >= 400:
        raise FileImportError(
            "TEIID_IMPORT_FAILED", f"Teiid import failed: {resp.text}"
        )
    teiid_result = (
        resp.json()
        if resp.headers.get("content-type", "").startswith("application/json")
        else {"raw": resp.text}
    )
    if "error" in teiid_result:
        raise FileImportError("TEIID_IMPORT_FAILED", str(teiid_result["error"]))

    column_types = detect_column_types(content, final_filename)
    view_name = compute_view_name(final_filename)

    resolved_project_id: int | None = None
    if project_id is not None:
        project = await session.get(Project, project_id)
        if project and project.tenant_id == tenant_id:
            resolved_project_id = project_id

    existing_meta = await session.scalar(
        select(FileSourceMeta).where(
            FileSourceMeta.tenant_id == tenant_id,
            FileSourceMeta.owner_id == user.id,
            FileSourceMeta.view_name == view_name,
        )
    )
    if existing_meta is None:
        meta = FileSourceMeta(
            tenant_id=tenant_id,
            owner_id=user.id,
            project_id=resolved_project_id,
            view_name=view_name,
            file_name=display_name,
            vdb_type="user",
            source_format=original_format,
            column_types=column_types or None,
        )
        session.add(meta)
    else:
        meta = existing_meta
        meta.file_name = display_name
        meta.source_format = original_format
        if column_types:
            meta.column_types = column_types
        if resolved_project_id is not None:
            meta.project_id = resolved_project_id
        meta.archived = False
        meta.archived_at = None
    apply_provenance(meta, job)
    await session.flush()

    ai_profile_data = await _persist_ai_metadata(
        session,
        meta=meta,
        options=options,
        tenant_id=tenant_id,
        user_id=user_id,
        resolved_project_id=resolved_project_id,
        file_profile=file_profile,
        ai_result=ai_result,
        catalog_result=catalog_result,
    )

    if resolved_project_id is not None:
        try:
            from app.services.auto_query import ensure_datasource_query

            col_names = [
                c["name"]
                for c in (column_types or [])
                if isinstance(c, dict) and c.get("name")
            ]
            await ensure_datasource_query(
                session,
                project_id=resolved_project_id,
                owner_id=user.id,
                display_name=final_filename,
                view_name=view_name,
                columns=col_names,
            )
        except Exception as exc:  # non-fatal
            logger.warning(
                "Auto-create query for %s failed (non-fatal): %s", view_name, exc
            )

    result = {
        "data_source_id": meta.id,
        "import_job_id": job.id,
        "view_name": view_name,
        "file_name": display_name,
        "project_id": resolved_project_id,
        "acquisition_method": job.method,
        "source_locator_redacted": job.source_locator_redacted,
        "status": "active",
        "message": "Data source created with AI metadata.",
        "ai_profile": ai_profile_data,
    }
    job.status = "completed"
    job.finalized_data_source_id = meta.id
    job.result_json = result
    discard_quarantine(job)
    logger.info(
        "file import finalized job=%s tenant=%s method=%s view=%s",
        job.id,
        tenant_id,
        job.method,
        view_name,
    )
    return result


async def _persist_ai_metadata(
    session: AsyncSession,
    *,
    meta: FileSourceMeta,
    options: FinalizeOptions,
    tenant_id: int,
    user_id: int,
    resolved_project_id: int | None,
    file_profile: dict[str, Any],
    ai_result: dict[str, Any],
    catalog_result: dict[str, Any],
) -> dict[str, Any]:
    """Apply catalog suggestions, tag/KPI decisions, and notes to a source."""
    from app.models.ai_asset_metadata import (
        AIAssetKPI,
        AIAssetKPISuggestion,
        AIAssetTag,
        AIAssetTagSuggestion,
    )
    from app.services import data_source_metadata_service as metadata_svc
    from app.services.upload_ai_profiler_service import (
        _persist_suggestions,
        _update_file_meta,
    )

    if catalog_result and meta.id and resolved_project_id:
        await _persist_suggestions(
            session, tenant_id, resolved_project_id, user_id, meta.id, catalog_result
        )
    if catalog_result and meta.id:
        await _update_file_meta(session, meta.id, catalog_result)

    if resolved_project_id and (options.accepted_tag_keys or options.rejected_tag_keys):
        suggestions = (
            await session.scalars(
                select(AIAssetTagSuggestion).where(
                    AIAssetTagSuggestion.source_id == meta.id,
                    AIAssetTagSuggestion.source_type == "file_datasource",
                    AIAssetTagSuggestion.tenant_id == tenant_id,
                )
            )
        ).all()
        accepted_keys = set(options.accepted_tag_keys or [])
        rejected_keys = set(options.rejected_tag_keys or [])
        for s in suggestions:
            if s.tag_key in accepted_keys:
                s.status = "accepted"  # type: ignore[assignment]
                session.add(
                    AIAssetTag(
                        tenant_id=tenant_id,
                        project_id=resolved_project_id,
                        source_type="file_datasource",
                        source_id=meta.id,
                        tag_key=s.tag_key,
                        display_name=s.display_name,
                        confidence=s.confidence,
                        source="ai_suggested",
                        created_by=user_id,
                    )
                )
            elif s.tag_key in rejected_keys:
                s.status = "rejected"  # type: ignore[assignment]

    if resolved_project_id and (options.accepted_kpi_keys or options.rejected_kpi_keys):
        kpi_suggestions = (
            await session.scalars(
                select(AIAssetKPISuggestion).where(
                    AIAssetKPISuggestion.source_id == meta.id,
                    AIAssetKPISuggestion.source_type == "file_datasource",
                    AIAssetKPISuggestion.tenant_id == tenant_id,
                )
            )
        ).all()
        accepted_kpi_keys = set(options.accepted_kpi_keys or [])
        rejected_kpi_keys = set(options.rejected_kpi_keys or [])
        for ks in kpi_suggestions:
            if ks.kpi_key in accepted_kpi_keys:
                ks.status = "accepted"  # type: ignore[assignment]
                session.add(
                    AIAssetKPI(
                        tenant_id=tenant_id,
                        project_id=resolved_project_id,
                        source_type="file_datasource",
                        source_id=meta.id,
                        kpi_key=ks.kpi_key,
                        display_name=ks.display_name,
                        field_mapping=ks.field_mapping,
                        formula=ks.formula,
                        recommended_chart_type=ks.recommended_chart_type,
                        confidence=ks.confidence,
                        source="ai_suggested",
                        created_by=user_id,
                    )
                )
            elif ks.kpi_key in rejected_kpi_keys:
                ks.status = "rejected"  # type: ignore[assignment]

    if options.user_notes:
        ai_result["user_notes"] = options.user_notes
    if options.user_nuances:
        ai_result["user_nuances"] = options.user_nuances

    ai_profile_data = await metadata_svc.create_ai_profile(
        session,
        data_source_id=meta.id,
        tenant_id=tenant_id,
        user_id=user_id,
        project_id=resolved_project_id,
        file_profile=file_profile,
        ai_result=ai_result,
    )

    if options.accepted_tags is not None:
        await metadata_svc.update_tags(
            session,
            data_source_id=meta.id,
            tenant_id=tenant_id,
            user_id=user_id,
            project_id=resolved_project_id,
            tags=options.accepted_tags,
        )
    if options.recommendation_decisions:
        await metadata_svc.update_recommendations(
            session,
            data_source_id=meta.id,
            recommendations=options.recommendation_decisions,
        )
    if options.user_notes or options.user_nuances:
        await metadata_svc.update_user_notes(
            session,
            data_source_id=meta.id,
            user_notes=options.user_notes,
            user_nuances=options.user_nuances,
        )
    return ai_profile_data


async def finalize_document_import(
    session: AsyncSession,
    job: FileImportJob,
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
    title: str | None = None,
) -> dict[str, Any]:
    """Hand a staged document to the existing Project Asset pipeline.

    Documents never become Teiid views: they are stored as project assets and
    processed by the existing extraction / embedding / knowledge-graph flow.
    """
    from pathlib import Path as _Path

    from app.models.project import Project
    from app.models.project_asset import ProjectAsset
    from app.routes.project_assets import (
        EXTENSION_TO_ASSET_TYPE,
        EXTENSION_TO_CONTENT_TYPE,
        _store_file_locally,
    )

    if job.status == "completed" and job.result_json:
        return job.result_json
    if job.content_family != "document":
        raise FileImportError(
            "WRONG_CONTENT_FAMILY", "That file is not a document import."
        )

    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != tenant_id:
        raise FileImportError("PROJECT_NOT_FOUND", "Project not found")

    job.status = "finalizing"
    data = read_staged_bytes(job)
    filename = job.sanitized_file_name or "document"
    ext = _Path(filename).suffix.lower()
    storage_loc = _store_file_locally(tenant_id, user_id, project_id, filename, data)

    asset = ProjectAsset(
        tenant_id=tenant_id,
        project_id=project_id,
        owner_user_id=user_id,
        asset_type=EXTENSION_TO_ASSET_TYPE.get(ext, "other_document"),
        source_type="uploaded_file",
        title=title or _Path(filename).stem,
        filename=filename,
        original_filename=job.original_file_name or filename,
        content_type=EXTENSION_TO_CONTENT_TYPE.get(
            ext, job.detected_mime_type or "application/octet-stream"
        ),
        file_extension=ext,
        storage_provider="local",
        storage_location=storage_loc,
        file_hash=job.sha256,
        file_size_bytes=job.file_size_bytes or len(data),
        visibility="shared_project",
        status="uploaded",
        ai_status="pending",
        ai_metadata={},
        created_by=user_id,
    )
    session.add(asset)
    await session.flush()

    result = {
        "asset_id": asset.id,
        "import_job_id": job.id,
        "project_id": project_id,
        "file_name": filename,
        "content_family": "document",
        "acquisition_method": job.method,
        "status": "uploaded",
    }
    job.status = "completed"
    job.result_json = result
    discard_quarantine(job)
    return result


async def cleanup_expired_jobs(session: AsyncSession, *, limit: int = 200) -> int:
    """Expire abandoned jobs and delete their quarantined bytes."""
    now = datetime.now(UTC)
    stale = (
        await session.scalars(
            select(FileImportJob)
            .where(
                FileImportJob.expires_at.is_not(None),
                FileImportJob.expires_at < now,
                FileImportJob.status.not_in(
                    ("completed", "failed", "cancelled", "expired")
                ),
            )
            .limit(limit)
        )
    ).all()
    for job in stale:
        discard_quarantine(job)
        job.status = "expired"
    if stale:
        await session.commit()
    return len(stale)
