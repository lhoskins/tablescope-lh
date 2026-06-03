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
from app.services.file_sources import compute_view_name, detect_column_types

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
    settings = get_settings()
    servlet_url = (
        f"{settings.teiid_servlet_url}/TeiidExcelImporterTest/upload"
    )

    resolved_vdb_type = vdb_type or "user"

    logger.info(
        "Forwarding upload to Teiid servlet: file=%s org_id=%s user_id=%s vdb_type=%s",
        file.filename,
        tenant.id,
        user.id,
        resolved_vdb_type,
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
                files={"file": (file.filename, content, file.content_type or "application/octet-stream")},
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
    base_name = file.filename.rsplit(".", 1)[0].replace(" ", "_")
    extension = file.filename.rsplit(".", 1)[-1].upper() if "." in file.filename else ""
    datasource_name = f"{base_name}_{extension}" if extension else base_name

    # Sync uploaded file to S3 if enabled
    settings_obj = get_settings()
    s3_location = None
    if settings_obj.s3_enabled:
        try:
            from app.services.s3_storage import S3StorageService
            s3_svc = S3StorageService()
            local_file_path = f"{settings_obj.customer_base_path}/{tenant.id}/{user.id}/uploads/{file.filename}"
            s3_key = s3_svc.get_s3_key_for_upload(tenant.id, user.id, file.filename)
            s3_location = s3_svc.upload_file(local_file_path, s3_key)
        except Exception as e:
            logger.warning("S3 upload sync failed (non-fatal): %s", e)

    # Detect per-column formatting types (currency/date/number) for item 6.
    column_types = detect_column_types(content, file.filename)

    # Validate the requested project (if any) belongs to this tenant.
    resolved_project_id: int | None = None
    if project_id is not None:
        project = await session.get(Project, project_id)
        if project is None or project.tenant_id != context.tenant_id:
            raise HTTPException(status_code=404, detail="Project not found")
        resolved_project_id = project_id

    # Upsert the file-source metadata row (project association, archive flag,
    # column types). Keyed by (tenant, owner, view_name).
    view_name = compute_view_name(file.filename)
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
                file_name=file.filename,
                vdb_type=resolved_vdb_type,
                column_types=column_types or None,
            )
        )
    else:
        existing.file_name = file.filename
        existing.vdb_type = resolved_vdb_type
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
        "path": f"/opt/wildfly/teiidfiles/customers/{tenant.id}/{user.id}/uploads/{file.filename}",
        "size": len(content),
        "datasource": datasource_name,
        "fileName": file.filename,
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
    uploads_dir = Path(settings.customer_base_path) / str(context.tenant_id) / str(user.id) / "uploads"

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
                datasources.append({
                    "fileName": f.name,
                    "viewName": view_name,
                    "size": f.stat().st_size,
                    "sourceType": extension.lower() or "file",
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

    # Remove the physical file (best-effort) and the metadata row.
    settings = get_settings()
    uploads_dir = (
        Path(settings.customer_base_path)
        / str(context.tenant_id)
        / str(context.user_id)
        / "uploads"
    )
    target = uploads_dir / meta.file_name
    try:
        if target.is_file():
            target.unlink()
    except OSError as exc:
        logger.warning("Failed to remove file %s: %s", target, exc)

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
    uploads_dir = (
        Path(settings.customer_base_path)
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
    servlet_url = f"{settings.teiid_servlet_url}/TeiidExcelImporterTest/upload"
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
