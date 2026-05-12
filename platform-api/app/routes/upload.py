"""File upload route.

Writes the uploaded file into the tenant/user folder on the shared volume and
enqueues a workflow task (see `app.tasks.workflows.process_upload`) to parse
it, generate DDL, and trigger a Teiid redeploy.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.user import User
from app.services.customer_folders import CustomerFolderError, CustomerFolderService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/upload", tags=["upload"])


@router.post("")
async def upload_file(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    if file.filename is None:
        raise HTTPException(status_code=400, detail="Filename is required")

    user = await session.get(User, context.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    from app.models.tenant import Tenant

    tenant = await session.get(Tenant, context.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    folders = CustomerFolderService()
    content = await file.read()
    try:
        target = folders.write_upload(
            tenant_slug=tenant.slug,
            user_external_id=user.external_id or str(user.id),
            filename=file.filename,
            content=content,
        )
    except CustomerFolderError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    from app.tasks.workflows import enqueue_process_upload

    await enqueue_process_upload(
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        path=str(target),
    )
    return {"path": str(target), "size": len(content)}
