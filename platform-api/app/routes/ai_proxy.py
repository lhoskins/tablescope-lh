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


class AICreateScopeRequest(BaseModel):
    """Create a single scope from an AI suggestion."""
    sourceTable: str
    sourceColumn: str
    targetTable: str
    targetColumn: str


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
    query_scopes: list[dict[str, Any]] = []


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


def _is_numeric_column(name: str) -> bool:
    """Return True if a column name looks like a numeric/aggregate value.

    Numeric columns (Revenue, Amount, Cost, Price, Quantity, Count, Sum, Total,
    etc.) should NOT be used for drill-down scopes — only identifier/name columns
    (ProductName, CategoryName, CustomerID, OrderID, etc.) are meaningful for
    drill-down relationships.
    """
    numeric_keywords = {
        "revenue", "amount", "cost", "price", "quantity", "count", "sum",
        "total", "average", "avg", "min", "max", "profit", "discount",
        "sales", "units", "weight", "balance", "fee", "rate", "percent",
        "percentage", "margin", "tax", "freight", "subtotal",
    }
    lower = name.lower()
    for kw in numeric_keywords:
        if kw in lower:
            return True
    return False


def _is_summarized_query(sql: str) -> bool:
    """Return True if the SQL is an aggregated/summarized query.

    A query is considered summarized if it contains GROUP BY or aggregate
    functions (SUM, COUNT, AVG, MIN, MAX). Summarized queries drill DOWN
    into detailed queries, not the other way around.
    """
    import re
    upper = sql.upper()
    if re.search(r"\bGROUP\s+BY\b", upper):
        return True
    if re.search(r"\b(SUM|COUNT|AVG|MIN|MAX)\s*\(", upper):
        return True
    return False


def _extract_select_columns(sql: str) -> list[str]:
    """Extract column names/aliases from a SQL SELECT clause using regex.

    Returns the alias (AS name) or the raw column reference for each item.
    """
    import re

    cols: list[str] = []

    # Extract text between SELECT and FROM (first occurrence, skip nested subqueries)
    m = re.search(r"\bSELECT\s+(.*?)\s+FROM\s+", sql, re.IGNORECASE | re.DOTALL)
    if not m:
        return cols
    raw = m.group(1)

    # Split by commas (respecting parentheses)
    items: list[str] = []
    current: list[str] = []
    paren_depth = 0
    for ch in raw:
        if ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth -= 1
        if ch == "," and paren_depth == 0:
            items.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        items.append("".join(current).strip())

    for item in items:
        if not item or item == "*":
            continue
        # Check for AS alias
        alias_match = re.search(r"\bAS\s+[\"']?(\w+)[\"']?\s*$", item, re.IGNORECASE)
        if alias_match:
            cols.append(alias_match.group(1))
            continue
        # No alias — take the last identifier (column name after any dot)
        # Strip surrounding quotes
        ident_match = re.search(r'[\".]?(\w+)[\"]*\s*$', item.rstrip())
        if ident_match:
            cols.append(ident_match.group(1))
    return cols


