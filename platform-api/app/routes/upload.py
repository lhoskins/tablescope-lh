"""File upload route.

Forwards the uploaded file to the Teiid ``TeiidExcelImporterTest`` servlet
which handles:

1. Saving the file into the tenant/user directory on the shared volume
   (``/opt/wildfly/teiidfiles/customers/{org_id}/{user_id}/uploads/``).
2. Parsing Excel/CSV/TXT files to extract column names and data types.
3. Updating the VDB XML with new data-source and model definitions.
4. Redeploying the VDB via the Teiid Admin API.

The platform API acts as an authenticated proxy — it resolves the caller's
tenant and user IDs, then delegates all file processing and metadata
insertion to the Java servlet.
"""

from __future__ import annotations

import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.database import get_db
from app.models.audit_event import AuditEvent
from app.models.database_data_source import DatabaseDataSource
from app.models.file_source_meta import FileSourceMeta
from app.models.file_source_version import (
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
    STATUS_FAILED,
    STATUS_ROLLED_BACK,
    STATUS_STAGED,
    FileSourceVersion,
)
from app.models.project import Project
from app.models.tenant import Tenant
from app.models.user import User
from app.routes.database_sources import find_query_dependencies
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
    convert_to_csv_if_needed,
    detect_column_types,
    display_source,
    sanitize_csv_content,
    sanitize_filename,
    sanitize_xlsx_content,
)
from app.services.tenant_teiid_resolver import TeiidEndpoint, TenantTeiidResolver
from app.services.upload_intake import (
    DESTINATION_DATA_SOURCE,
    UploadRejected,
    classify_upload,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/upload", tags=["upload"])


@router.post("")
async def upload_file(
    file: UploadFile = File(...),
    vdb_type: str | None = Form(None),
    project_id: int | None = Form(None),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    """Forward file to the Teiid servlet for import and metadata insertion.

    When ``project_id`` is supplied the resulting file data source is
    automatically associated with that project under the uploading user as
    owner (item 3).
    """
    if file.filename is None:
        raise HTTPException(status_code=400, detail="Filename is required")

    user = await session.get(User, context.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    tenant = await session.get(Tenant, context.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    content = await file.read()

    # ── Comprehensive upload cleaning (no user interaction) ──────────
    # 1. Sanitize the filename: remove $, commas, whitespace, reserved chars
    clean_name = sanitize_filename(file.filename)
    logger.info("Filename sanitized: %r → %r", file.filename, clean_name)

    # 2. Clean column headers + cell values in CSV / XLSX
    lower_name = clean_name.lower()
    if lower_name.endswith((".csv", ".tsv", ".txt")):
        content = sanitize_csv_content(content)
    elif lower_name.endswith((".xlsx", ".xlsm", ".xls")):
        content = sanitize_xlsx_content(content)
        # sanitize_xlsx_content returns CSV bytes
        clean_name = clean_name.rsplit(".", 1)[0] + ".csv"

    # Remember the original uploaded extension so the UI can show the real type
    # (e.g. "json"/"xml") even though JSON/XML are flattened to CSV below.
    original_format = (
        file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else None
    )

    # JSON/XML uploads are flattened to CSV so they import through the same
    # Teiid file pipeline as CSV/Excel and behave like every other data source.
    try:
        filename, content = convert_to_csv_if_needed(clean_name, content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Preserve the original extension for display/naming while the on-disk file
    # stays the CSV representation the Teiid pipeline requires.
    display_name, _ = display_source(filename, original_format)

    endpoint = await TenantTeiidResolver(session).resolve_for_org(context.tenant_id)
    servlet_url = (
        f"{endpoint.servlet_url}/TeiidExcelImporterTest/upload"
    )

    resolved_vdb_type = vdb_type or "user"

    logger.info(
        "Forwarding upload to Teiid servlet: file=%s org_id=%s user_id=%s vdb_type=%s endpoint=%s",
        filename,
        tenant.id,
        user.id,
        resolved_vdb_type,
        "dedicated" if endpoint.is_dedicated else "shared",
    )

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=10.0)
        ) as client:
            resp = await client.post(
                servlet_url,
                data={
                    "org_id": str(tenant.id),
                    "user_id": str(user.id),
                    "vdb_type": resolved_vdb_type,
                },
                files={"file": (filename, content, file.content_type or "application/octet-stream")},
            )
    except httpx.RequestError as exc:
        logger.error("Failed to reach Teiid servlet: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=f"Failed to reach Teiid import servlet: {exc}",
        ) from exc

    if resp.status_code >= 400:
        logger.error(
            "Teiid servlet returned %s: %s", resp.status_code, resp.text
        )
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"Teiid import failed: {resp.text}",
        )

    try:
        teiid_result = resp.json()
    except Exception:
        teiid_result = {"raw": resp.text}

    logger.info("Teiid servlet response: %s", teiid_result)

    # The servlet may return HTTP 200 but include an error in the JSON body
    if "error" in teiid_result:
        logger.error("Teiid servlet processing error: %s", teiid_result["error"])
        raise HTTPException(
            status_code=422,
            detail=teiid_result["error"],
        )

    # Build the datasource name from the original upload name (not the CSV
    # intermediate filename) so XLSX/JSON/XML sources keep their real extension.
    base_name = display_name.rsplit(".", 1)[0].replace(" ", "_")
    extension = display_name.rsplit(".", 1)[-1].upper() if "." in display_name else ""
    datasource_name = f"{base_name}_{extension}" if extension else base_name

    # Sync uploaded file to S3 if enabled
    settings_obj = get_settings()
    s3_location = None
    if settings_obj.s3_enabled:
        try:
            from app.services.s3_storage import S3StorageService
            s3_svc = S3StorageService()
            local_file_path = f"{settings_obj.customer_base_path}/{tenant.id}/{user.id}/uploads/{filename}"
            s3_key = s3_svc.get_s3_key_for_upload(tenant.id, user.id, filename)
            s3_location = s3_svc.upload_file(local_file_path, s3_key)
        except Exception as e:
            logger.warning("S3 upload sync failed (non-fatal): %s", e)

    # Detect per-column formatting types (currency/date/number) for item 6.
    column_types = detect_column_types(content, filename)

    # Validate the requested project (if any) belongs to this tenant.
    resolved_project_id: int | None = None
    if project_id is not None:
        project = await session.get(Project, project_id)
        if project is None or project.tenant_id != context.tenant_id:
            raise HTTPException(status_code=404, detail="Project not found")
        resolved_project_id = project_id

    # Upsert the file-source metadata row (project association, archive flag,
    # column types). Keyed by (tenant, owner, view_name).
    view_name = compute_view_name(display_name)
    existing = await session.scalar(
        select(FileSourceMeta).where(
            FileSourceMeta.tenant_id == context.tenant_id,
            FileSourceMeta.owner_id == user.id,
            FileSourceMeta.view_name == view_name,
        )
    )
    if existing is None:
        session.add(
            FileSourceMeta(
                tenant_id=context.tenant_id,
                owner_id=user.id,
                project_id=resolved_project_id,
                view_name=view_name,
                file_name=display_name,
                vdb_type=resolved_vdb_type,
                source_format=original_format,
                column_types=column_types or None,
            )
        )
    else:
        existing.file_name = display_name
        existing.vdb_type = resolved_vdb_type
        existing.source_format = original_format
        if column_types:
            existing.column_types = column_types
        # Re-associating via a project upload (re)links to that project; a plain
        # personal re-upload leaves the existing association untouched.
        if resolved_project_id is not None:
            existing.project_id = resolved_project_id
        existing.archived = False
        existing.archived_at = None
    await session.commit()

    # Auto-create a saved query named after this data source (project uploads
    # only). Best-effort: never fail the upload if query creation has issues.
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
                display_name=display_name,
                view_name=view_name,
                columns=col_names,
            )
            await session.commit()
        except Exception as exc:  # non-fatal
            logger.warning(
                "Auto-create query for %s failed (non-fatal): %s",
                view_name,
                exc,
            )
            await session.rollback()

    return {
        "path": f"/opt/wildfly/teiidfiles/customers/{tenant.id}/{user.id}/uploads/{filename}",
        "size": len(content),
        "datasource": datasource_name,
        "fileName": display_name,
        "viewName": view_name,
        "columnTypes": column_types,
        "projectId": resolved_project_id,
        "teiid": teiid_result,
        "s3_location": s3_location,
    }


@router.get("/datasources")
async def list_datasources(
    include_archived: bool = False,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> list[dict]:
    """List uploaded datasources for the current user by scanning their uploads directory."""
    user = await session.get(User, context.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    settings = get_settings()
    endpoint = await TenantTeiidResolver(session).resolve_for_org(context.tenant_id)
    if endpoint.is_dedicated and endpoint.vdb_host_path:
        base_path = endpoint.vdb_host_path
    else:
        base_path = settings.customer_base_path
    uploads_dir = Path(base_path) / str(context.tenant_id) / str(user.id) / "uploads"

    # Metadata (archive flag, project association, column types) keyed by view.
    meta_rows = (
        await session.scalars(
            select(FileSourceMeta).where(
                FileSourceMeta.tenant_id == context.tenant_id,
                FileSourceMeta.owner_id == user.id,
            )
        )
    ).all()
    meta_by_view = {m.view_name: m for m in meta_rows}

    datasources: list[dict] = []
    if uploads_dir.is_dir():
        for f in sorted(uploads_dir.iterdir()):
            if f.is_file() and not f.name.startswith("."):
                base_name = f.stem.replace(" ", "_")
                extension = f.suffix.lstrip(".").upper()
                view_name = f"{base_name}_{extension}" if extension else base_name
                meta = meta_by_view.get(view_name)
                is_archived = bool(meta and meta.archived)
                if is_archived and not include_archived:
                    continue
                display_name, source_type = display_source(
                    f.name, meta.source_format if meta else None
                )
                datasources.append({
                    "fileName": display_name,
                    "viewName": view_name,
                    "size": f.stat().st_size,
                    "sourceType": source_type,
                    "dbType": None,
                    "fileMetaId": meta.id if meta else None,
                    "projectId": meta.project_id if meta else None,
                    "columnTypes": (meta.column_types or []) if meta else [],
                    "archived": is_archived,
                })

    # Append the user's database-backed data sources (not tied to a project).
    db_sources = (
        await session.scalars(
            select(DatabaseDataSource).where(
                DatabaseDataSource.tenant_id == context.tenant_id,
                DatabaseDataSource.created_by == user.id,
                DatabaseDataSource.project_id.is_(None),
                DatabaseDataSource.status == "active",
                DatabaseDataSource.archived.is_(False),
            )
        )
    ).all()
    for ds in db_sources:
        is_saas = ds.source_type == "saas_object"
        datasources.append({
            "fileName": ds.display_name,
            "viewName": ds.teiid_view_name,
            "size": None,
            "sourceType": "saas_object" if is_saas else "database_table",
            "dbType": ds.db_type,
            "connectorType": ds.connector_type,
            "id": ds.id,
        })

    return datasources


async def _get_or_create_file_meta(
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
        meta = FileSourceMeta(
            tenant_id=tenant_id,
            owner_id=owner_id,
            view_name=view_name,
            file_name=view_name,
        )
        session.add(meta)
        await session.flush()
    return meta


@router.patch("/datasources/{view_name}/archive")
async def archive_file_source(
    view_name: str,
    archived: bool = True,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    """Archive (hide) or unarchive an uploaded-file data source (item 1)."""
    from datetime import UTC, datetime

    meta = await _get_or_create_file_meta(
        session,
        tenant_id=context.tenant_id,
        owner_id=context.user_id,
        view_name=view_name,
    )
    meta.archived = archived
    meta.archived_at = datetime.now(UTC) if archived else None
    await session.commit()
    await session.refresh(meta)
    return meta.to_dict()


@router.patch("/datasources/{view_name}/project")
async def set_file_source_project(
    view_name: str,
    project_id: int | None = None,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    """Associate/de-associate a file data source with a project (item 3).

    Only the data source owner (uploader) may change its project association.
    Pass no ``project_id`` to remove it from its project.
    """
    meta = await _get_or_create_file_meta(
        session,
        tenant_id=context.tenant_id,
        owner_id=context.user_id,
        view_name=view_name,
    )
    if project_id is not None:
        project = await session.get(Project, project_id)
        if project is None or project.tenant_id != context.tenant_id:
            raise HTTPException(status_code=404, detail="Project not found")
    meta.project_id = project_id
    await session.commit()
    await session.refresh(meta)
    return meta.to_dict()


@router.get("/datasources/{view_name}/preflight-delete")
async def preflight_delete_file_source(
    view_name: str,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    """Return whether a file data source can be permanently deleted."""
    meta = await session.scalar(
        select(FileSourceMeta).where(
            FileSourceMeta.tenant_id == context.tenant_id,
            FileSourceMeta.owner_id == context.user_id,
            FileSourceMeta.view_name == view_name,
        )
    )
    if meta is None:
        raise HTTPException(status_code=404, detail="Data source not found")

    blockers: list[dict[str, str]] = []
    if not meta.archived:
        blockers.append({
            "category": "not_archived",
            "message": "Archive the data source before deleting it.",
        })

    deps = await find_query_dependencies(
        session, tenant_id=context.tenant_id, view_name=view_name
    )
    if deps:
        blockers.append({
            "category": "active_dependencies",
            "message": f"{len(deps)} active saved quer{'y' if len(deps) == 1 else 'ies'} depend on this source.",
        })

    from app.models.data_source_ai_profile import DataSourceAIProfile

    ai_profile = await session.scalar(
        select(DataSourceAIProfile).where(DataSourceAIProfile.data_source_id == meta.id)
    )
    ai_profile_count = 1 if ai_profile else 0

    return {
        "view_name": view_name,
        "safe": len(blockers) == 0 and meta.archived,
        "archived": meta.archived,
        "blockers": blockers,
        "active_query_dependencies": deps,
        "ai_profile_count": ai_profile_count,
    }


@router.delete("/datasources/{view_name}")
async def delete_file_source(
    view_name: str,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    """Delete an uploaded-file data source (item 1).

    Mirrors database-source delete rules: the source must be archived first,
    and may not be deleted while an active saved query depends on it.
    """
    user = await session.get(User, context.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    meta = await session.scalar(
        select(FileSourceMeta).where(
            FileSourceMeta.tenant_id == context.tenant_id,
            FileSourceMeta.owner_id == context.user_id,
            FileSourceMeta.view_name == view_name,
        )
    )
    if meta is None or not meta.archived:
        raise HTTPException(
            status_code=409,
            detail="Archive the data source before deleting it.",
        )

    deps = await find_query_dependencies(
        session, tenant_id=context.tenant_id, view_name=view_name
    )
    if deps:
        names = ", ".join(d["name"] for d in deps)
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete: {len(deps)} active query(ies) depend on this source ({names}).",
        )

    # Remove the physical file (best-effort) and the metadata row. Bound
    # tenants store uploads under their dedicated data plane's VDB path.
    settings = get_settings()
    endpoint = await TenantTeiidResolver(session).resolve_for_org(context.tenant_id)
    if endpoint.is_dedicated and endpoint.vdb_host_path:
        base_path = endpoint.vdb_host_path
    else:
        base_path = settings.customer_base_path
    uploads_dir = (
        Path(base_path)
        / str(context.tenant_id)
        / str(context.user_id)
        / "uploads"
    )
    # Remove all file variants (original + converted CSV).
    # XLSX files are converted to CSV on upload, so both may exist.
    candidates = [
        uploads_dir / meta.file_name,
    ]
    # If the stored name ends with .xlsx/.xls, also try the .csv variant
    stem = meta.file_name.rsplit(".", 1)[0] if "." in meta.file_name else meta.file_name
    for ext in (".csv", ".xlsx", ".xls", ".txt", ".tsv"):
        candidates.append(uploads_dir / f"{stem}{ext}")
    # Also try matching by view_name stem (e.g., ManagmentReport from ManagmentReport_CSV)
    view_stem = view_name.rsplit("_", 1)[0] if "_" in view_name else view_name
    for ext in (".csv", ".xlsx", ".xls", ".txt", ".tsv"):
        candidates.append(uploads_dir / f"{view_stem}{ext}")

    removed_any = False
    for candidate in candidates:
        try:
            if candidate.is_file():
                candidate.unlink()
                removed_any = True
                logger.info("Removed file: %s", candidate)
        except OSError as exc:
            logger.warning("Failed to remove file %s: %s", candidate, exc)

    if not removed_any:
        logger.warning("No physical file found for %s in %s", view_name, uploads_dir)

    # Remove Teiid view and foreign table (best-effort)
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0)
        ) as teiid_client:
            teiid_resp = await teiid_client.post(
                f"{endpoint.servlet_url}/TeiidExcelImporterTest/deleteDataSource",
                data={"dataSourceName": view_name},
            )
            if teiid_resp.status_code == 200:
                logger.info("Teiid view/foreign-table removed for %s", view_name)
            else:
                logger.warning(
                    "Teiid deleteDataSource returned %s for %s: %s",
                    teiid_resp.status_code, view_name, teiid_resp.text,
                )
    except httpx.RequestError as exc:
        logger.warning("Failed to contact Teiid servlet to delete %s: %s", view_name, exc)

    # Also clean up any orphaned AI profile data
    from app.models.data_source_ai_profile import (
        DataSourceAIProfile,
        DataSourceAIRecommendation,
        DataSourceFieldProfile,
        DataSourceTag,
    )

    for model in (DataSourceAIRecommendation, DataSourceTag, DataSourceFieldProfile, DataSourceAIProfile):
        orphans = (
            await session.scalars(
                select(model).where(model.data_source_id == meta.id)
            )
        ).all()
        for o in orphans:
            await session.delete(o)

    await session.delete(meta)
    await session.commit()
    return {"status": "deleted", "view_name": view_name}


@router.post("/datasources/{view_name}/replace")
async def replace_file_source(
    view_name: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    """Replace an uploaded file's data with a new file (item 5).

    The incoming file must have the **same name** as the existing source and
    must contain **all** of the existing columns. New columns are allowed and
    are added without affecting existing data.
    """
    if file.filename is None:
        raise HTTPException(status_code=400, detail="Filename is required")

    user = await session.get(User, context.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    tenant = await session.get(Tenant, context.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    settings = get_settings()
    endpoint = await TenantTeiidResolver(session).resolve_for_org(context.tenant_id)
    if endpoint.is_dedicated and endpoint.vdb_host_path:
        base_path = endpoint.vdb_host_path
    else:
        base_path = settings.customer_base_path
    uploads_dir = (
        Path(base_path)
        / str(context.tenant_id)
        / str(user.id)
        / "uploads"
    )

    # Locate the metadata row first so we know the original source format and
    # can map the display view_name back to the physical (possibly converted) file.
    meta = await session.scalar(
        select(FileSourceMeta).where(
            FileSourceMeta.tenant_id == context.tenant_id,
            FileSourceMeta.owner_id == user.id,
            FileSourceMeta.view_name == view_name,
        )
    )
    if meta is None:
        raise HTTPException(status_code=404, detail="Data source not found")

    # Resolve the existing physical file backing this view.
    existing_path: Path | None = None
    existing_name: str | None = None
    if uploads_dir.is_dir():
        for f in uploads_dir.iterdir():
            if f.is_file():
                physical_display_name, _ = display_source(f.name, meta.source_format)
                if compute_view_name(physical_display_name) == view_name:
                    existing_path = f
                    existing_name = f.name
                    break
    if existing_path is None or existing_name is None:
        raise HTTPException(status_code=404, detail="Data source not found")

    # 1) Same-name check.
    if sanitize_filename(file.filename) != sanitize_filename(meta.file_name):
        raise HTTPException(
            status_code=409,
            detail=(
                f'File name mismatch: expected "{meta.file_name}", '
                f'got "{file.filename}". Replacement must use the same file name.'
            ),
        )

    content = await file.read()

    # ── Replacement cleaning (same as the original upload path) ─────────
    # Apply header/cell sanitization to both files so the column compatibility
    # check and the VDB DDL are working with the same safe identifiers.
    lower_name = existing_name.lower()
    if lower_name.endswith((".csv", ".tsv", ".txt")):
        content = sanitize_csv_content(content)
        existing_content = sanitize_csv_content(existing_path.read_bytes())
    elif lower_name.endswith((".xlsx", ".xlsm", ".xls")):
        # The original upload flattens XLSX to CSV; keep that behavior here.
        content = sanitize_xlsx_content(content)
        existing_content = sanitize_xlsx_content(existing_path.read_bytes())
    else:
        existing_content = existing_path.read_bytes()

    # 2) Column compatibility check: incoming must contain all existing columns.
    existing_types = detect_column_types(existing_content, existing_name)
    existing_cols = {c["field"] for c in existing_types}
    incoming_types = detect_column_types(content, file.filename)
    incoming_cols = {c["field"] for c in incoming_types}
    diff = compare_schemas(existing_types, incoming_types)
    if diff["blockers"]:
        raise HTTPException(status_code=409, detail=" ".join(diff["blockers"]))

    # 3) Re-import the new file through the Teiid servlet (overwrites the view).
    resolved_vdb_type = meta.vdb_type if meta else "user"
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
                    "vdb_type": resolved_vdb_type,
                    # This is a replace: tell the servlet to overwrite the
                    # existing view/foreign table instead of returning a 409
                    # "already exists / requiresConfirmation" conflict.
                    "replace": "true",
                },
                files={
                    "file": (
                        file.filename,
                        content,
                        file.content_type or "application/octet-stream",
                    )
                },
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to reach Teiid import servlet: {exc}",
        ) from exc
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"Teiid import failed: {resp.text}",
        )
    try:
        teiid_result = resp.json()
    except Exception:
        teiid_result = {"raw": resp.text}
    if isinstance(teiid_result, dict) and "error" in teiid_result:
        raise HTTPException(status_code=422, detail=teiid_result["error"])

    # 4) Update metadata column types and display name (preserve project association/archive).
    new_original_format = (
        file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else None
    )
    new_display_name, _ = display_source(existing_name, new_original_format)
    meta.file_name = new_display_name
    meta.source_format = new_original_format
    meta.column_types = incoming_types or None
    await session.commit()

    added = sorted(incoming_cols - existing_cols)
    return {
        "status": "replaced",
        "view_name": view_name,
        "fileName": new_display_name,
        "addedColumns": added,
        "columnTypes": incoming_types,
    }


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
    if uploads_dir.is_dir():
        for candidate in uploads_dir.iterdir():
            if not candidate.is_file():
                continue
            physical_display_name, _ = display_source(candidate.name, meta.source_format)
            if compute_view_name(physical_display_name) == view_name:
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
    content = await file.read()
    try:
        classification = classify_upload(file.filename, content, file.content_type)
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
    if sanitize_filename(file.filename) != sanitize_filename(meta.file_name):
        raise HTTPException(
            status_code=409,
            detail=(
                f'File name mismatch: expected "{meta.file_name}", got "{file.filename}". '
                "An update must use the same file name so the source keeps its identity."
            ),
        )

    _, uploads_dir = await _resolve_uploads_dir(
        session, tenant_id=context.tenant_id, user_id=user.id
    )
    existing_path, existing_name = _locate_physical_file(uploads_dir, meta, view_name)

    baseline = await _ensure_baseline_version(
        session, meta=meta, existing_path=existing_path, existing_name=existing_name
    )

    try:
        existing_content = existing_path.read_bytes()
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"Could not read existing file: {exc}"
        ) from exc
    existing_types = detect_column_types(existing_content, existing_name)
    incoming_types = detect_column_types(content, file.filename)
    diff = compare_schemas(existing_types, incoming_types)

    dependencies = await find_query_dependencies(
        session, tenant_id=context.tenant_id, view_name=view_name
    )

    incoming_checksum = checksum(content)
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
        "proposedRowCount": count_data_rows(content, file.filename),
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
        size_bytes=len(content),
        row_count=compatibility["proposedRowCount"],
        column_types=incoming_types or None,
        compatibility=compatibility,
        replaced_version_id=baseline.id,
    )
    session.add(staged)
    await session.flush()

    stage_dir = staging_dir(uploads_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)
    staged_path = stage_dir / f"{staged.id}_{sanitize_filename(file.filename)}"
    staged_path.write_bytes(content)
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
) -> None:
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
            filename=filename,
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

    new_original_format = filename.rsplit(".", 1)[-1].lower() if "." in filename else None
    new_display_name, _ = display_source(existing_name, new_original_format)
    meta.file_name = new_display_name
    meta.source_format = new_original_format
    meta.column_types = version.column_types or None

    version.status = STATUS_ACTIVE
    version.activated_at = datetime.now(UTC)
    version.error_message = None


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

    await _activate_content(
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
    activated_copy = archive_root / existing_name
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
        view_name=view_name,
        project_id=meta.project_id,
        title=f"Activated version {version.version_number} of {view_name}",
    )
    await session.commit()
    return {
        "status": "active",
        "viewName": view_name,
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
