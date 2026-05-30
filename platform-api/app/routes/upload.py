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
from app.models.tenant import Tenant
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/upload", tags=["upload"])


@router.post("")
async def upload_file(
    file: UploadFile = File(...),
    vdb_type: str | None = Form(None),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    """Forward file to the Teiid servlet for import and metadata insertion."""
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

    return {
        "path": f"/opt/wildfly/teiidfiles/customers/{tenant.id}/{user.id}/uploads/{file.filename}",
        "size": len(content),
        "datasource": datasource_name,
        "fileName": file.filename,
        "teiid": teiid_result,
        "s3_location": s3_location,
    }


@router.get("/datasources")
async def list_datasources(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> list[dict]:
    """List uploaded datasources for the current user by scanning their uploads directory."""
    user = await session.get(User, context.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    settings = get_settings()
    uploads_dir = Path(settings.customer_base_path) / str(context.tenant_id) / str(user.id) / "uploads"

    datasources: list[dict] = []
    if uploads_dir.is_dir():
        for f in sorted(uploads_dir.iterdir()):
            if f.is_file() and not f.name.startswith("."):
                base_name = f.stem.replace(" ", "_")
                extension = f.suffix.lstrip(".").upper()
                view_name = f"{base_name}_{extension}" if extension else base_name
                datasources.append({
                    "fileName": f.name,
                    "viewName": view_name,
                    "size": f.stat().st_size,
                    "sourceType": extension.lower() or "file",
                    "dbType": None,
                })

    # Append the user's database-backed data sources (not tied to a project).
    db_sources = (
        await session.scalars(
            select(DatabaseDataSource).where(
                DatabaseDataSource.tenant_id == context.tenant_id,
                DatabaseDataSource.created_by == user.id,
                DatabaseDataSource.project_id.is_(None),
                DatabaseDataSource.status == "active",
            )
        )
    ).all()
    for ds in db_sources:
        datasources.append({
            "fileName": ds.display_name,
            "viewName": ds.teiid_view_name,
            "size": None,
            "sourceType": "database_table",
            "dbType": ds.db_type,
            "id": ds.id,
        })

    return datasources
