"""SQL and relationship generation proxy endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.file_source_meta import FileSourceMeta
from app.services.teiid_sql import rebuild_group_by_from_select

from .ai_proxy_schemas import (
    AIGenerateRelationshipsRequest,
    AIGenerateSQLRequest,
)
from .ai_proxy_shared import (
    _build_source_catalog,
    _check_project_access,
    _forward_to_ai,
    _kg_context,
)

router = APIRouter()

@router.post("/query/generate")
async def generate_sql(
    req: AIGenerateSQLRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Generate SQL from a natural language prompt."""
    await _check_project_access(session, context, req.project_id)

    # Resolve allowed tables from project datasources if not provided
    allowed_tables = req.allowed_tables
    if not allowed_tables:
        ds_stmt = select(FileSourceMeta).where(
            FileSourceMeta.project_id == req.project_id,
            FileSourceMeta.tenant_id == context.tenant_id,
            FileSourceMeta.archived.is_(False),
        )
        ds_result = await session.execute(ds_stmt)
        allowed_tables = [ds.view_name for ds in ds_result.scalars()]

    source_catalog = await _build_source_catalog(
        session, tenant_id=context.tenant_id, project_id=req.project_id
    )

    payload = {
        "tenant_id": context.tenant_id,
        "user_id": context.user_id,
        "project_id": req.project_id,
        "prompt": req.prompt,
        "allowed_tables": allowed_tables,
        "source_catalog": source_catalog,
        "preferred_sources": [],
        "relevant_columns": [],
        # All query AI generation includes Knowledge Graph context so SQL targets
        # the risks/gaps/KPIs the graph surfaces (never Reference Library docs).
        "knowledge_graph_context": await _kg_context(
            session, context, req.project_id,
        ),
    }
    result = await _forward_to_ai("/ai/query/generate", payload)
    if isinstance(result, dict) and isinstance(result.get("sql"), str):
        result["sql"] = rebuild_group_by_from_select(result["sql"])
    return result


@router.post("/project/relationships/generate")
async def generate_relationships(
    req: AIGenerateRelationshipsRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Generate suggested relationships between project tables."""
    await _check_project_access(session, context, req.project_id)

    payload = {
        "tenant_id": context.tenant_id,
        "user_id": context.user_id,
        "project_id": req.project_id,
    }
    return await _forward_to_ai("/ai/project/relationships/generate", payload)
