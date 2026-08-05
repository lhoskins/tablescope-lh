"""Versioned data-source updates: preflight, activate, rollback.

Split from ``upload.py``; siblings: ``upload_core.py``,
``upload_datasources.py`` and ``upload_replace.py``.
"""

from __future__ import annotations

import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.database import get_db
from app.models.audit_event import AuditEvent
from app.models.file_source_meta import FileSourceMeta
from app.models.file_source_version import (
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
    STATUS_FAILED,
    STATUS_ROLLED_BACK,
    STATUS_STAGED,
    FileSourceVersion,
)
from app.models.user import User
from app.routes.database_sources_lifecycle import find_query_dependencies
from app.services.file_source_versions import (
    MODE_REPLACE,
    archive_dir,
    checksum,
    compare_schemas,
    count_data_rows,
    staging_dir,
)
from app.services.file_sources import (
    compute_view_name,
    detect_column_types,
    display_source,
    physical_file_name,
    prepare_replacement_content,
    sanitize_filename,
)
from app.services.tenant_teiid_resolver import TeiidEndpoint, TenantTeiidResolver
from app.services.upload_intake import (
    DESTINATION_DATA_SOURCE,
    UploadRejected,
    classify_upload,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/upload", tags=["upload"])


# ───────────────────────── Versioned data-source updates ─────────────────────
#
# The drag-to-update / "Update data source" workflow never writes over the live
# view. It stages the incoming file as a ``FileSourceVersion``, returns a
# preflight (schema diff + dependency impact), and only activates after an
# explicit confirmation. The superseded file is archived so it can be rolled
# back to.


async def _resolve_uploads_dir(
    session: AsyncSession, *, tenant_id: int, user_id: int
) -> tuple[TeiidEndpoint, Path]:
    settings = get_settings()
    endpoint = await TenantTeiidResolver(session).resolve_for_org(tenant_id)
    if endpoint.is_dedicated and endpoint.vdb_host_path:
        base_path = endpoint.vdb_host_path
    else:
        base_path = settings.customer_base_path
    return endpoint, Path(base_path) / str(tenant_id) / str(user_id) / "uploads"


async def _load_file_source(
    session: AsyncSession, *, tenant_id: int, owner_id: int, view_name: str
) -> FileSourceMeta:
    meta = await session.scalar(
        select(FileSourceMeta).where(
            FileSourceMeta.tenant_id == tenant_id,
            FileSourceMeta.owner_id == owner_id,
            FileSourceMeta.view_name == view_name,
        )
    )
    if meta is None:
        raise HTTPException(status_code=404, detail="Data source not found")
    return meta


def _locate_physical_file(
    uploads_dir: Path, meta: FileSourceMeta, view_name: str
) -> tuple[Path, str]:
    """Find the on-disk file backing ``meta``.

    The live Teiid view name is derived from the physical filename on disk,
    but some rows have a stale ``view_name`` based on the display name. Match
    first by the physical view name, then by the display view name, so both
    modern and legacy sources resolve correctly.
    """
    if uploads_dir.is_dir():
        for candidate in uploads_dir.iterdir():
            if not candidate.is_file():
                continue
            if compute_view_name(candidate.name) == view_name:
                return candidate, candidate.name
            display_name, _ = display_source(candidate.name, meta.source_format)
            if compute_view_name(display_name) == view_name:
                return candidate, candidate.name
    raise HTTPException(status_code=404, detail="Data source file not found")


async def _reimport_through_teiid(
    endpoint: TeiidEndpoint,
    *,
    tenant_id: int,
    user_id: int,
    vdb_type: str,
    filename: str,
    content: bytes,
    content_type: str | None = None,
) -> dict:
    """Publish ``content`` as the source's view, replacing the current one."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            resp = await client.post(
                f"{endpoint.servlet_url}/TeiidExcelImporterTest/upload",
                data={
                    "org_id": str(tenant_id),
                    "user_id": str(user_id),
                    "vdb_type": vdb_type,
                    "replace": "true",
                },
                files={
                    "file": (
                        filename,
                        content,
                        content_type or "application/octet-stream",
                    )
                },
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502, detail=f"Failed to reach Teiid import servlet: {exc}"
        ) from exc
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=resp.status_code, detail=f"Teiid import failed: {resp.text}"
        )
    try:
        result = resp.json()
    except Exception:
        result = {"raw": resp.text}
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


def _audit(
    session: AsyncSession,
    context: RequestContext,
    *,
    event_type: str,
    view_name: str,
    project_id: int | None,
    title: str,
) -> None:
    """Record a durable update event. Never includes file content or paths."""
    session.add(
        AuditEvent(
            tenant_id=context.tenant_id,
            project_id=project_id,
            user_id=context.user_id,
            event_type=event_type,
            scope="data_source_update",
            prompt_type=view_name[:100],
            title=title[:500],
            tables_queried=[view_name],
            documents_read=[],
            duration_ms=None,
        )
    )


async def _ensure_baseline_version(
    session: AsyncSession,
    *,
    meta: FileSourceMeta,
    existing_path: Path,
    existing_name: str,
) -> FileSourceVersion:
    """Return the active version row, materialising one for legacy sources."""
    active = await session.scalar(
        select(FileSourceVersion).where(
            FileSourceVersion.file_source_id == meta.id,
            FileSourceVersion.status == STATUS_ACTIVE,
        )
    )
    if active is not None:
        return active
    try:
        content = existing_path.read_bytes()
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"Could not read existing file: {exc}"
        ) from exc
    baseline = FileSourceVersion(
        tenant_id=meta.tenant_id,
        file_source_id=meta.id,
        uploader_id=meta.owner_id,
        version_number=1,
        status=STATUS_ACTIVE,
        update_mode=MODE_REPLACE,
        original_filename=meta.file_name or existing_name,
        stored_path=str(existing_path),
        checksum=checksum(content),
        size_bytes=len(content),
        row_count=count_data_rows(content, existing_name),
        column_types=meta.column_types or detect_column_types(content, existing_name),
        compatibility={"baseline": True},
        activated_at=datetime.now(UTC),
    )
    session.add(baseline)
    await session.flush()
    return baseline


@router.post("/datasources/{view_name}/versions/preflight")
async def preflight_source_update(
    view_name: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    """Stage a replacement file and report what activating it would change."""
    if file.filename is None:
        raise HTTPException(status_code=400, detail="Filename is required")

    user = await session.get(User, context.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    meta = await _load_file_source(
        session,
        tenant_id=context.tenant_id,
        owner_id=context.user_id,
        view_name=view_name,
    )
    # Validate the file itself before touching the tenant's storage.
    incoming_content = await file.read()
    try:
        classification = classify_upload(file.filename, incoming_content, file.content_type)
    except UploadRejected as exc:
        raise HTTPException(
            status_code=422, detail={"code": exc.code, "message": exc.message}
        ) from exc
    if classification.destination != DESTINATION_DATA_SOURCE:
        raise HTTPException(
            status_code=409,
            detail=(
                "Only tabular files can update a data source. "
                f"{file.filename} was classified as a document."
            ),
        )

    _, uploads_dir = await _resolve_uploads_dir(
        session, tenant_id=context.tenant_id, user_id=user.id
    )
    existing_path, existing_name = _locate_physical_file(uploads_dir, meta, view_name)

    # 1) Same-name check. The user must supply the same original display name.
    expected_name, _ = display_source(existing_name, meta.source_format)
    if sanitize_filename(file.filename) != sanitize_filename(expected_name):
        raise HTTPException(
            status_code=409,
            detail=(
                f'File name mismatch: expected "{expected_name}", got "{file.filename}". '
                "An update must use the same file name so the source keeps its identity."
            ),
        )
    if meta.file_name != expected_name:
        # Self-heal a stale stored name so future reads/checks agree with it.
        meta.file_name = expected_name

    # Decide the target physical filename. This migrates legacy .csv files to
    # their original extension (e.g. .xlsx) while keeping JSON/XML as .csv.
    new_original_format = (
        file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else None
    )
    target_name = physical_file_name(expected_name, new_original_format)

    target_content = prepare_replacement_content(
        file.filename, incoming_content, target_name
    )

    baseline = await _ensure_baseline_version(
        session, meta=meta, existing_path=existing_path, existing_name=existing_name
    )

    try:
        existing_raw = existing_path.read_bytes()
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"Could not read existing file: {exc}"
        ) from exc
    existing_types = detect_column_types(existing_raw, existing_name)
    incoming_types = detect_column_types(target_content, target_name)
    diff = compare_schemas(existing_types, incoming_types)

    dependencies = await find_query_dependencies(
        session, tenant_id=context.tenant_id, view_name=view_name
    )

    incoming_checksum = checksum(target_content)
    warnings: list[str] = []
    if incoming_checksum == baseline.checksum:
        warnings.append("The new file is identical to the active version.")
    if diff["addedColumns"]:
        warnings.append(
            "New column(s) will be added: " + ", ".join(diff["addedColumns"])
        )
    if diff["blockers"] and dependencies:
        warnings.append(
            f"{len(dependencies)} saved query/queries depend on this source and may break."
        )

    next_number = (
        await session.scalar(
            select(FileSourceVersion.version_number)
            .where(FileSourceVersion.file_source_id == meta.id)
            .order_by(FileSourceVersion.version_number.desc())
        )
        or 0
    ) + 1

    compatibility = {
        **diff,
        "dependencies": dependencies,
        "warnings": warnings,
        "currentFileName": meta.file_name,
        "proposedFileName": file.filename,
        "currentRowCount": baseline.row_count,
        "proposedRowCount": count_data_rows(target_content, target_name),
        "currentChecksum": baseline.checksum,
        "proposedChecksum": incoming_checksum,
        "updateMode": MODE_REPLACE,
    }

    staged = FileSourceVersion(
        tenant_id=context.tenant_id,
        file_source_id=meta.id,
        uploader_id=context.user_id,
        version_number=next_number,
        status=STATUS_STAGED,
        update_mode=MODE_REPLACE,
        original_filename=file.filename,
        checksum=incoming_checksum,
        size_bytes=len(target_content),
        row_count=compatibility["proposedRowCount"],
        column_types=incoming_types or None,
        compatibility=compatibility,
        replaced_version_id=baseline.id,
    )
    session.add(staged)
    await session.flush()

    stage_dir = staging_dir(uploads_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)
    staged_path = stage_dir / f"{staged.id}_{sanitize_filename(target_name)}"
    staged_path.write_bytes(target_content)
    staged.stored_path = str(staged_path)

    _audit(
        session,
        context,
        event_type="data_source_update_staged",
        view_name=view_name,
        project_id=meta.project_id,
        title=f"Staged version {next_number} for {view_name}",
    )
    await session.commit()

    return {
        "status": "preflight_ready",
        "viewName": view_name,
        "version": staged.to_dict(),
        "activeVersion": baseline.to_dict(),
        "compatibility": compatibility,
        "canActivate": diff["compatible"],
        "classification": classification.to_dict(),
    }


@router.get("/datasources/{view_name}/versions")
async def list_source_versions(
    view_name: str,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> list[dict]:
    """Version history for a file data source, newest first."""
    meta = await _load_file_source(
        session,
        tenant_id=context.tenant_id,
        owner_id=context.user_id,
        view_name=view_name,
    )
    versions = (
        await session.scalars(
            select(FileSourceVersion)
            .where(FileSourceVersion.file_source_id == meta.id)
            .order_by(FileSourceVersion.version_number.desc())
        )
    ).all()
    return [v.to_dict() for v in versions]


async def _activate_content(
    session: AsyncSession,
    context: RequestContext,
    *,
    meta: FileSourceMeta,
    version: FileSourceVersion,
    content: bytes,
    filename: str,
    uploads_dir: Path,
    existing_path: Path,
    existing_name: str,
    endpoint: TeiidEndpoint,
    tenant_id: int,
    user_id: int,
) -> str:
    """Archive the live file, publish ``content``, then flip the pointer.

    The prior file is copied into the archive directory *before* the servlet
    re-imports, so a failed import leaves both the archive copy and the live
    version intact.
    """
    previous_active = await session.scalar(
        select(FileSourceVersion).where(
            FileSourceVersion.file_source_id == meta.id,
            FileSourceVersion.status == STATUS_ACTIVE,
        )
    )
    expected_name, _ = display_source(existing_name, meta.source_format)
    new_original_format = filename.rsplit(".", 1)[-1].lower() if "." in filename else None
    target_name = physical_file_name(expected_name, new_original_format)
    target_path = uploads_dir / target_name

    if previous_active is not None and previous_active.id != version.id:
        archive_root = archive_dir(uploads_dir) / str(previous_active.id)
        archive_root.mkdir(parents=True, exist_ok=True)
        archived_copy = archive_root / existing_name
        try:
            shutil.copy2(existing_path, archived_copy)
            previous_active.stored_path = str(archived_copy)
        except OSError as exc:
            raise HTTPException(
                status_code=500, detail=f"Could not archive the current version: {exc}"
            ) from exc

    try:
        await _reimport_through_teiid(
            endpoint,
            tenant_id=tenant_id,
            user_id=user_id,
            vdb_type=meta.vdb_type or "user",
            filename=target_name,
            content=content,
        )
    except HTTPException as exc:
        version.status = STATUS_FAILED
        version.error_message = str(exc.detail)[:1024]
        _audit(
            session,
            context,
            event_type="data_source_update_failed",
            view_name=meta.view_name,
            project_id=meta.project_id,
            title=f"Activation of version {version.version_number} failed",
        )
        await session.commit()
        raise

    if previous_active is not None and previous_active.id != version.id:
        previous_active.status = STATUS_ARCHIVED

    if existing_path != target_path:
        try:
            existing_path.unlink()
        except OSError as exc:
            logger.warning("Could not remove legacy physical file %s: %s", existing_path, exc)

    new_display_name, _ = display_source(target_name, new_original_format)
    meta.view_name = compute_view_name(target_name)
    meta.file_name = new_display_name
    meta.source_format = new_original_format
    meta.column_types = version.column_types or None

    version.status = STATUS_ACTIVE
    version.activated_at = datetime.now(UTC)
    version.error_message = None
    return target_name


@router.post("/datasources/{view_name}/versions/{version_id}/activate")
async def activate_source_version(
    view_name: str,
    version_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    """Activate a staged version after its preflight came back compatible."""
    user = await session.get(User, context.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    meta = await _load_file_source(
        session,
        tenant_id=context.tenant_id,
        owner_id=context.user_id,
        view_name=view_name,
    )
    version = await session.get(FileSourceVersion, version_id)
    if (
        version is None
        or version.file_source_id != meta.id
        or version.tenant_id != context.tenant_id
    ):
        raise HTTPException(status_code=404, detail="Version not found")
    if version.status == STATUS_ACTIVE:
        # Idempotent retry of a completed activation.
        return {"status": "active", "viewName": view_name, "version": version.to_dict()}
    if version.status != STATUS_STAGED:
        raise HTTPException(
            status_code=409,
            detail=f"Version {version.version_number} is {version.status} and cannot be activated.",
        )
    compatibility = version.compatibility or {}
    if compatibility.get("blockers"):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "incompatible_schema",
                "message": "Resolve the blocking schema changes before activating.",
                "blockers": compatibility["blockers"],
            },
        )
    if version.stored_path is None:
        raise HTTPException(status_code=409, detail="Staged file is no longer available.")

    endpoint, uploads_dir = await _resolve_uploads_dir(
        session, tenant_id=context.tenant_id, user_id=user.id
    )
    existing_path, existing_name = _locate_physical_file(uploads_dir, meta, view_name)
    try:
        content = Path(version.stored_path).read_bytes()
    except OSError as exc:
        raise HTTPException(
            status_code=409, detail=f"Staged file is no longer available: {exc}"
        ) from exc

    activated_target_name = await _activate_content(
        session,
        context,
        meta=meta,
        version=version,
        content=content,
        filename=version.original_filename,
        uploads_dir=uploads_dir,
        existing_path=existing_path,
        existing_name=existing_name,
        endpoint=endpoint,
        tenant_id=context.tenant_id,
        user_id=user.id,
    )

    # Keep the activated file as this version's archive copy so a later
    # rollback can restore it.
    archive_root = archive_dir(uploads_dir) / str(version.id)
    archive_root.mkdir(parents=True, exist_ok=True)
    activated_copy = archive_root / activated_target_name
    activated_copy.write_bytes(content)
    try:
        Path(version.stored_path).unlink()
    except OSError:
        logger.warning("Could not remove staged file for version %s", version.id)
    version.stored_path = str(activated_copy)

    _audit(
        session,
        context,
        event_type="data_source_update_activated",
        view_name=meta.view_name,
        project_id=meta.project_id,
        title=f"Activated version {version.version_number} of {view_name}",
    )
    await session.commit()
    return {
        "status": "active",
        "viewName": meta.view_name,
        "fileName": meta.file_name,
        "version": version.to_dict(),
        "columnTypes": version.column_types or [],
        "addedColumns": compatibility.get("addedColumns", []),
    }


@router.post("/datasources/{view_name}/versions/{version_id}/rollback")
async def rollback_source_version(
    view_name: str,
    version_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    """Re-activate a previously archived version of a file data source."""
    user = await session.get(User, context.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    meta = await _load_file_source(
        session,
        tenant_id=context.tenant_id,
        owner_id=context.user_id,
        view_name=view_name,
    )
    target = await session.get(FileSourceVersion, version_id)
    if (
        target is None
        or target.file_source_id != meta.id
        or target.tenant_id != context.tenant_id
    ):
        raise HTTPException(status_code=404, detail="Version not found")
    if target.status not in (STATUS_ARCHIVED, STATUS_ROLLED_BACK):
        raise HTTPException(
            status_code=409,
            detail=f"Only archived versions can be rolled back to (version is {target.status}).",
        )
    if target.stored_path is None or not Path(target.stored_path).is_file():
        raise HTTPException(
            status_code=409,
            detail="The archived file for this version is no longer available.",
        )

    endpoint, uploads_dir = await _resolve_uploads_dir(
        session, tenant_id=context.tenant_id, user_id=user.id
    )
    existing_path, existing_name = _locate_physical_file(uploads_dir, meta, view_name)
    content = Path(target.stored_path).read_bytes()

    superseded = await session.scalar(
        select(FileSourceVersion).where(
            FileSourceVersion.file_source_id == meta.id,
            FileSourceVersion.status == STATUS_ACTIVE,
        )
    )
    await _activate_content(
        session,
        context,
        meta=meta,
        version=target,
        content=content,
        filename=target.original_filename,
        uploads_dir=uploads_dir,
        existing_path=existing_path,
        existing_name=existing_name,
        endpoint=endpoint,
        tenant_id=context.tenant_id,
        user_id=user.id,
    )
    if superseded is not None and superseded.id != target.id:
        superseded.status = STATUS_ROLLED_BACK

    _audit(
        session,
        context,
        event_type="data_source_update_rolled_back",
        view_name=view_name,
        project_id=meta.project_id,
        title=f"Rolled back {view_name} to version {target.version_number}",
    )
    await session.commit()
    return {
        "status": "rolled_back",
        "viewName": view_name,
        "fileName": meta.file_name,
        "version": target.to_dict(),
    }
