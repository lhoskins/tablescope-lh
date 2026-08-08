"""AI-server-facing endpoints: service status and permission resolution."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.database import get_db
from app.models.dashboard import Dashboard
from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project, ProjectMember
from app.models.saved_query import SavedQuery
from app.services.analytical_method_engine.config import get_engine_mode
from app.services.analytical_method_engine.method_registry import catalog_status as analytical_catalog_status

from .ai_proxy_schemas import (
    AIPermissionsResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/status")
async def ai_status(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> dict[str, Any]:
    """Check AI server health (admin only).

    Also reports the resolved Analytical Method Engine mode and whether an
    ``approved+active`` analytical catalog version exists — when it does not,
    hybrid analysis silently produces nothing, so this is surfaced here to make
    that state diagnosable.
    """
    settings = get_settings()
    try:
        catalog = await analytical_catalog_status(session)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Analytical catalog status check failed: %s", exc)
        catalog = {"active": False, "version_id": None, "error": str(exc)}
    analytical = {
        "engineMode": get_engine_mode().value,
        "catalog": catalog,
    }
    if not settings.tablescope_ai_enabled or not settings.tablescope_ai_api_url:
        return {
            "enabled": False,
            "status": "not_configured",
            "analytical": analytical,
        }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.get(f"{settings.tablescope_ai_api_url}/health")
            resp.raise_for_status()
            return {"enabled": True, "analytical": analytical, **resp.json()}
    except Exception as e:
        return {
            "enabled": True,
            "status": "unreachable",
            "error": str(e),
            "analytical": analytical,
        }


@router.get("/permissions", response_model=AIPermissionsResponse)
async def check_permissions(
    tenant_id: int,
    user_id: int,
    project_id: int,
    session: AsyncSession = Depends(get_db),
) -> AIPermissionsResponse:
    """Called by the AI server to verify user permissions before building context.

    Returns tenant/project membership info plus available datasources/queries.
    This endpoint is NOT exposed to the frontend — only reachable from the
    AI server's private network.
    """
    # Verify project exists in tenant
    stmt = select(Project).where(
        Project.id == project_id,
        Project.tenant_id == tenant_id,
    )
    result = await session.execute(stmt)
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    # Check membership
    is_owner = project.owner_id == user_id
    is_member = is_owner
    if not is_member:
        member_stmt = select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
            ProjectMember.is_active.is_(True),
        )
        member_result = await session.execute(member_stmt)
        is_member = member_result.scalar_one_or_none() is not None

    # Fetch datasources (file_source_meta rows for this project)
    ds_stmt = select(FileSourceMeta).where(
        FileSourceMeta.project_id == project_id,
        FileSourceMeta.tenant_id == tenant_id,
        FileSourceMeta.archived.is_(False),
    )
    ds_result = await session.execute(ds_stmt)
    datasources: list[dict[str, Any]] = []
    for ds in ds_result.scalars():
        ds_entry: dict[str, Any] = {
            "id": ds.id,
            "view_name": ds.view_name,
            "file_name": ds.file_name,
            "name": ds.view_name,
        }
        if ds.column_types:
            ds_entry["columns"] = [
                {"name": c.get("name", ""), "type": c.get("type", "string")}
                for c in ds.column_types
            ]
        datasources.append(ds_entry)

    # Fetch saved queries
    query_stmt = select(SavedQuery).where(SavedQuery.project_id == project_id)
    query_result = await session.execute(query_stmt)
    saved_queries = [
        {"id": q.id, "name": q.name, "sql_text": q.sql_text}
        for q in query_result.scalars()
    ]

    # Fetch dashboards
    dash_stmt = select(Dashboard).where(Dashboard.project_id == project_id)
    dash_result = await session.execute(dash_stmt)
    dashboards = [
        {"id": d.id, "name": d.name}
        for d in dash_result.scalars()
    ]

    # Fetch query scopes for this project
    from app.models.query_scope import QueryScope
    scope_stmt = select(QueryScope).where(
        QueryScope.project_id == project_id,
        QueryScope.tenant_id == tenant_id,
    )
    scope_result = await session.execute(scope_stmt)
    query_scopes = [
        {
            "id": s.id,
            "query_id": s.query_id,
            "source_field": s.source_field,
            "target_query_id": s.target_query_id,
            "target_field": s.target_field,
            "project_id": s.project_id,
        }
        for s in scope_result.scalars()
    ]

    # Fetch accepted tags for this project
    from app.models.ai_asset_metadata import AIAssetKPI, AIAssetTag
    accepted_tags_stmt = select(AIAssetTag).where(
        AIAssetTag.tenant_id == tenant_id,
        AIAssetTag.project_id == project_id,
    )
    at_result = await session.execute(accepted_tags_stmt)
    accepted_tags = [t.to_dict() for t in at_result.scalars()]

    # Fetch accepted KPIs for this project
    accepted_kpis_stmt = select(AIAssetKPI).where(
        AIAssetKPI.tenant_id == tenant_id,
        AIAssetKPI.project_id == project_id,
    )
    ak_result = await session.execute(accepted_kpis_stmt)
    accepted_kpis = [k.to_dict() for k in ak_result.scalars()]

    # Fetch enabled reference tags and KPIs for the tenant
    from app.services.reference_catalog_service import (
        get_reference_kpis,
        get_reference_tags,
    )
    ref_tags = await get_reference_tags(session, tenant_id)
    ref_kpis = await get_reference_kpis(session, tenant_id)

    # Fetch project documents (unstructured assets with AI profiles)
    from app.models.project_asset import ProjectAsset
    doc_stmt = select(ProjectAsset).where(
        ProjectAsset.project_id == project_id,
        ProjectAsset.tenant_id == tenant_id,
        ProjectAsset.status != "deleted",
    )
    doc_result = await session.execute(doc_stmt)
    documents: list[dict[str, Any]] = []
    for doc in doc_result.scalars():
        doc_entry: dict[str, Any] = {
            "id": doc.id,
            "title": doc.title or doc.filename,
            "filename": doc.filename,
            "asset_type": doc.asset_type,
            "ai_summary": doc.ai_summary or "",
            "ai_status": doc.ai_status or "",
        }
        if doc.ai_metadata:
            doc_entry["tags"] = [
                t.get("tag_key", t.get("display_name", ""))
                for t in doc.ai_metadata.get("tags", [])
            ]
            doc_entry["entities"] = doc.ai_metadata.get("entities", [])
            doc_entry["recommended_kpis"] = [
                k.get("kpi_key", k.get("display_name", ""))
                for k in doc.ai_metadata.get("recommended_kpis", [])
            ]
        documents.append(doc_entry)

    # Fetch project graph nodes and edges (active only)
    from app.models.ai_project_graph import AIProjectGraphEdge, AIProjectGraphNode
    from app.services.project_graph_service import get_family_members
    node_stmt = select(AIProjectGraphNode).where(
        AIProjectGraphNode.project_id == project_id,
        AIProjectGraphNode.tenant_id == tenant_id,
        AIProjectGraphNode.is_active.is_(True),
    )
    node_result = await session.execute(node_stmt)
    graph_nodes: list[dict[str, Any]] = [
        {"id": n.id, "node_type": n.node_type, "name": n.name, "label": n.name}
        for n in node_result.scalars()
    ]

    edge_stmt = select(AIProjectGraphEdge).where(
        AIProjectGraphEdge.project_id == project_id,
        AIProjectGraphEdge.tenant_id == tenant_id,
        AIProjectGraphEdge.is_active.is_(True),
    )
    edge_result = await session.execute(edge_stmt)
    graph_edges = [
        {
            "id": e.id,
            "from_node_id": e.from_node_id,
            "to_node_id": e.to_node_id,
            "edge_type": e.edge_type,
            "confidence": e.confidence,
        }
        for e in edge_result.scalars()
    ]

    # Document families with rolled-up members (family-aware retrieval).
    document_families: list[dict[str, Any]] = []
    for fam in graph_nodes:
        if fam["node_type"] != "document_family":
            continue
        fam_id = int(fam["id"])
        members = await get_family_members(session, tenant_id, project_id, fam_id)
        fam_props_stmt = select(AIProjectGraphNode).where(AIProjectGraphNode.id == fam_id)
        fam_node = (await session.execute(fam_props_stmt)).scalar_one_or_none()
        props = fam_node.properties if (fam_node and isinstance(fam_node.properties, dict)) else {}
        document_families.append({
            "family_node_id": fam_id,
            "family_name": fam["name"],
            "family_type": props.get("family_type", ""),
            "summary": props.get("family_summary", props.get("description", "")),
            "members": {
                "documents": [d["name"] for d in members["documents"]],
                "datasources": [d["name"] for d in members["datasources"]],
                "queries": [d["name"] for d in members["queries"]],
                "dashboards": [d["name"] for d in members["dashboards"]],
                "kpis": [d["name"] for d in members["kpis"]],
            },
        })

    return AIPermissionsResponse(
        tenant_id=tenant_id,
        user_id=user_id,
        project_id=project_id,
        is_member=is_member,
        is_owner=is_owner,
        project_visibility="shared" if project.is_shared else "private",
        datasources=datasources,
        saved_queries=saved_queries,
        dashboards=dashboards,
        query_scopes=query_scopes,
        accepted_tags=accepted_tags,
        accepted_kpis=accepted_kpis,
        enabled_reference_tags=ref_tags,
        enabled_reference_kpis=ref_kpis,
        documents=documents,
        graph_nodes=graph_nodes,
        graph_edges=graph_edges,
        document_families=document_families,
    )
