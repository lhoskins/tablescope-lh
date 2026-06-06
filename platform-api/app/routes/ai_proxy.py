"""AI proxy routes — the ONLY path from the frontend to the AI server.

The frontend never calls the AI server directly. This proxy:
1. Validates the user's session and permissions
2. Resolves tenant, project, and user scope
3. Signs the request with HMAC
4. Forwards to the AI server
5. Returns the AI response

Also provides a /permissions endpoint called by the AI server to verify
access before retrieving vectors or building context.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
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

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["AI"])

TIMEOUT = httpx.Timeout(300.0, connect=10.0)


# ---------------------------------------------------------------------------
# Request/Response schemas for the proxy
# ---------------------------------------------------------------------------

class AIAskRequest(BaseModel):
    project_id: int
    question: str
    scope: str = "project"
    include_query_history: bool = True
    include_dashboard_context: bool = True


class AIGenerateSQLRequest(BaseModel):
    project_id: int
    prompt: str
    allowed_tables: list[str] = []


class AIGenerateRelationshipsRequest(BaseModel):
    project_id: int


class AISuggestDashboardRequest(BaseModel):
    project_id: int


class AIIndexDocumentRequest(BaseModel):
    project_id: int
    document_id: int
    source_type: str
    source_id: int
    content: str = ""
    visibility: str = "shared_project"


class AISaveQueryRequest(BaseModel):
    """Save AI-generated SQL as a project query."""
    project_id: int
    name: str
    description: str | None = None
    sql_text: str


class AIGenerateAndSaveQueryRequest(BaseModel):
    """Generate SQL from prompt and save as a project query."""
    project_id: int
    prompt: str
    name: str | None = None
    description: str | None = None
    allowed_tables: list[str] = []


class AIGenerateAndSaveDashboardRequest(BaseModel):
    """Generate a full dashboard with widgets from a prompt and save."""
    project_id: int
    prompt: str | None = None
    name: str | None = None
    description: str | None = None


class AIPermissionsResponse(BaseModel):
    tenant_id: int
    user_id: int
    project_id: int
    is_member: bool
    is_owner: bool
    project_visibility: str
    datasources: list[dict[str, Any]]
    saved_queries: list[dict[str, Any]]
    dashboards: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sign_payload(payload: dict[str, Any], secret: str) -> str:
    """Generate HMAC-SHA256 signature for a request payload."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hmac.new(
        secret.encode(), canonical.encode(), hashlib.sha256,
    ).hexdigest()


