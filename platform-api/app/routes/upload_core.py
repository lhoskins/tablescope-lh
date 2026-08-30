"""File upload intake route (``POST /upload``).

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

Siblings: ``upload_datasources.py``, ``upload_replace.py``,
``upload_versions.py``.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.database import get_db
from app.models.file_source_meta import FileSourceMeta
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

    # Sanitize content and determine the real on-disk filename. Excel files keep
    # their .xlsx/.xlsm extension and are imported by the Teiid Excel translator;
    # JSON/XML/legacy .xls are flattened to .csv. The original extension is
    # remembered as source_format so the UI still shows e.g. "SalesJournal.xlsx".
    filename, content, original_format = prepare_upload_content(
        file.filename or "upload.csv", content
    )
    display_name, _ = display_source(filename, original_format)
    view_name = compute_view_name(filename)
    logger.info(
        "Upload prepared: incoming=%r physical=%r display=%r view=%r",
        file.filename,
        filename,
        display_name,
        view_name,
    )

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
                c.get("field") or c["name"]
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
        "datasource": view_name,
        "fileName": display_name,
        "viewName": view_name,
        "columnTypes": column_types,
        "projectId": resolved_project_id,
        "teiid": teiid_result,
        "s3_location": s3_location,
    }

