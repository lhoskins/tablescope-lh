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
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.database import get_db
from app.models.database_data_source import DatabaseDataSource
from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project
from app.models.tenant import Tenant
from app.models.user import User
from app.services.file_sources import (
    compute_view_name,
    convert_to_csv_if_needed,
    detect_column_types,
    display_source,
    sanitize_csv_content,
    sanitize_filename,
    sanitize_xlsx_content,
)
from app.services.tenant_teiid_resolver import TenantTeiidResolver

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

    # Build the datasource name from the filename (matches servlet convention)
    base_name = filename.rsplit(".", 1)[0].replace(" ", "_")
    extension = filename.rsplit(".", 1)[-1].upper() if "." in filename else ""
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
    view_name = compute_view_name(filename)
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
                file_name=filename,
                vdb_type=resolved_vdb_type,
                source_format=original_format,
                column_types=column_types or None,
            )
        )
    else:
        existing.file_name = filename
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

    return {
        "path": f"/opt/wildfly/teiidfiles/customers/{tenant.id}/{user.id}/uploads/{filename}",
        "size": len(content),
        "datasource": datasource_name,
        "fileName": filename,
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
    from app.routes.database_sources import find_query_dependencies

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

    # Resolve the existing physical file backing this view.
    existing_path: Path | None = None
    existing_name: str | None = None
    if uploads_dir.is_dir():
        for f in uploads_dir.iterdir():
            if f.is_file() and compute_view_name(f.name) == view_name:
                existing_path = f
                existing_name = f.name
                break
    if existing_path is None or existing_name is None:
        raise HTTPException(status_code=404, detail="Data source not found")

    # 1) Same-name check.
    if file.filename != existing_name:
        raise HTTPException(
            status_code=409,
            detail=(
                f'File name mismatch: expected "{existing_name}", '
                f'got "{file.filename}". Replacement must use the same file name.'
            ),
        )

    content = await file.read()

    # 2) Column compatibility check: incoming must contain all existing columns.
    try:
        existing_content = existing_path.read_bytes()
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"Could not read existing file: {exc}"
        ) from exc
    existing_cols = {
        c["field"] for c in detect_column_types(existing_content, existing_name)
    }
    incoming_types = detect_column_types(content, file.filename)
    incoming_cols = {c["field"] for c in incoming_types}
    missing = existing_cols - incoming_cols
    if missing:
        raise HTTPException(
            status_code=409,
            detail=(
                "Replacement file is missing existing column(s): "
                + ", ".join(sorted(missing))
            ),
        )

    # 3) Re-import the new file through the Teiid servlet (overwrites the view).
    meta = await session.scalar(
        select(FileSourceMeta).where(
            FileSourceMeta.tenant_id == context.tenant_id,
            FileSourceMeta.owner_id == user.id,
            FileSourceMeta.view_name == view_name,
        )
    )
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

    # 4) Update metadata column types (preserve project association/archive).
    if meta is None:
        meta = FileSourceMeta(
            tenant_id=context.tenant_id,
            owner_id=user.id,
            view_name=view_name,
            file_name=file.filename,
        )
        session.add(meta)
    meta.column_types = incoming_types or None
    await session.commit()

    added = sorted(incoming_cols - existing_cols)
    return {
        "status": "replaced",
        "view_name": view_name,
        "fileName": file.filename,
        "addedColumns": added,
        "columnTypes": incoming_types,
    }
