"""Dashboard suggestion proxy endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.file_source_meta import FileSourceMeta

from .ai_proxy_schemas import (
    AISuggestDashboardRequest,
)
from .ai_proxy_shared import (
    _check_project_access,
    _forward_to_ai,
    _kg_context,
)

router = APIRouter()

@router.post("/dashboard/suggest")
async def suggest_dashboard(
    req: AISuggestDashboardRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Suggest dashboard widgets based on project data."""
    await _check_project_access(session, context, req.project_id)

    ds_stmt = select(FileSourceMeta).where(
        FileSourceMeta.project_id == req.project_id,
        FileSourceMeta.tenant_id == context.tenant_id,
        FileSourceMeta.archived.is_(False),
    )
    ds_result = await session.execute(ds_stmt)
    allowed_tables = [ds.view_name for ds in ds_result.scalars()]

    payload = {
        "tenant_id": context.tenant_id,
        "user_id": context.user_id,
        "project_id": req.project_id,
        "prompt": "",
        "allowed_tables": allowed_tables,
        # Knowledge Graph context steers suggestions toward validated
        # risks/gaps/measured KPIs and governing documents.
        "knowledge_graph_context": await _kg_context(
            session, context, req.project_id,
        ),
    }
    return await _forward_to_ai("/ai/dashboard/suggest", payload)
