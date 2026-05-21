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

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.database import get_db
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
    from app.models.tenant import Tenant

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

    return {
        "path": f"/opt/wildfly/teiidfiles/customers/{tenant.id}/{user.id}/uploads/{file.filename}",
        "size": len(content),
        "teiid": teiid_result,
    }