async def _ai_analyze_and_create_scopes(
    *,
    session: AsyncSession,
    context: RequestContext,
    project_id: int,
) -> dict[str, Any]:
    """Send queries to AI server for scope analysis and create QueryScope records.

    The AI determines which columns are meaningful for drill-down and the
    correct direction (summarized → detailed). No hardcoded rules.
    """
    from app.models.query_scope import QueryScope

    # Get all saved queries for this project
    queries_result = await session.scalars(
        select(SavedQuery).where(SavedQuery.project_id == project_id)
    )
    queries = list(queries_result)

    if not queries:
        return {"relationships": [], "scopes_created": 0, "status": "ok"}

    # Only send queries that have SQL — include extracted columns for clarity
    query_infos = []
    query_names: dict[int, str] = {}
    for q in queries:
        query_names[q.id] = q.name
        if q.sql_text:
            cols = _extract_select_columns(q.sql_text)
            query_infos.append({
                "id": q.id,
                "name": q.name,
                "sql": q.sql_text,
                "columns": cols,
            })

    if not query_infos:
        return {"relationships": [], "scopes_created": 0, "status": "ok"}

    # Build a prompt describing the queries with their exact columns
    query_descriptions = "\n\n".join(
        f"Query ID={q['id']}, Name=\"{q['name']}\"\n"
        f"  SELECT columns: {q['columns']}\n"
        f"  SQL: {q['sql']}"
        for q in query_infos
    )
    scope_prompt = (
        f"Analyze these {len(query_infos)} saved SQL queries and find drill-down "
        f"scope relationships.\n\n"
        f"QUERIES:\n{query_descriptions}\n\n"
        "TASK: Find pairs where clicking a cell in the SOURCE query should filter "
        "the TARGET query by that value.\n\n"
        "RULES:\n"
        "1. Only use identifier/name columns (ProductName, CategoryName, CustomerID, "
        "OrderID) — NEVER numeric/aggregate columns (Revenue, Amount, Total, Count, "
        "Price, Quantity)\n"
        "2. Direction: summarized (GROUP BY/SUM/COUNT) → detailed (no aggregation). "
        "Source = aggregated query, Target = raw/detail query.\n"
        "3. CRITICAL: source_field and target_field MUST be the EXACT same column "
        "name that appears in both queries' SELECT columns list above. "
        "CategoryName and CategoryID are DIFFERENT columns — do NOT match them. "
        "Only match columns with the EXACT SAME NAME in both queries.\n"
        "4. One scope per query-pair per column — no duplicates, no reverse.\n"
        "5. Both queries must have the EXACT column name in their SELECT columns list.\n\n"
        "Return ONLY a JSON array: [{\"source_query_id\": int, "
        "\"source_query_name\": str, \"source_field\": str, "
        "\"target_query_id\": int, \"target_query_name\": str, "
        "\"target_field\": str, \"confidence\": float, \"reason\": str}]"
    )

    payload = {
        "tenant_id": context.tenant_id,
        "user_id": context.user_id,
        "project_id": project_id,
        "question": scope_prompt,
        "scope": "project",
        "include_query_history": False,
        "include_dashboard_context": False,
    }
    ai_response = await _forward_to_ai("/ai/ask", payload)

    # Parse scope suggestions from the AI answer
    import json as _json
    raw_answer = ai_response.get("answer", "")
    scopes_list: list[dict[str, Any]] = []
    try:
        json_text = raw_answer.strip()
        if json_text.startswith("```"):
            json_text = json_text.split("```")[1]
            if json_text.startswith("json"):
                json_text = json_text[4:]
        parsed = _json.loads(json_text)
        if isinstance(parsed, list):
            scopes_list = parsed
    except (_json.JSONDecodeError, IndexError, ValueError):
        pass

    if not scopes_list:
        return {"relationships": [], "scopes_created": 0, "status": "ok"}

    # Build column map for validation: query_id -> set of column names (lowercase)
    # This catches AI hallucinations where it suggests fields that don't exist
    query_col_map: dict[int, set[str]] = {}
    for q in queries:
        if q.sql_text:
            cols = _extract_select_columns(q.sql_text)
            query_col_map[q.id] = {c.lower() for c in cols}
        else:
            query_col_map[q.id] = set()

    # Find existing scopes to avoid duplicates
    existing_scopes = await session.scalars(
        select(QueryScope).where(
            QueryScope.project_id == project_id,
            QueryScope.tenant_id == context.tenant_id,
        )
    )
    existing_keys = {
        (s.query_id, s.source_field, s.target_query_id, s.target_field)
        for s in existing_scopes
    }

    # Valid query IDs in this project
    valid_ids = {q.id for q in queries}

    relationships: list[dict[str, Any]] = []
    scopes_created = 0
    for suggestion in scopes_list:
        src_qid = suggestion.get("source_query_id")
        tgt_qid = suggestion.get("target_query_id")
        src_field = suggestion.get("source_field", "")
        tgt_field = suggestion.get("target_field", "")

        # Validate that IDs belong to this project
        if src_qid not in valid_ids or tgt_qid not in valid_ids:
            continue
        if not src_field or not tgt_field:
            continue

        # Validate fields actually exist in the queries' SELECT clauses
        src_cols = query_col_map.get(src_qid, set())
        tgt_cols = query_col_map.get(tgt_qid, set())
        if src_field.lower() not in src_cols or tgt_field.lower() not in tgt_cols:
            continue

        key = (src_qid, src_field, tgt_qid, tgt_field)
        if key in existing_keys:
            relationships.append({
                "left_table": suggestion.get("source_query_name", query_names.get(src_qid, "")),
                "left_column": src_field,
                "right_table": suggestion.get("target_query_name", query_names.get(tgt_qid, "")),
                "right_column": tgt_field,
                "source_query_id": src_qid,
                "target_query_id": tgt_qid,
                "confidence": suggestion.get("confidence", 1.0),
                "reason": suggestion.get("reason", ""),
                "scope_exists": True,
            })
            continue

        scope = QueryScope(
            tenant_id=context.tenant_id,
            project_id=project_id,
            query_id=src_qid,
            source_field=src_field,
            target_query_id=tgt_qid,
            target_field=tgt_field,
            created_by=context.user_id,
        )
        session.add(scope)
        existing_keys.add(key)
        scopes_created += 1

        relationships.append({
            "left_table": suggestion.get("source_query_name", query_names.get(src_qid, "")),
            "left_column": src_field,
            "right_table": suggestion.get("target_query_name", query_names.get(tgt_qid, "")),
            "right_column": tgt_field,
            "source_query_id": src_qid,
            "target_query_id": tgt_qid,
            "confidence": suggestion.get("confidence", 1.0),
            "reason": suggestion.get("reason", ""),
            "scope_exists": True,
        })

    if scopes_created > 0:
        await session.commit()

    return {
        "relationships": relationships,
        "scopes_created": scopes_created,
        "status": "ok",
    }


@router.post("/project/scope-map/generate")
async def generate_scope_map(
    req: AIGenerateRelationshipsRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Generate query-based scope map using AI analysis.

    Sends all saved queries to the AI server which determines:
    1. Which columns are meaningful for drill-down (not aggregates)
    2. The correct direction (summarized → detailed)
    Auto-creates QueryScope records from AI suggestions.
    """
    await _check_project_access(session, context, req.project_id)
    return await _ai_analyze_and_create_scopes(
        session=session, context=context, project_id=req.project_id
    )


@router.post("/project/scope-map/auto-create")
async def auto_create_scopes_from_queries(
    req: AIGenerateRelationshipsRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Auto-create QueryScope records using AI analysis.

    When scoping is toggled ON, this endpoint sends all saved queries to
    the AI server which determines meaningful drill-down scopes and their
    direction (summarized → detailed).
    """
    await _check_project_access(session, context, req.project_id)
    result = await _ai_analyze_and_create_scopes(
        session=session, context=context, project_id=req.project_id
    )
    return {
        "scopes_created": result["scopes_created"],
        "total_queries": len(result.get("relationships", [])),
        "message": f"Created {result['scopes_created']} scope(s) via AI analysis",
    }


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