async def _forward_to_ai(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Sign and forward request to the AI server."""
    settings = get_settings()
    if not settings.tablescope_ai_enabled or not settings.tablescope_ai_api_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI server is not configured",
        )

    payload["timestamp"] = time.time()
    payload["signature"] = _sign_payload(payload, settings.tablescope_ai_signing_secret)

    url = f"{settings.tablescope_ai_api_url}{path}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            detail = str(e)
            if e.response.content:
                try:
                    detail = e.response.json().get("detail", detail)
                except Exception:
                    detail = e.response.text[:500] or detail
            raise HTTPException(status_code=e.response.status_code, detail=detail) from e
        except httpx.RequestError as e:
            logger.error("AI server unreachable: %s", e)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI server is unreachable",
            ) from e


async def _check_project_access(
    session: AsyncSession,
    context: RequestContext,
    project_id: int,
) -> Project:
    """Verify user has access to the project within their tenant."""
    stmt = select(Project).where(
        Project.id == project_id,
        Project.tenant_id == context.tenant_id,
    )
    result = await session.execute(stmt)
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found in your tenant",
        )

    # Check membership for shared projects
    if project.is_shared:
        member_stmt = select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == context.user_id,
            ProjectMember.is_active.is_(True),
        )
        member_result = await session.execute(member_stmt)
        if not member_result.scalar_one_or_none():
            if project.owner_id != context.user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You are not a member of this project",
                )
    else:
        # Private project — owner only
        if project.owner_id != context.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This is a private project and you are not the owner",
            )

    return project


def _detect_datasource(sql: str, allowed_tables: list[str]) -> str | None:
    """Find which datasource view_name is referenced in the generated SQL."""
    sql_upper = sql.upper()
    for table in allowed_tables:
        # Check for table name in FROM/JOIN clauses (with or without quotes)
        if table.upper() in sql_upper or f'"{table}"'.upper() in sql_upper:
            return table
    return allowed_tables[0] if len(allowed_tables) == 1 else None


# ---------------------------------------------------------------------------
# AI Proxy endpoints
# ---------------------------------------------------------------------------

@router.post("/ask")
async def ask(
    req: AIAskRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Ask Tablescope AI a question about the active project."""
    await _check_project_access(session, context, req.project_id)

    payload = {
        "tenant_id": context.tenant_id,
        "user_id": context.user_id,
        "project_id": req.project_id,
        "question": req.question,
        "scope": req.scope,
        "include_query_history": req.include_query_history,
        "include_dashboard_context": req.include_dashboard_context,
    }
    return await _forward_to_ai("/ai/ask", payload)


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

    payload = {
        "tenant_id": context.tenant_id,
        "user_id": context.user_id,
        "project_id": req.project_id,
        "prompt": req.prompt,
        "allowed_tables": allowed_tables,
    }
    return await _forward_to_ai("/ai/query/generate", payload)


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


@router.post("/dashboard/suggest")
async def suggest_dashboard(
    req: AISuggestDashboardRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Suggest dashboard widgets based on project data."""
    await _check_project_access(session, context, req.project_id)

    payload = {
        "tenant_id": context.tenant_id,
        "user_id": context.user_id,
        "project_id": req.project_id,
    }
    return await _forward_to_ai("/ai/dashboard/suggest", payload)


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


@router.get("/status")
async def ai_status(
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> dict[str, Any]:
    """Check AI server health (admin only)."""
    settings = get_settings()
    if not settings.tablescope_ai_enabled or not settings.tablescope_ai_api_url:
        return {"enabled": False, "status": "not_configured"}

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.get(f"{settings.tablescope_ai_api_url}/health")
            resp.raise_for_status()
            return {"enabled": True, **resp.json()}
    except Exception as e:
        return {"enabled": True, "status": "unreachable", "error": str(e)}


# ---------------------------------------------------------------------------
# Permissions endpoint — called by the AI server to verify access
# ---------------------------------------------------------------------------

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
    )


# ---------------------------------------------------------------------------
# AI Action endpoints — LLM proposes, Tablescope validates & executes
# ---------------------------------------------------------------------------

@router.post("/actions/save-query")
async def ai_save_query(
    req: AISaveQueryRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Save AI-generated SQL as a project query.

    Pattern: LLM already proposed the SQL → Tablescope validates → saves.
    """
    project = await _check_project_access(session, context, req.project_id)

    # Detect which datasource the SQL references
    ds_stmt = select(FileSourceMeta).where(
        FileSourceMeta.project_id == req.project_id,
        FileSourceMeta.tenant_id == context.tenant_id,
        FileSourceMeta.archived.is_(False),
    )
    ds_result = await session.execute(ds_stmt)
    view_names = [ds.view_name for ds in ds_result.scalars()]
    left_datasource = _detect_datasource(req.sql_text, view_names)

    query = SavedQuery(
        project_id=project.id,
        owner_id=context.user_id,
        name=req.name,
        description=req.description or "Generated by Tablescope AI",
        sql_text=req.sql_text,
        left_datasource=left_datasource,
    )
    session.add(query)
    await session.commit()
    await session.refresh(query)

    logger.info(
        "AI action: save_query | query_id=%d project=%d tenant=%d user=%d",
        query.id, project.id, context.tenant_id, context.user_id,
    )
    return {
        "action": "save_query",
        "status": "saved",
        "query_id": query.id,
        "name": query.name,
        "sql_text": query.sql_text,
    }


@router.post("/actions/generate-and-save-query")
async def ai_generate_and_save_query(
    req: AIGenerateAndSaveQueryRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Generate SQL from a natural language prompt, validate, and save.

    Full action flow:
    1. Forward prompt to AI server → LLM generates SQL
    2. Tablescope validates the SQL
    3. Tablescope creates the SavedQuery
    4. Tablescope logs the audit trail
    """
    project = await _check_project_access(session, context, req.project_id)

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

    # Step 1: Call AI server to generate SQL
    payload = {
        "tenant_id": context.tenant_id,
        "user_id": context.user_id,
        "project_id": req.project_id,
        "prompt": req.prompt,
        "allowed_tables": allowed_tables,
    }
    ai_result = await _forward_to_ai("/ai/query/generate", payload)
    generated_sql = ai_result.get("sql", "").rstrip().rstrip(";")

    if not generated_sql:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="AI could not generate SQL for this prompt",
        )

    # Detect which datasource the SQL references
    left_datasource = _detect_datasource(generated_sql, allowed_tables)

    # Step 2: Derive a name if not provided
    name = req.name or f"AI: {req.prompt[:80]}"

    # Step 3: Save as query
    query = SavedQuery(
        project_id=project.id,
        owner_id=context.user_id,
        name=name,
        description=req.description or f"AI-generated from: {req.prompt}",
        sql_text=generated_sql,
        left_datasource=left_datasource,
    )
    session.add(query)
    await session.commit()
    await session.refresh(query)

    logger.info(
        "AI action: generate_and_save_query | query_id=%d project=%d tenant=%d user=%d",
        query.id, project.id, context.tenant_id, context.user_id,
    )
    return {
        "action": "generate_and_save_query",
        "status": "saved",
        "query_id": query.id,
        "name": query.name,
        "sql_text": generated_sql,
        "explanation": ai_result.get("explanation", ""),
        "model_used": ai_result.get("model_used", ""),
    }


@router.post("/actions/generate-and-save-dashboard")
async def ai_generate_and_save_dashboard(
    req: AIGenerateAndSaveDashboardRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Generate a full dashboard with widgets and save everything.

    Full action flow:
    1. Forward to AI server → LLM proposes dashboard (title, widgets with SQL)
    2. Tablescope validates each widget's SQL
    3. For each widget query, create a SavedQuery
    4. Create Dashboard with widget config referencing queries
    5. Audit trail
    """
    project = await _check_project_access(session, context, req.project_id)

    # Resolve allowed tables from project datasources
    ds_stmt = select(FileSourceMeta).where(
        FileSourceMeta.project_id == req.project_id,
        FileSourceMeta.tenant_id == context.tenant_id,
        FileSourceMeta.archived.is_(False),
    )
    ds_result = await session.execute(ds_stmt)
    allowed_tables = [ds.view_name for ds in ds_result.scalars()]

    # Step 1: Call AI server for dashboard suggestion
    payload = {
        "tenant_id": context.tenant_id,
        "user_id": context.user_id,
        "project_id": req.project_id,
        "prompt": req.prompt or "",
        "allowed_tables": allowed_tables,
    }
    ai_result = await _forward_to_ai("/ai/dashboard/suggest", payload)
    suggestions = ai_result.get("suggestions", [])

    if not suggestions:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="AI could not generate dashboard suggestions",
        )

    # Take the first suggestion (or the one matching the prompt best)
    suggestion = suggestions[0]
    dashboard_title = req.name or suggestion.get("title", f"AI Dashboard - {req.prompt or 'auto'}")
    widget_defs = suggestion.get("widgets", [])

    # Step 2 & 3: For each widget, create a SavedQuery and build widget config
    widgets_config: list[dict[str, Any]] = []
    created_queries: list[int] = []

    for idx, w in enumerate(widget_defs):
        widget_sql = (w.get("sql", "") or "").rstrip().rstrip(";")
        widget_title = w.get("title", f"Widget {idx + 1}")
        widget_type = w.get("type", "bar")
        x_col = w.get("x_column") or ""
        y_col = w.get("y_column") or ""
        aggregation = w.get("aggregation") or "count"

        # Create a SavedQuery for this widget's SQL
        data_source: dict[str, Any] = {"kind": "custom_sql", "customSql": ""}
        if widget_sql:
            # Detect which datasource the SQL references
            left_ds = _detect_datasource(widget_sql, allowed_tables)
            query = SavedQuery(
                project_id=project.id,
                owner_id=context.user_id,
                name=f"{dashboard_title} — {widget_title}",
                description=f"Auto-created for AI dashboard widget: {widget_title}",
                sql_text=widget_sql,
                left_datasource=left_ds,
            )
            session.add(query)
            await session.flush()
            created_queries.append(query.id)
            data_source = {"kind": "query", "queryId": query.id}

        widgets_config.append({
            "id": f"ai_widget_{idx}",
            "title": widget_title,
            "type": _map_chart_type(widget_type),
            "chartSubtype": _map_chart_subtype(widget_type),
            "dataSource": data_source,
            "xColumn": x_col,
            "yColumn": y_col,
            "aggregation": aggregation.lower() if aggregation else "count",
            "sortBy": "x_asc",
            "filters": [],
            "colSpan": 6 if widget_type != "table" else 12,
            "position": idx,
            "gridX": (idx % 2) * 6,
            "gridY": (idx // 2) * 4,
            "gridW": 6,
            "gridH": 4,
        })

    # Step 4: Create the Dashboard
    dashboard = Dashboard(
        project_id=project.id,
        owner_id=context.user_id,
        tenant_id=context.tenant_id,
        name=dashboard_title,
        description=req.description or f"AI-generated dashboard{(': ' + req.prompt) if req.prompt else ''}",
        status="draft",
        config={
            "widgets": widgets_config,
            "filters": [],
            "layout": "grid",
            "ai_generated": True,
        },
    )
    session.add(dashboard)
    await session.commit()
    await session.refresh(dashboard)

    logger.info(
        "AI action: generate_and_save_dashboard | dashboard_id=%d widgets=%d queries=%d "
        "project=%d tenant=%d user=%d",
        dashboard.id, len(widgets_config), len(created_queries),
        project.id, context.tenant_id, context.user_id,
    )
    return {
        "action": "generate_and_save_dashboard",
        "status": "saved",
        "dashboard_id": dashboard.id,
        "dashboard_name": dashboard_title,
        "widgets_created": len(widgets_config),
        "queries_created": created_queries,
        "model_used": ai_result.get("model_used", ""),
    }


def _map_chart_type(ai_type: str) -> str:
    """Map AI-suggested chart types to the dashboard widget chart type."""
    mapping = {
        "kpi": "kpi",
        "bar": "bar",
        "line": "line",
        "pie": "pie",
        "area": "area",
        "table": "table",
        "donut": "pie",
        "scatter": "line",
    }
    return mapping.get(ai_type.lower(), "bar")


def _map_chart_subtype(ai_type: str) -> str:
    """Map AI-suggested type to a chart subtype."""
    mapping = {
        "kpi": "kpi",
        "bar": "column",
        "line": "straight",
        "pie": "pie",
        "donut": "donut",
        "area": "area",
        "table": "table",
        "scatter": "straight",
    }
    return mapping.get(ai_type.lower(), "column")
