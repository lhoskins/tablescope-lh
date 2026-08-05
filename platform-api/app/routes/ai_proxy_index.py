"""Document indexing proxy endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db

from .ai_proxy_schemas import (
    AIIndexDocumentRequest,
)
from .ai_proxy_shared import (
    _check_project_access,
    _forward_to_ai,
)

router = APIRouter()

@router.post("/index/document")
async def index_document(
    req: AIIndexDocumentRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Index a project document into the AI vector store."""
    await _check_project_access(session, context, req.project_id)

    payload = {
        "tenant_id": context.tenant_id,
        "user_id": context.user_id,
        "project_id": req.project_id,
        "document_id": req.document_id,
        "source_type": req.source_type,
        "source_id": req.source_id,
        "content": req.content,
        "visibility": req.visibility,
    }
    return await _forward_to_ai("/ai/index/document", payload)
