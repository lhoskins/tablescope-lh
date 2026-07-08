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

import asyncio
import difflib
import hashlib
import hmac
import json
import logging
import re
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.database import get_db
from app.models.ai_conversation import AiConversation, AiConversationMessage
from app.models.dashboard import Dashboard
from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project, ProjectMember
from app.models.query_scope import QueryScope
from app.models.saved_query import SavedQuery
from app.services.auto_scope import _get_or_create_ai_scope_set
from app.services.knowledge_graph_ai_context import (
    collect_knowledge_graph_ai_context,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["AI"])

TIMEOUT = httpx.Timeout(300.0, connect=10.0)

# Bounded window of prior conversation turns forwarded to the AI server so
# follow-up questions resolve against recent context without unbounded prompts.
CONVERSATION_HISTORY_LIMIT = 20

# Row cap for a data answer rendered inline in the AI Assistant chat.
CHAT_ANSWER_MAX_ROWS = 100


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


class AICardContext(BaseModel):
    """Source context carried from a Business/Project Insight card.

    Lets the Project Semantic Source Resolver prefer the exact authorized
    source a card's finding was grounded in, instead of re-inferring it from
    the plain sentence.
    """
    insight_type: str | None = None
    source_tables: list[str] = Field(default_factory=list)
    source_columns: list[str] = Field(default_factory=list)
    metric: str | None = None
    period_column: str | None = None

    def to_resolver_context(self) -> dict[str, Any]:
        return {
            "insightType": self.insight_type,
            "sourceTables": self.source_tables,
            "sourceColumns": self.source_columns,
            "metric": self.metric,
            "periodColumn": self.period_column,
        }


class AIAskAndRunRequest(BaseModel):
    """Generate SQL for a natural-language question, execute it, return rows.

    Powers the inline AI Question modal: the user clicks an AI-generated
    question and sees the answer (results) directly instead of being routed to
    the AI Assistant chat.
    """
    project_id: int
    question: str
    source: str | None = None
    card_context: AICardContext | None = None
    max_rows: int = 200


class AIGenerateQueryPreviewRequest(BaseModel):
    """Generate + execute a recommended query and return a renderable preview.

    Powers the Recommended Queries "Generate" button: generates SQL from the
    recommendation's business question, executes it, and returns rows so the
    user can preview before saving.
    """
    project_id: int
    question: str
    title: str | None = None
    description: str | None = None
    card_context: AICardContext | None = None
    max_rows: int = 200


class AISuggestDashboardsRequest(BaseModel):
    """Request several dashboard plan suggestions for a project (no save)."""
    project_id: int
    prompt: str | None = None
    audience: str | None = None
    desired_count: int = 3


class AISuggestionWidget(BaseModel):
    """A single widget carried in a dashboard suggestion's savePayload.

    Previews now carry executable ``sql`` (plus label/value columns), so Save can
    persist the exact widgets the user previewed instead of re-deriving a plan.
    """
    title: str = ""
    chartType: str = ""
    businessQuestion: str = ""
    sql: str = ""
    labelColumn: str = ""
    valueColumn: str = ""
    status: str = ""


class AISuggestionPayload(BaseModel):
    """The selected suggestion the user chose to persist (its savePayload)."""
    title: str = ""
    description: str = ""
    businessPurpose: str = ""
    audience: str = ""
    prompt: str = ""
    widgets: list[AISuggestionWidget] = []
    kpis: list[str] = []
    dataSources: list[str] = []


class AISaveDashboardSuggestionRequest(BaseModel):
    """Persist a previewed dashboard suggestion (strict save validation)."""
    project_id: int
    suggestionId: str | None = None
    suggestion: AISuggestionPayload


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
    accepted_tags: list[dict[str, Any]] = []
    accepted_kpis: list[dict[str, Any]] = []
    enabled_reference_tags: list[dict[str, Any]] = []
    enabled_reference_kpis: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    graph_nodes: list[dict[str, Any]] = []
    graph_edges: list[dict[str, Any]] = []
    document_families: list[dict[str, Any]] = []


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
    """Find which datasource view_name is referenced in the generated SQL.

    An AI-generated table must never be left with a blank source: a blank
    ``left_datasource`` makes the All Tables row show no Source and causes a
    "no datasource associated" error when a query is built from it. When no
    referenced table can be matched we fall back to the first allowed table so
    the query still binds to a real, executable datasource.
    """
    sql_upper = sql.upper()
    for table in allowed_tables:
        # Check for table name in FROM/JOIN clauses (with or without quotes)
        if table.upper() in sql_upper or f'"{table}"'.upper() in sql_upper:
            return table
    return allowed_tables[0] if allowed_tables else None


async def _build_source_catalog(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
) -> list[dict[str, Any]]:
    """Build the AI source catalog (data sources + saved queries) for a project.

    Each entry carries the source name, its known columns, and a short
    description so the AI server can semantically match the user's request to
    real project sources instead of inventing table names from the prompt.
    """
    catalog: list[dict[str, Any]] = []

    ds_rows = (
        await session.scalars(
            select(FileSourceMeta).where(
                FileSourceMeta.project_id == project_id,
                FileSourceMeta.tenant_id == tenant_id,
                FileSourceMeta.archived.is_(False),
            )
        )
    ).all()
    for ds in ds_rows:
        columns = [
            str(c.get("name"))
            for c in (ds.column_types or [])
            if isinstance(c, dict) and c.get("name")
        ]
        description = ""
        if isinstance(ds.ai_metadata, dict):
            description = str(ds.ai_metadata.get("summary") or "")
        catalog.append(
            {
                "name": ds.view_name,
                "columns": columns,
                "description": description or None,
                "kind": "table",
            }
        )

    query_rows = (
        await session.scalars(
            select(SavedQuery).where(SavedQuery.project_id == project_id)
        )
    ).all()
    for q in query_rows:
        catalog.append(
            {
                "name": q.name,
                "columns": [],
                "description": (q.description or "")[:200] or None,
                "kind": "query",
            }
        )

    return catalog


def _clarification_response(
    prompt: str,
    detail: Any,
    allowed_tables: list[str],
) -> dict[str, Any]:
    """Turn a 422 from the AI server into a friendly, structured response.

    The frontend renders ``message`` + ``suggested_sources`` instead of a raw
    validation stack trace. The detailed reason stays in server logs.
    """
    suggested: list[str] = []
    reason = ""
    if isinstance(detail, dict):
        suggested = list(detail.get("suggested_sources") or [])
        reason = str(detail.get("reason") or detail.get("message") or "")
    else:
        reason = str(detail or "")
    if not suggested:
        suggested = _heuristic_rank_sources(prompt, allowed_tables)

    logger.info(
        "AI query generation needs clarification | reason=%s | suggested=%s",
        reason, suggested,
    )
    message = (
        "I could not find an authorized table that matches part of your "
        "request."
    )
    if suggested:
        message += " Try choosing one of these related sources."
    return {
        "action": "generate_and_save_query",
        "status": "needs_clarification",
        "message": message,
        "suggested_sources": suggested,
    }


def _heuristic_rank_sources(prompt: str, allowed_tables: list[str]) -> list[str]:
    """Rank authorized sources by normalized/fuzzy match with the prompt."""
    scored = sorted(
        ((_score_source_match(prompt, t), t) for t in allowed_tables),
        key=lambda x: (-x[0], x[1]),
    )
    ranked = [t for score, t in scored if score > 0]
    return (ranked or allowed_tables)[:5]


# ---------------------------------------------------------------------------
# Fuzzy source-name matching
#
# Users refer to a data source by a partial or suffix-insensitive name
# ("fin_gl_chart_of_accounts", "chart of accounts") when the physical source is
# "fin_gl_chart_of_accounts_CSV". Normalize both sides and score the match so a
# confident single match is auto-selected and ambiguous matches ask the user.
# ---------------------------------------------------------------------------

_SOURCE_SUFFIX_RE = re.compile(
    r"(_csv|_xlsx|_xls|_json|_parquet|_tsv|_table|_tbl|_view)$", re.IGNORECASE
)


def _strip_source_suffix(name: str) -> str:
    return _SOURCE_SUFFIX_RE.sub("", (name or "").strip())


def _normalize_source_name(name: str) -> str:
    """Lowercase, drop a file-format suffix, and collapse separators to spaces."""
    text = _strip_source_suffix((name or "").lower())
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _score_source_match(request: str, source: str) -> int:
    """Score how well ``request`` refers to authorized ``source`` (0-100)."""
    req = (request or "").strip().lower()
    src = (source or "").strip().lower()
    if not req or not src:
        return 0
    if req == src:
        return 100
    req_n = _normalize_source_name(request)
    src_n = _normalize_source_name(source)
    if req_n and req_n == src_n:
        return 95
    if req == _strip_source_suffix(src).lower():
        return 92
    req_tokens = [t for t in req_n.split() if t]
    src_tokens = set(t for t in src_n.split() if t)
    if req_tokens and set(req_tokens).issubset(src_tokens):
        return 80
    if req_n and src_n and difflib.SequenceMatcher(None, req_n, src_n).ratio() >= 0.85:
        return 70
    if req_n and req_n in src_n:
        return 60
    return 0


def _resolve_prompt_source(
    prompt: str, allowed_tables: list[str]
) -> tuple[list[str], list[str]]:
    """Return ``(strong, close)`` source matches for a table-name-like prompt.

    ``strong`` are confident matches (score ≥ 90); ``close`` are plausible but
    ambiguous ones (60 ≤ score < 90). Both are ordered best-first.
    """
    scored = sorted(
        ((_score_source_match(prompt, t), t) for t in allowed_tables),
        key=lambda x: (-x[0], x[1]),
    )
    strong = [t for s, t in scored if s >= 90]
    close = [t for s, t in scored if 60 <= s < 90]
    return strong, close


def _heuristic_sql(prompt: str, allowed_tables: list[str]) -> str:
    """Build a baseline SELECT when the AI server is unavailable.

    Picks the table whose name best matches words in the prompt (falling back
    to the first available table) and returns a simple preview query. The user
    can refine it in the query builder.
    """
    if not allowed_tables:
        return ""
    prompt_lower = prompt.lower()
    best = allowed_tables[0]
    best_score = -1
    for table in allowed_tables:
        # Score by how many of the table's word-parts appear in the prompt.
        parts = [p for p in re.split(r"[_\s]+", table.lower()) if p]
        score = sum(1 for p in parts if p in prompt_lower)
        if score > best_score:
            best_score = score
            best = table
    return f'SELECT * FROM "{best}" LIMIT 100'


# ---------------------------------------------------------------------------
# Query-summary intent
#
# "Can you give me a summary of my queries?" is answered directly from the
# database rather than the AI server: the summary is then always
# authorization-correct (only the caller's accessible queries) and never
# depends on the AI server being reachable or schema-compatible — which also
# avoids the "Invalid request signature" failure users saw for this prompt.
# ---------------------------------------------------------------------------

_QUERY_SUMMARY_PATTERNS = [
    re.compile(r"\bsummary of (my|all|the) queries\b", re.IGNORECASE),
    re.compile(
        r"\b(summarize|summarise|list|show|overview of|recap) "
        r"(my|all|the) queries\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bhow many queries (do i|have i)\b", re.IGNORECASE),
]


def _is_query_summary_request(question: str) -> bool:
    """True when the prompt is asking for an overview of the user's queries."""
    q = (question or "").strip()
    return any(p.search(q) for p in _QUERY_SUMMARY_PATTERNS)


def _plural(n: int, singular: str, plural: str) -> str:
    return singular if n == 1 else plural


async def _build_query_summary(
    session: AsyncSession,
    context: RequestContext,
    *,
    include_archived: bool = False,
) -> str:
    """Build a friendly, authorization-scoped summary of the user's queries.

    Includes queries in every project the caller can access (private projects
    they own + shared projects they are an active member of). Archived queries
    are excluded unless explicitly requested.
    """
    member_sub = select(ProjectMember.project_id).where(
        ProjectMember.user_id == context.user_id,
        ProjectMember.is_active.is_(True),
    )
    projects = list(
        await session.scalars(
            select(Project)
            .where(
                Project.tenant_id == context.tenant_id,
                or_(
                    Project.owner_id == context.user_id,
                    Project.id.in_(member_sub),
                ),
            )
            .order_by(Project.name)
        )
    )
    if not projects:
        return (
            "You don't have access to any projects yet, so there are no "
            "queries to summarize."
        )

    ids = [p.id for p in projects]
    count_stmt = select(SavedQuery.project_id, func.count()).where(
        SavedQuery.project_id.in_(ids)
    )
    if not include_archived:
        count_stmt = count_stmt.where(SavedQuery.is_archived.is_(False))
    count_stmt = count_stmt.group_by(SavedQuery.project_id)
    counts = {pid: c for pid, c in (await session.execute(count_stmt)).all()}

    total = sum(counts.values())
    private = [
        (p, counts.get(p.id, 0)) for p in projects if not p.is_shared
    ]
    shared = [(p, counts.get(p.id, 0)) for p in projects if p.is_shared]

    lines: list[str] = []
    if total == 0:
        lines.append(
            "You don't have any "
            + ("" if include_archived else "active ")
            + "queries yet across your "
            + f"{len(projects)} accessible "
            + _plural(len(projects), "project", "projects")
            + "."
        )
        return "\n".join(lines)

    scope_word = "" if include_archived else "active "
    lines.append(
        f"You currently have {total} {scope_word}"
        f"{_plural(total, 'query', 'queries')} across your "
        f"{len(projects)} accessible "
        f"{_plural(len(projects), 'project', 'projects')}."
    )

    def _section(heading: str, rows: list[tuple[Project, int]]) -> None:
        with_queries = [(p, c) for p, c in rows if c > 0]
        if not with_queries:
            return
        lines.append("")
        lines.append(f"{heading}:")
        for p, c in with_queries:
            lines.append(f"- {p.name}: {c} {_plural(c, 'query', 'queries')}")

    _section("Private projects", private)
    _section("Shared projects", shared)

    lines.append("")
    if include_archived:
        lines.append(
            "This summary includes archived queries as requested."
        )
    else:
        lines.append(
            "All queries listed are active and available for execution. "
            "Archived queries are not included."
        )
    return "\n".join(lines)


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

    # A request for a summary of the user's queries is answered directly from
    # the database (authorization-correct, no AI-server dependency).
    if _is_query_summary_request(req.question):
        return {
            "answer": await _build_query_summary(session, context),
            "model_used": "tablescope-direct",
            "request_id": "",
            "context_summary": {},
        }

    payload = {
        "tenant_id": context.tenant_id,
        "user_id": context.user_id,
        "project_id": req.project_id,
        "question": req.question,
        "scope": req.scope,
        "include_query_history": req.include_query_history,
        "include_dashboard_context": req.include_dashboard_context,
        "history": [],
    }
    return await _forward_to_ai("/ai/ask", payload)


class RoutePromptRequest(BaseModel):
    prompt: str
    project_id: int | None = None


class RoutePromptResponse(BaseModel):
    route: str
    prefilled: str


@router.post("/route-prompt", response_model=RoutePromptResponse)
async def route_prompt(
    req: RoutePromptRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> RoutePromptResponse:
    """Route a Home hero prompt to the right destination.

    If the caller already has a project (or named one), the prompt opens that
    project's AI assistant pre-filled. Otherwise it seeds new-project creation.
    """
    prompt = req.prompt.strip()
    target_id = req.project_id
    if target_id is not None:
        await _check_project_access(session, context, target_id)
    else:
        member_sub = select(ProjectMember.project_id).where(
            ProjectMember.user_id == context.user_id,
            ProjectMember.is_active.is_(True),
        )
        target_id = await session.scalar(
            select(Project.id)
            .where(
                Project.tenant_id == context.tenant_id,
                or_(
                    Project.owner_id == context.user_id,
                    Project.id.in_(member_sub),
                ),
            )
            .order_by(Project.updated_at.desc())
            .limit(1)
        )

    if target_id is not None:
        return RoutePromptResponse(
            route=f"/projects/{target_id}/ai", prefilled=prompt
        )
    return RoutePromptResponse(route="/projects/new", prefilled=prompt)


async def _kg_context(
    session: AsyncSession,
    context: RequestContext,
    project_id: int,
    *,
    max_items: int = 20,
) -> dict[str, Any]:
    """Collect the project's Knowledge Graph context for AI generation.

    Best-effort: a graph that fails to load must never block dashboard/query
    generation, so any error yields an empty context block.
    """
    try:
        return await collect_knowledge_graph_ai_context(
            session,
            tenant_id=context.tenant_id,
            project_id=project_id,
            user_id=context.user_id,
            max_items=max_items,
        )
    except Exception:  # context is optional enrichment
        logger.exception(
            "Failed to collect Knowledge Graph context for project %s", project_id,
        )
        return {}


def _kg_context_chips(kg: dict[str, Any]) -> dict[str, Any]:
    """Compact, chip-friendly KG summary for dashboard preview cards.

    Returns short title lists (not full objects) the frontend renders as chips.
    """
    def _titles(key: str, cap: int = 4) -> list[str]:
        items = kg.get(key) or []
        out: list[str] = []
        for it in items:
            title = str((it or {}).get("title") or "").strip()
            if title and title not in out:
                out.append(title)
            if len(out) >= cap:
                break
        return out

    return {
        "risks": _titles("risks"),
        "opportunities": _titles("opportunities"),
        "gaps": _titles("gaps"),
        "measuredKpis": _titles("measured_kpis"),
        "recommendedKpis": _titles("recommended_kpis"),
        "governingDocuments": _titles("governing_documents"),
    }


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


def _shorten_ai_name(prompt: str) -> str:
    """Convert an AI prompt into a short, clean query/widget title.

    Examples:
        "Generate a query showing total revenue by category." → "AI - Total Revenue by Category"
        "Generate a dashboard with total revenue, total orders, ..." → "AI - Total Revenue, Total Orders"
        "Show monthly sales trend" → "AI - Monthly Sales Trend"
    """
    import re as _re

    s = prompt.strip().rstrip(".")

    # Strip common AI prompt prefixes
    s = _re.sub(
        r"^(?:generate|create|show|build|make|give me|write|produce)"
        r"\s+(?:a\s+)?(?:query|dashboard|report|chart|table|widget|view)?"
        r"\s*(?:showing|with|for|of|that shows|to show|displaying)?\s*",
        "", s, flags=_re.IGNORECASE,
    ).strip()

    # If the result starts with a SELECT statement, just use the first meaningful part
    if _re.match(r"^SELECT\b", s, _re.IGNORECASE):
        s = "Custom SQL Query"

    # Title-case and prefix
    if s:
        s = s.title()
        # Preserve common lowercase words
        for word in ("by", "of", "and", "the", "in", "for", "with", "to", "a"):
            s = _re.sub(rf"\b{word.title()}\b", word, s)
        # Ensure first char is uppercase
        s = s[0].upper() + s[1:]
    else:
        s = "Query"

    return f"AI - {s}"


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


async def _sample_query_values(
    *,
    sql: str,
    database: str,
    teiid_host: str | None = None,
    teiid_port: int | None = None,
) -> dict[str, set[str]]:
    """Execute a query with LIMIT 10 and return distinct string values per column.

    Returns a dict mapping column_name → set of non-null, non-numeric
    distinct string values found in the sample rows.
    """
    from app.routes.query import _auto_cast_aggregates, _run_sql

    sample_sql = _auto_cast_aggregates(sql.rstrip().rstrip(";")) + " LIMIT 10"
    try:
        result = await _run_sql(
            database=database, sql=sample_sql,
            teiid_host=teiid_host, teiid_port=teiid_port,
        )
    except Exception:
        logger.warning("Failed to sample query for scope validation: %s", sql[:80])
        return {}

    col_values: dict[str, set[str]] = {}
    for col in result.get("columns", []):
        col_values[col] = set()
    for row in result.get("rows", []):
        for col, val in row.items():
            if val is None:
                continue
            s = str(val).strip()
            if not s:
                continue
            col_values.setdefault(col, set()).add(s)
    return col_values


def _has_string_values(vals: set[str]) -> bool:
    """Return True if the set contains at least one non-numeric string value."""
    for v in vals:
        try:
            float(v.replace(",", ""))
        except ValueError:
            return True
    return False


def _string_values(vals: set[str]) -> set[str]:
    """Return only the non-numeric string values from a set."""
    result: set[str] = set()
    for v in vals:
        try:
            float(v.replace(",", ""))
        except ValueError:
            result.add(v)
    return result


def _value_overlap(
    vals_a: set[str],
    vals_b: set[str],
    *,
    same_column_name: bool = False,
) -> float:
    """Return the fraction of overlapping values (Jaccard-like).

    When ``same_column_name`` is False (different column names), filters
    out numeric values before comparing so that ID columns (1, 2, 3)
    don't get matched against name columns.

    When ``same_column_name`` is True, compares ALL values including
    numeric ones — two columns both named "CategoryID" with values
    {1, 2, 3} should match.
    """
    if same_column_name:
        a, b = vals_a, vals_b
    else:
        a = _string_values(vals_a)
        b = _string_values(vals_b)
    if not a or not b:
        return 0.0
    intersection = a & b
    union = a | b
    return len(intersection) / len(union) if union else 0.0


async def _ai_analyze_and_create_scopes(
    *,
    session: AsyncSession,
    context: RequestContext,
    project_id: int,
) -> dict[str, Any]:
    """Hybrid scope analysis: AI suggestions validated by cell-level data.

    Phase 1 — AI Analysis: LLM analyzes SQL structure to suggest scopes
      (direction, meaningful columns).
    Phase 2 — Cell Validation: execute each query with LIMIT 10, compare
      actual cell values to validate AI suggestions and discover cross-column
      relationships the AI may have missed (e.g. CategoryID ↔ CategoryName
      when they share actual values).
    """
    import asyncio

    from app.routes.query import _resolve_vdb_database
    from app.services.tenant_teiid_resolver import TenantTeiidResolver

    # Get all saved queries for this project
    queries_result = await session.scalars(
        select(SavedQuery).where(SavedQuery.project_id == project_id)
    )
    queries = list(queries_result)

    if not queries:
        return {"relationships": [], "scopes_created": 0, "status": "ok"}

    # Only send queries that have SQL — include extracted columns for clarity
    query_infos: list[dict[str, Any]] = []
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

    # ── Phase 1: AI structural analysis via the dedicated scopes endpoint ──
    # Uses /ai/project/scopes/analyze (NOT the generic /ai/ask): the AI server
    # has a purpose-built prompt that returns structured ScopeSuggestion JSON.
    payload = {
        "tenant_id": context.tenant_id,
        "user_id": context.user_id,
        "project_id": project_id,
        "queries": [
            {"id": q["id"], "name": q["name"], "sql": q["sql"]}
            for q in query_infos
        ],
    }

    # Run AI analysis and data sampling in parallel
    database = await _resolve_vdb_database(
        session=session, context=context, project_id=project_id,
    )
    endpoint = await TenantTeiidResolver(session).resolve_for_org(context.tenant_id)

    async def _sample_one(q: dict[str, Any]) -> tuple[int, dict[str, set[str]]]:
        vals = await _sample_query_values(
            sql=q["sql"], database=database,
            teiid_host=endpoint.pg_host, teiid_port=endpoint.pg_port,
        )
        return q["id"], vals

    ai_task = asyncio.create_task(
        _forward_to_ai("/ai/project/scopes/analyze", payload)
    )
    sample_tasks = [asyncio.create_task(_sample_one(q)) for q in query_infos]
    ai_response, *sample_results = await asyncio.gather(ai_task, *sample_tasks)

    # Build query_id → {column_name: set(values)} from samples
    query_values: dict[int, dict[str, set[str]]] = {}
    for qid, col_vals in sample_results:
        query_values[qid] = col_vals

    # The dedicated endpoint returns structured scope suggestions directly.
    scopes_list: list[dict[str, Any]] = ai_response.get("scopes", []) or []

    # Build column map: query_id → set of column names (lowercase)
    query_col_map: dict[int, set[str]] = {}
    for q in queries:
        if q.sql_text:
            cols = _extract_select_columns(q.sql_text)
            query_col_map[q.id] = {c.lower() for c in cols}
        else:
            query_col_map[q.id] = set()

    # ── Phase 2: Validate AI suggestions with cell-level data ────────
    valid_ids = {q.id for q in queries}
    validated_scopes: list[dict[str, Any]] = []

    for suggestion in scopes_list:
        src_qid = suggestion.get("source_query_id")
        tgt_qid = suggestion.get("target_query_id")
        src_field = suggestion.get("source_field", "")
        tgt_field = suggestion.get("target_field", "")

        if src_qid not in valid_ids or tgt_qid not in valid_ids:
            continue
        if not src_field or not tgt_field:
            continue

        # Check fields exist in SELECT clauses
        src_cols = query_col_map.get(src_qid, set())
        tgt_cols = query_col_map.get(tgt_qid, set())
        if src_field.lower() not in src_cols or tgt_field.lower() not in tgt_cols:
            continue

        # Validate with sampled cell values — require some overlap.
        # When column names match (e.g. CategoryID↔CategoryID), compare ALL
        # values including numeric ones. When names differ (e.g.
        # CategoryName↔CategoryID), only compare string values to prevent
        # false matches between text and numeric columns.
        src_vals = query_values.get(src_qid, {}).get(src_field, set())
        tgt_vals = query_values.get(tgt_qid, {}).get(tgt_field, set())
        names_match = src_field.lower() == tgt_field.lower()
        overlap = _value_overlap(src_vals, tgt_vals, same_column_name=names_match)

        src_sampled = src_qid in query_values and bool(query_values[src_qid])
        tgt_sampled = tgt_qid in query_values and bool(query_values[tgt_qid])
        if overlap == 0.0 and src_sampled and tgt_sampled:
            logger.info(
                "Rejected AI scope %s.%s → %s.%s — zero value overlap "
                "(src=%r, tgt=%r, names_match=%s)",
                src_qid, src_field, tgt_qid, tgt_field,
                list(src_vals)[:3], list(tgt_vals)[:3], names_match,
            )
            continue

        conf = suggestion.get("confidence", 1.0)
        if overlap > 0:
            conf = max(conf, overlap)

        validated_scopes.append({
            "source_query_id": src_qid,
            "source_query_name": suggestion.get("source_query_name", query_names.get(src_qid, "")),
            "source_field": src_field,
            "target_query_id": tgt_qid,
            "target_query_name": suggestion.get("target_query_name", query_names.get(tgt_qid, "")),
            "target_field": tgt_field,
            "confidence": conf,
            "reason": suggestion.get("reason", ""),
        })

    # ── Phase 2b: Discover cross-column relationships via value overlap ──
    # Find columns across different queries that share values even if
    # the AI didn't suggest them (e.g. CategoryID ↔ CategoryName when the
    # underlying values are the same entity strings).
    MIN_OVERLAP = 0.3
    discovered_keys = {
        (s["source_query_id"], s["source_field"],
         s["target_query_id"], s["target_field"])
        for s in validated_scopes
    }

    for i, qi in enumerate(query_infos):
        for qj in query_infos[i + 1:]:
            if qi["id"] == qj["id"]:
                continue
            vals_i = query_values.get(qi["id"], {})
            vals_j = query_values.get(qj["id"], {})
            for col_i, v_i in vals_i.items():
                if _is_numeric_column(col_i):
                    continue
                for col_j, v_j in vals_j.items():
                    if _is_numeric_column(col_j):
                        continue
                    names_match = col_i.lower() == col_j.lower()
                    overlap = _value_overlap(v_i, v_j, same_column_name=names_match)
                    if overlap < MIN_OVERLAP:
                        continue

                    # Determine direction: summarized → detailed
                    i_summ = _is_summarized_query(qi["sql"])
                    j_summ = _is_summarized_query(qj["sql"])
                    if i_summ and not j_summ:
                        src_qid, src_field = qi["id"], col_i
                        tgt_qid, tgt_field = qj["id"], col_j
                    elif j_summ and not i_summ:
                        src_qid, src_field = qj["id"], col_j
                        tgt_qid, tgt_field = qi["id"], col_i
                    elif i_summ and j_summ:
                        continue  # both summarized — skip
                    else:
                        # Neither is summarized — pick the shorter one as source
                        if len(qi["columns"]) <= len(qj["columns"]):
                            src_qid, src_field = qi["id"], col_i
                            tgt_qid, tgt_field = qj["id"], col_j
                        else:
                            src_qid, src_field = qj["id"], col_j
                            tgt_qid, tgt_field = qi["id"], col_i

                    key = (src_qid, src_field, tgt_qid, tgt_field)
                    rev_key = (tgt_qid, tgt_field, src_qid, src_field)
                    if key in discovered_keys or rev_key in discovered_keys:
                        continue
                    discovered_keys.add(key)

                    validated_scopes.append({
                        "source_query_id": src_qid,
                        "source_query_name": query_names.get(src_qid, ""),
                        "source_field": src_field,
                        "target_query_id": tgt_qid,
                        "target_query_name": query_names.get(tgt_qid, ""),
                        "target_field": tgt_field,
                        "confidence": overlap,
                        "reason": f"Cell-level value overlap ({overlap:.0%})",
                    })

    # ── Phase 2c: Exact column-name matching (fallback) ────────────
    # When sampling fails or the AI omits a suggestion, matching column
    # names across two queries is still a strong signal.  This catches
    # cases like CategoryID↔CategoryID where the AI skipped it and
    # sampling returned no data.
    for i, qi in enumerate(query_infos):
        for qj in query_infos[i + 1:]:
            if qi["id"] == qj["id"]:
                continue
            common_cols = set(c.lower() for c in qi["columns"]) & set(
                c.lower() for c in qj["columns"]
            )
            for col_lower in common_cols:
                if _is_numeric_column(col_lower):
                    continue
                # Find original-case column name from each query
                col_i = next((c for c in qi["columns"] if c.lower() == col_lower), col_lower)
                col_j = next((c for c in qj["columns"] if c.lower() == col_lower), col_lower)

                # Determine direction
                i_summ = _is_summarized_query(qi["sql"])
                j_summ = _is_summarized_query(qj["sql"])
                if i_summ and not j_summ:
                    src_qid, src_field = qi["id"], col_i
                    tgt_qid, tgt_field = qj["id"], col_j
                elif j_summ and not i_summ:
                    src_qid, src_field = qj["id"], col_j
                    tgt_qid, tgt_field = qi["id"], col_i
                elif i_summ and j_summ:
                    continue
                else:
                    if len(qi["columns"]) <= len(qj["columns"]):
                        src_qid, src_field = qi["id"], col_i
                        tgt_qid, tgt_field = qj["id"], col_j
                    else:
                        src_qid, src_field = qj["id"], col_j
                        tgt_qid, tgt_field = qi["id"], col_i

                key = (src_qid, src_field, tgt_qid, tgt_field)
                rev_key = (tgt_qid, tgt_field, src_qid, src_field)
                if key in discovered_keys or rev_key in discovered_keys:
                    continue
                discovered_keys.add(key)

                validated_scopes.append({
                    "source_query_id": src_qid,
                    "source_query_name": query_names.get(src_qid, ""),
                    "source_field": src_field,
                    "target_query_id": tgt_qid,
                    "target_query_name": query_names.get(tgt_qid, ""),
                    "target_field": tgt_field,
                    "confidence": 0.85,
                    "reason": f"Exact column name match ({col_lower})",
                })

    # ── Write validated scopes to database ───────────────────────────
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

    relationships: list[dict[str, Any]] = []
    scopes_created = 0
    ai_set = None
    for s in validated_scopes:
        key = (s["source_query_id"], s["source_field"],
               s["target_query_id"], s["target_field"])

        rel = {
            "left_table": s["source_query_name"],
            "left_column": s["source_field"],
            "right_table": s["target_query_name"],
            "right_column": s["target_field"],
            "source_query_id": s["source_query_id"],
            "target_query_id": s["target_query_id"],
            "confidence": s["confidence"],
            "reason": s["reason"],
            "scope_exists": True,
        }

        if key in existing_keys:
            relationships.append(rel)
            continue

        # Group AI-discovered scopes under the project's "AI Generated Scopes"
        # set so they surface (with a count + toggle) in the new Scopes UI.
        if ai_set is None:
            ai_set = await _get_or_create_ai_scope_set(
                session,
                tenant_id=context.tenant_id,
                project_id=project_id,
                user_id=context.user_id,
            )
        scope = QueryScope(
            tenant_id=context.tenant_id,
            project_id=project_id,
            scope_set_id=ai_set.id,
            query_id=s["source_query_id"],
            source_field=s["source_field"],
            source_table=s["source_query_name"],
            target_query_id=s["target_query_id"],
            target_field=s["target_field"],
            target_table=s["target_query_name"],
            confidence_score=s.get("confidence"),
            created_by_ai=True,
            enabled=ai_set.enabled,
            created_by=context.user_id,
        )
        session.add(scope)
        existing_keys.add(key)
        scopes_created += 1
        relationships.append(rel)

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
        description=req.description or "",
        sql_text=req.sql_text,
        left_datasource=left_datasource,
        ai_generated=True,
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


# Leading intent verb the user may type in the "Generate with AI" box, e.g.
# "generate table supplier performance" or "build query top vendors". Both the
# table and query phrasings must reach the SAME read-only query-generation flow;
# stripping the verb also stops the model from reading "table" as a DDL/CREATE
# request (which the SQL validator rejects — the source of the earlier
# "authorization error" on `generate table …`).
_GENERATION_INTENT_PATTERN = re.compile(
    r"^\s*(?:please\s+)?(?:generate|create|build|make)\s+(table|query)\b[:\s-]*",
    re.IGNORECASE,
)


def normalize_ai_generation_intent(prompt: str) -> tuple[str, str]:
    """Normalize an AI generation prompt into ``(intent, cleaned_prompt)``.

    ``intent`` is ``"table"`` or ``"query"`` (defaults to ``"query"``). Both
    intents use the same authorized, read-only query-generation path — the only
    difference is a hint appended to the prompt. The recognised leading verb is
    stripped so the remaining text describes the desired data, not a DDL action.
    """
    text = prompt or ""
    match = _GENERATION_INTENT_PATTERN.match(text)
    if not match:
        return "query", text.strip()
    intent = match.group(1).lower()
    remainder = text[match.end():].strip()
    return intent, remainder or text.strip()


@router.post("/actions/generate-and-save-query")
async def ai_generate_and_save_query(
    req: AIGenerateAndSaveQueryRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Generate SQL from a natural language prompt, validate, and save.

    Supports both new query creation and modification of existing queries.
    When the prompt indicates modification intent (modify, update, edit,
    change, add to, etc.) and references an existing query name, the
    existing query is updated in place instead of creating a new one.
    """
    project = await _check_project_access(session, context, req.project_id)

    # Normalize "generate/create/build table|query …" so both phrasings hit this
    # same authorized flow and the model treats the request as a read-only query
    # rather than a table (DDL) creation.
    gen_intent, base_prompt = normalize_ai_generation_intent(req.prompt)

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

    # ── Detect modification intent ────────────────────────────────────
    import re as _re
    _MODIFY_PATTERN = _re.compile(
        r"^(?:modify|update|edit|change|alter|revise|adjust|fix|add\s+to|"
        r"add\s+.+?\s+to|remove\s+from|include\s+.+?\s+in)\s+",
        _re.IGNORECASE,
    )
    is_modification = bool(_MODIFY_PATTERN.search(req.prompt.strip()))

    # If modification, find the referenced existing query
    existing_query: SavedQuery | None = None
    if is_modification:
        existing_result = await session.scalars(
            select(SavedQuery).where(SavedQuery.project_id == project.id)
        )
        all_queries = list(existing_result)
        prompt_lower = req.prompt.lower()
        # Score each query by how well its name matches the prompt
        best_match: SavedQuery | None = None
        best_score = 0
        for eq in all_queries:
            if not eq.name:
                continue
            eq_name_lower = eq.name.lower().strip()
            # Check if the query name appears in the prompt
            if eq_name_lower in prompt_lower:
                score = len(eq_name_lower)
                if score > best_score:
                    best_score = score
                    best_match = eq
        existing_query = best_match
        if existing_query:
            logger.info(
                "Modification intent detected — updating query %d (%s)",
                existing_query.id, existing_query.name,
            )

    # Step 1: Call AI server to generate SQL
    prompt_text = base_prompt
    if existing_query and existing_query.sql_text:
        # Include the existing SQL so the AI can modify it
        prompt_text = (
            f"{base_prompt}\n\n"
            f"Here is the current SQL for the query \"{existing_query.name}\":\n"
            f"{existing_query.sql_text}\n\n"
            f"Please modify this SQL according to the request above. "
            f"Return ONLY the modified SQL."
        )
    elif gen_intent == "table":
        # A "generate table" request still resolves to a single read-only
        # SELECT that materializes the table — never CREATE/DDL.
        prompt_text = (
            f"{base_prompt}\n\n"
            "Return a single read-only SELECT query that produces this table. "
            "Do not emit CREATE TABLE, DDL, or any write statement."
        )

    # Fuzzy source match: when the prompt is essentially a source name given
    # without its physical suffix ("fin_gl_chart_of_accounts" for
    # "fin_gl_chart_of_accounts_CSV"), resolve it directly. A single confident
    # match is auto-selected; several plausible matches ask the user to choose.
    ai_result: dict[str, Any] = {}
    generated_sql = ""
    if not existing_query and allowed_tables:
        strong, close = _resolve_prompt_source(base_prompt, allowed_tables)
        if len(strong) == 1 and not close:
            matched = strong[0]
            generated_sql = f'SELECT * FROM "{matched}" LIMIT 100'
            ai_result = {
                "explanation": (
                    f'Matched your request to authorized source "{matched}".'
                ),
                "model_used": "source-match",
            }
        elif len(strong) > 1 or (not strong and len(close) > 1):
            return {
                "action": "generate_and_save_query",
                "status": "needs_clarification",
                "message": (
                    "I found multiple matching sources. Which one should I use?"
                ),
                "suggested_sources": (strong or close)[:5],
            }

    try:
        if not generated_sql:  # not resolved by fuzzy source match
            source_catalog = await _build_source_catalog(
                session, tenant_id=context.tenant_id, project_id=req.project_id
            )
            payload = {
                "tenant_id": context.tenant_id,
                "user_id": context.user_id,
                "project_id": req.project_id,
                "prompt": prompt_text,
                "allowed_tables": allowed_tables,
                "source_catalog": source_catalog,
                "preferred_sources": [],
                "relevant_columns": [],
                # Knowledge Graph context steers generated SQL toward validated
                # risks/gaps/measured KPIs surfaced by the graph.
                "knowledge_graph_context": await _kg_context(
                    session, context, req.project_id,
                ),
            }
            ai_result = await _forward_to_ai("/ai/query/generate", payload)
            generated_sql = ai_result.get("sql", "").rstrip().rstrip(";")
    except HTTPException as exc:
        # A 422 means the AI generated SQL that could not be validated/repaired
        # (e.g. it could not map the request to an authorized source). Surface a
        # friendly, structured clarification instead of a raw validation error.
        if exc.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY:
            return _clarification_response(req.prompt, exc.detail, allowed_tables)
        # The local AI server is optional/may be offline. Rather than failing
        # the action outright, fall back to a deterministic query built from
        # the prompt + the project's available tables.
        if exc.status_code != status.HTTP_503_SERVICE_UNAVAILABLE:
            raise
        generated_sql = _heuristic_sql(req.prompt, allowed_tables)
        ai_result = {
            "explanation": (
                "Generated without the AI server (offline) — a baseline query "
                "from your prompt and available tables. Edit it as needed."
            ),
            "model_used": "heuristic-fallback",
        }

    if not generated_sql:
        generated_sql = _heuristic_sql(req.prompt, allowed_tables)
    if not generated_sql:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Could not generate SQL — connect a data source to this "
                "project first."
            ),
        )

    # Detect which datasource the SQL references
    left_datasource = _detect_datasource(generated_sql, allowed_tables)

    if existing_query:
        # Update the existing query in place
        existing_query.sql_text = generated_sql
        existing_query.left_datasource = left_datasource
        existing_query.description = req.description or req.prompt
        await session.commit()
        await session.refresh(existing_query)

        logger.info(
            "AI action: update_query | query_id=%d project=%d tenant=%d user=%d",
            existing_query.id, project.id, context.tenant_id, context.user_id,
        )
        return {
            "action": "update_query",
            "status": "updated",
            "query_id": existing_query.id,
            "name": existing_query.name,
            "sql_text": existing_query.sql_text,
        }

    # Step 2: Derive a name if not provided (from the cleaned prompt, so the
    # "generate table"/"generate query" verb isn't baked into the table name).
    name = req.name or _shorten_ai_name(base_prompt)

    # Step 3: Save as new query
    query = SavedQuery(
        project_id=project.id,
        owner_id=context.user_id,
        name=name,
        description=req.description or req.prompt,
        sql_text=generated_sql,
        left_datasource=left_datasource,
        ai_generated=True,
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
        "selected_sources": ai_result.get("selected_sources", []),
        "repaired": ai_result.get("repaired", False),
    }


def _is_numeric_value(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int | float):
        return True
    if isinstance(value, str):
        try:
            float(value.replace(",", "").strip())
            return True
        except (ValueError, AttributeError):
            return False
    return False


def _looks_like_time_column(name: str) -> bool:
    lowered = name.lower()
    return any(
        token in lowered
        for token in ("date", "time", "month", "year", "day", "week", "quarter")
    )


def _suggest_visualization(
    columns: list[str], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Pick a sensible default chart for a result set (deterministic).

    - single numeric cell -> kpi
    - a time column + a numeric column -> line
    - a categorical column + a numeric column -> bar
    - otherwise -> table
    """
    if not columns or not rows:
        return {"type": "table"}

    sample = rows[0]
    numeric_cols = [
        c
        for c in columns
        if any(_is_numeric_value(r.get(c)) for r in rows[:20])
    ]
    non_numeric_cols = [c for c in columns if c not in numeric_cols]

    if len(rows) == 1 and len(columns) == 1 and _is_numeric_value(sample.get(columns[0])):
        return {"type": "kpi", "metricField": columns[0]}

    if numeric_cols and non_numeric_cols:
        y_field = numeric_cols[0]
        time_cols = [c for c in non_numeric_cols if _looks_like_time_column(c)]
        if time_cols:
            return {"type": "line", "xField": time_cols[0], "yField": y_field}
        return {"type": "bar", "xField": non_numeric_cols[0], "yField": y_field}

    return {"type": "table"}


_LIMIT_RE = re.compile(r"\blimit\s+\d+\s*$", re.IGNORECASE)


def _apply_row_limit(sql: str, max_rows: int) -> str:
    """Ensure a preview query is bounded so it never runs unbounded."""
    trimmed = sql.strip().rstrip(";").rstrip()
    if _LIMIT_RE.search(trimmed):
        return trimmed
    return f"{trimmed} LIMIT {max_rows}"


async def _execute_project_sql(
    session: AsyncSession,
    context: RequestContext,
    project_id: int,
    sql: str,
) -> dict[str, Any]:
    """Execute SQL against the project's VDB and return ``{columns, rows}``."""
    from app.routes.query import (
        _auto_cast_aggregates,
        _resolve_vdb_database,
        _run_sql,
    )
    from app.services.tenant_teiid_resolver import TenantTeiidResolver

    database = await _resolve_vdb_database(
        session=session, context=context, project_id=project_id
    )
    endpoint = await TenantTeiidResolver(session).resolve_for_org(context.tenant_id)
    return await _run_sql(
        database=database,
        sql=_auto_cast_aggregates(sql),
        teiid_host=endpoint.pg_host,
        teiid_port=endpoint.pg_port,
    )


async def _project_table_schema(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
) -> list[dict[str, Any]]:
    """Build the exact per-source column schema for SQL repair.

    Shape: ``[{"table": view, "columns": [{"name", "type"}]}]`` — the same
    contract the AI server's ``fix-sql`` endpoint consumes so it can rewrite a
    rejected query using real columns/types (never invented ones).
    """
    rows = (
        await session.scalars(
            select(FileSourceMeta).where(
                FileSourceMeta.project_id == project_id,
                FileSourceMeta.tenant_id == tenant_id,
                FileSourceMeta.archived.is_(False),
            )
        )
    ).all()
    schema: list[dict[str, Any]] = []
    for ds in rows:
        columns = [
            {"name": str(c.get("name")), "type": str(c.get("type") or "")}
            for c in (ds.column_types or [])
            if isinstance(c, dict) and c.get("name")
        ]
        schema.append({"table": ds.view_name, "columns": columns})
    return schema


async def _execute_with_repair(
    session: AsyncSession,
    context: RequestContext,
    *,
    project_id: int,
    sql: str,
    allowed_tables: list[str],
    max_rows: int,
    table_schema: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str, str]:
    """Execute SQL; on an engine error, repair via the AI using the exact
    Teiid error + real schema, then re-run.

    Closes the same self-repair loop the dashboard path uses so Teiid quirks
    (unsupported functions like DATEDIFF, un-CAST string arithmetic, alias/
    GROUP BY mistakes) heal automatically instead of surfacing as a dead-end
    error. Returns ``(result_or_none, final_sql, last_error)``.
    """
    from app.services import ai_intelligence_client as ai

    current = sql
    last_error = ""
    for attempt in range(3):
        bounded = _apply_row_limit(current, max_rows)
        try:
            result = await _execute_project_sql(
                session, context, project_id, bounded
            )
            return result, current, ""
        except HTTPException as exc:
            last_error = str(exc.detail)
            if attempt >= 2:
                break
            fixed = await ai.fix_sql(
                tenant_id=context.tenant_id,
                user_id=context.user_id,
                project_id=project_id,
                sql=current,
                error=last_error,
                allowed_tables=allowed_tables,
                table_schema=table_schema,
            )
            normalized = (fixed or "").strip().rstrip(";")
            if (
                not normalized
                or normalized == current.strip().rstrip(";")
                or not _is_read_only_select(normalized)
            ):
                break
            current = normalized
    return None, current, last_error


_READONLY_START_RE = re.compile(r"^(?:SELECT|WITH)\b", re.IGNORECASE)
_LEADING_SQL_COMMENT_RE = re.compile(
    r"^(?:\s*(?:--[^\n]*\n|/\*.*?\*/))+", re.DOTALL
)


def _is_read_only_select(sql: str) -> bool:
    """True only for a single read-only statement (defense-in-depth vs prose).

    The AI server already strips prose, but this guard guarantees natural-language
    text is never forwarded to Teiid as SQL even if the AI server misbehaves.
    """
    body = _LEADING_SQL_COMMENT_RE.sub("", (sql or "").strip()).lstrip()
    return bool(_READONLY_START_RE.match(body))


def _ai_generation_error(exc: HTTPException) -> tuple[str, dict[str, Any]]:
    """Translate an AI-server generation failure into a friendly message + details.

    Returns ``(message, details)`` where ``message`` is safe to show a user and
    ``details`` carries expandable technical context (matched sources, validation
    error) — never a raw dict repr or stack trace.
    """
    friendly = "We could not safely build a query for this question."
    details: dict[str, Any] = {}
    detail = exc.detail
    if isinstance(detail, dict):
        message = detail.get("message")
        if message:
            friendly = str(message)
        if detail.get("reason"):
            details["validationError"] = str(detail["reason"])
        sources = detail.get("suggested_sources")
        if isinstance(sources, list) and sources:
            details["matchedSources"] = [
                (s.get("name") if isinstance(s, dict) else str(s))
                for s in sources
            ]
    elif isinstance(detail, str) and detail:
        details["validationError"] = detail
    return friendly, details


async def _generate_sql_for_question(
    session: AsyncSession,
    context: RequestContext,
    project_id: int,
    question: str,
    *,
    preferred_sources: list[str] | None = None,
    relevant_columns: list[str] | None = None,
) -> dict[str, Any]:
    """Generate SQL for a natural-language question via the AI server.

    Returns the raw AI result dict (``sql``/``explanation``/``selected_sources``)
    plus the resolved ``allowed_tables``. Raises HTTPException on failure so the
    caller can convert it into a structured, non-fatal modal error.

    ``preferred_sources``/``relevant_columns`` come from the Project Semantic
    Source Resolver and steer the model toward the authorized source the
    request maps to.
    """
    ds_stmt = select(FileSourceMeta).where(
        FileSourceMeta.project_id == project_id,
        FileSourceMeta.tenant_id == context.tenant_id,
        FileSourceMeta.archived.is_(False),
    )
    ds_result = await session.execute(ds_stmt)
    allowed_tables = [ds.view_name for ds in ds_result.scalars()]

    source_catalog = await _build_source_catalog(
        session, tenant_id=context.tenant_id, project_id=project_id
    )
    payload = {
        "tenant_id": context.tenant_id,
        "user_id": context.user_id,
        "project_id": project_id,
        "prompt": question,
        "allowed_tables": allowed_tables,
        "source_catalog": source_catalog,
        "preferred_sources": preferred_sources or [],
        "relevant_columns": relevant_columns or [],
        "knowledge_graph_context": await _kg_context(
            session, context, project_id
        ),
    }
    ai_result = await _forward_to_ai("/ai/query/generate", payload)
    ai_result["_allowed_tables"] = allowed_tables
    return ai_result


async def _resolve_action_sources(
    session: AsyncSession,
    context: RequestContext,
    *,
    project_id: int,
    question: str,
    intent: str,
    source: str | None = None,
    card_context: AICardContext | None = None,
) -> Any:
    """Run the Project Semantic Source Resolver for one AI action.

    A user-picked ``source`` (e.g. chosen from a prior clarification) is treated
    as an authorized card source so the resolver locks onto it.
    """
    from app.services.project_source_resolver import resolve_project_source

    ctx: dict[str, Any] = (
        card_context.to_resolver_context() if card_context else {}
    )
    if source:
        ctx = {**ctx, "sourceTables": [source]}
    return await resolve_project_source(
        session,
        tenant_id=context.tenant_id,
        project_id=project_id,
        question=question,
        intent=intent,
        card_context=ctx or None,
    )


async def _ask_and_run_core(
    session: AsyncSession,
    context: RequestContext,
    *,
    project_id: int,
    question: str,
    max_rows: int,
    source: str | None = None,
    card_context: Any | None = None,
) -> dict[str, Any]:
    """Resolve a source, generate SQL, execute it, and return the result dict.

    Shared by the ask-and-run action endpoint and the AI Assistant chat so both
    ground answers on real executed data. Never raises on a generation/execution
    failure — returns a structured ``status`` with SQL + error instead.
    """
    resolver = await _resolve_action_sources(
        session, context,
        project_id=project_id,
        question=question,
        intent="question_answer",
        source=source,
        card_context=card_context,
    )

    try:
        ai_result = await _generate_sql_for_question(
            session, context, project_id, question,
            preferred_sources=resolver.preferred_sources,
            relevant_columns=resolver.relevant_columns,
        )
    except HTTPException as exc:
        friendly, details = _ai_generation_error(exc)
        return {
            "question": question,
            "sql": "",
            "columns": [],
            "rows": [],
            "suggestedVisualization": {"type": "table"},
            "explanation": "",
            "dataSourcesUsed": [],
            "status": "generation_error",
            "error": friendly,
            "errorDetails": details,
        }

    allowed_tables = ai_result.pop("_allowed_tables", [])
    sql = (ai_result.get("sql") or "").strip().rstrip(";")
    if not sql or not _is_read_only_select(sql):
        return {
            "question": question,
            "sql": sql if sql else "",
            "columns": [],
            "rows": [],
            "suggestedVisualization": {"type": "table"},
            "explanation": ai_result.get("explanation", ""),
            "dataSourcesUsed": [],
            "status": "generation_error",
            "error": "We could not safely build a query for this question.",
            "errorDetails": {"sql": sql} if sql else {},
        }

    table_schema = await _project_table_schema(
        session, tenant_id=context.tenant_id, project_id=project_id
    )
    result, sql, exec_error = await _execute_with_repair(
        session, context,
        project_id=project_id,
        sql=sql,
        allowed_tables=allowed_tables,
        max_rows=max_rows,
        table_schema=table_schema,
    )
    if result is None:
        return {
            "question": question,
            "sql": sql,
            "columns": [],
            "rows": [],
            "suggestedVisualization": {"type": "table"},
            "explanation": ai_result.get("explanation", ""),
            "dataSourcesUsed": [_detect_datasource(sql, allowed_tables) or ""],
            "status": "execution_error",
            "error": "We could not run this query against the project's data.",
            "errorDetails": {
                "sql": sql,
                "executionError": exec_error,
            },
        }

    columns = result.get("columns", [])
    rows = result.get("rows", [])[:max_rows]
    used = _detect_datasource(sql, allowed_tables)
    return {
        "question": question,
        "sql": sql,
        "columns": columns,
        "rows": rows,
        "suggestedVisualization": _suggest_visualization(columns, rows),
        "explanation": ai_result.get("explanation", ""),
        "dataSourcesUsed": [used] if used else [],
        "status": "success",
        "error": None,
    }


async def _forward_prose_answer(
    context: RequestContext,
    *,
    project_id: int,
    question: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    """Free-text answer from the AI server's documents + knowledge-graph path.

    Used as a fallback for analytical/document questions that don't map to a
    single SQL source, so they get a real answer instead of a hard error.
    """
    try:
        result = await _forward_to_ai("/ai/ask", {
            "tenant_id": context.tenant_id,
            "user_id": context.user_id,
            "project_id": project_id,
            "question": question,
            "scope": "project",
            "include_query_history": True,
            "include_dashboard_context": True,
            "history": history or [],
        })
    except HTTPException:
        return ""
    return str(result.get("answer") or "").strip()


@router.post("/actions/ask-and-run")
async def ai_ask_and_run(
    req: AIAskAndRunRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Generate SQL for a question, execute it, and return the results.

    Never raises on a generation/execution failure: returns a structured
    ``status`` (``success`` / ``generation_error`` / ``execution_error``) with
    the SQL (when available) and an error message so the modal can render an
    inline error and reveal the SQL instead of navigating away.

    When the question can't be grounded on a data source (``generation_error``
    from source resolution), fall back to the free-text documents/knowledge-graph
    answer — the same path the AI Assistant uses — so analytical questions are
    answered as prose instead of showing a "couldn't match a source" error.
    """
    await _check_project_access(session, context, req.project_id)
    result = await _ask_and_run_core(
        session, context,
        project_id=req.project_id,
        question=req.question,
        max_rows=req.max_rows,
        source=req.source,
        card_context=req.card_context,
    )
    if result.get("status") == "success":
        result["answerType"] = "data"
        return result
    if result.get("status") == "generation_error":
        prose = await _forward_prose_answer(
            context, project_id=req.project_id, question=req.question
        )
        if prose:
            return {
                "question": req.question,
                "sql": "",
                "columns": [],
                "rows": [],
                "suggestedVisualization": {"type": "table"},
                "explanation": prose,
                "dataSourcesUsed": [],
                "status": "success",
                "answerType": "text",
                "error": None,
            }
    return result


@router.post("/actions/generate-query-preview")
async def ai_generate_query_preview(
    req: AIGenerateQueryPreviewRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Generate + execute a recommended query and return a preview.

    Same generation/execution path as ask-and-run, but returns query metadata
    (title/description) so the Recommended Queries modal can preview then save.
    Non-fatal: returns a structured ``status`` on failure.
    """
    await _check_project_access(session, context, req.project_id)
    title = req.title or _shorten_ai_name(req.question)

    resolver = await _resolve_action_sources(
        session, context,
        project_id=req.project_id,
        question=req.question,
        intent="recommended_query",
        card_context=req.card_context,
    )

    try:
        ai_result = await _generate_sql_for_question(
            session, context, req.project_id, req.question,
            preferred_sources=resolver.preferred_sources,
            relevant_columns=resolver.relevant_columns,
        )
    except HTTPException as exc:
        friendly, details = _ai_generation_error(exc)
        return {
            "title": title,
            "description": req.description or "",
            "sql": "",
            "columns": [],
            "rows": [],
            "suggestedVisualization": {"type": "table"},
            "dataSourcesUsed": [],
            "explanation": "",
            "status": "generation_error",
            "error": friendly,
            "errorDetails": details,
        }

    allowed_tables = ai_result.pop("_allowed_tables", [])
    sql = (ai_result.get("sql") or "").strip().rstrip(";")
    if not sql or not _is_read_only_select(sql):
        return {
            "title": title,
            "description": req.description or "",
            "sql": sql if sql else "",
            "columns": [],
            "rows": [],
            "suggestedVisualization": {"type": "table"},
            "dataSourcesUsed": [],
            "explanation": ai_result.get("explanation", ""),
            "status": "generation_error",
            "error": "We could not safely build a query for this recommendation.",
            "errorDetails": {"sql": sql} if sql else {},
        }

    table_schema = await _project_table_schema(
        session, tenant_id=context.tenant_id, project_id=req.project_id
    )
    result, sql, exec_error = await _execute_with_repair(
        session, context,
        project_id=req.project_id,
        sql=sql,
        allowed_tables=allowed_tables,
        max_rows=req.max_rows,
        table_schema=table_schema,
    )
    if result is None:
        return {
            "title": title,
            "description": req.description or "",
            "sql": sql,
            "columns": [],
            "rows": [],
            "suggestedVisualization": {"type": "table"},
            "dataSourcesUsed": [_detect_datasource(sql, allowed_tables) or ""],
            "explanation": ai_result.get("explanation", ""),
            "status": "execution_error",
            "error": "We could not run this query against the project's data.",
            "errorDetails": {
                "sql": sql,
                "executionError": exec_error,
            },
        }

    columns = result.get("columns", [])
    rows = result.get("rows", [])[: req.max_rows]
    used = _detect_datasource(sql, allowed_tables)
    return {
        "title": title,
        "description": req.description or "",
        "sql": sql,
        "columns": columns,
        "rows": rows,
        "suggestedVisualization": _suggest_visualization(columns, rows),
        "dataSourcesUsed": [used] if used else [],
        "explanation": ai_result.get("explanation", ""),
        "status": "success",
        "error": None,
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

    # Step 1 — Plan: ask the AI server for an insight-first dashboard plan.
    payload = {
        "tenant_id": context.tenant_id,
        "user_id": context.user_id,
        "project_id": req.project_id,
        "prompt": req.prompt or "",
        "allowed_tables": allowed_tables,
        # Knowledge Graph context steers the plan toward validated risks, gaps,
        # measured/recommended KPIs, and governing documents.
        "knowledge_graph_context": await _kg_context(
            session, context, req.project_id,
        ),
    }
    ai_result = await _forward_to_ai("/ai/dashboard/suggest", payload)
    suggestions = ai_result.get("suggestions", [])

    if not suggestions:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="AI could not generate dashboard suggestions",
        )

    suggestion = suggestions[0]
    if req.name:
        dashboard_title = req.name
    elif req.prompt:
        dashboard_title = _shorten_ai_name(req.prompt)
    else:
        dashboard_title = suggestion.get("title", "AI - Dashboard")

    widget_defs = list(suggestion.get("widgets", []))
    # Highest-priority widgets first (executive reading path top-left → bottom-right).
    widget_defs.sort(key=lambda w: float(w.get("priority_score") or 0), reverse=True)

    # Step 2 — Judge: execute each widget's SQL and keep only the strong ones.
    from app.routes.query import (
        _auto_cast_aggregates,
        _resolve_vdb_database,
        _run_sql,
    )
    from app.services.tenant_teiid_resolver import TenantTeiidResolver

    judge_available = True
    teiid_host: str | None = None
    teiid_port: int | None = None
    vdb_database: str | None = None
    try:
        vdb_database = await _resolve_vdb_database(
            session=session, context=context, project_id=req.project_id
        )
        endpoint = await TenantTeiidResolver(session).resolve_for_org(context.tenant_id)
        teiid_host, teiid_port = endpoint.pg_host, endpoint.pg_port
    except Exception as exc:
        # No live VDB (data not materialised yet, or Teiid unavailable): skip the
        # execution-based judge rather than blocking dashboard creation.
        judge_available = False
        logger.warning("Dashboard judge skipped (no VDB): %s", exc)

    kept_defs: list[dict[str, Any]] = []
    dropped_widgets: list[dict[str, str]] = []
    # Widgets kept despite a failed/empty validation run, so the dashboard still
    # saves; they render with an inline "needs attention" state the user can fix.
    flagged_widgets: list[dict[str, str]] = []
    repair_count = 0

    for w in widget_defs:
        title = str(w.get("title", "untitled"))
        wtype = str(w.get("type", "bar")).lower()
        widget_sql = (w.get("sql", "") or "").strip().rstrip(";")

        # Narrative / no-SQL findings cannot be rendered as a dashboard chart.
        if not widget_sql or wtype in _NARRATIVE_TYPES:
            dropped_widgets.append(
                {"title": title, "reason": "narrative finding (no chart)"}
            )
            continue

        validation: dict[str, Any] = {
            "execution_status": "skipped",
            "row_count": 0,
            "columns_returned": [],
            "non_null_metric_count": 0,
            "chart_type_original": wtype,
            "chart_type_final": wtype,
            "sql_original": widget_sql,
            "sql_final": widget_sql,
            "warnings": [],
            "drop_reason": "",
        }

        if judge_available and vdb_database:
            try:
                result = await _run_sql(
                    database=vdb_database,
                    sql=_auto_cast_aggregates(widget_sql),
                    teiid_host=teiid_host,
                    teiid_port=teiid_port,
                )
            except Exception as exc:
                # A failed validation run must not silently delete a widget the
                # user previewed and chose to save. Keep it, flag it, and let the
                # dashboard render an inline error the user can repair.
                logger.warning(
                    "AI dashboard widget flagged (kept) | title=%s reason=%s sql=%s",
                    title, "query failed to execute", widget_sql,
                )
                logger.debug("Widget %r SQL error: %s", title, exc)
                validation.update(
                    {
                        "execution_status": "error",
                        "warnings": ["query failed to execute"],
                        "error": str(exc)[:500],
                    }
                )
                flagged_widgets.append(
                    {"title": title, "reason": "query failed to execute"}
                )
                w["_validation"] = validation
                kept_defs.append(w)
                continue
            cols = result.get("columns", [])
            rows = result.get("rows", [])
            keep, reason = _judge_widget(w, cols, rows)
            if not keep:
                # Weak/empty result: keep but flag rather than dropping, so the
                # previewed dashboard is still created.
                logger.info(
                    "AI dashboard widget flagged (kept) | title=%s reason=%s "
                    "row_count=%d columns=%s",
                    title, reason, len(rows), cols,
                )
                validation.update(
                    {
                        "execution_status": "weak",
                        "row_count": len(rows),
                        "columns_returned": cols,
                        "warnings": [reason],
                    }
                )
                flagged_widgets.append({"title": title, "reason": reason})
                w["_validation"] = validation
                kept_defs.append(w)
                continue
            _correct_widget_chart(w, cols, rows)
            final_type = str(w.get("type", wtype)).lower()
            if final_type != wtype:
                repair_count += 1
            vcol = w.get("value_column") or w.get("y_column") or ""
            non_null = 0
            if vcol:
                col_map = {_norm_col(c): c for c in cols}
                actual = col_map.get(_norm_col(vcol))
                if actual:
                    non_null = sum(1 for r in rows if r.get(actual) is not None)
            validation.update(
                {
                    "execution_status": "success",
                    "row_count": len(rows),
                    "columns_returned": cols,
                    "non_null_metric_count": non_null,
                    "chart_type_final": final_type,
                }
            )

        w["_validation"] = validation
        kept_defs.append(w)

    # Minimum-save rule: a dashboard needs at least one chartable widget. Widgets
    # whose validation query fails or returns weak data are kept (and flagged),
    # so the only widgets that count as unsavable are narrative/no-SQL findings.
    if len(kept_defs) < 1:
        detail = (
            "This suggestion has no chartable widgets to build a dashboard."
        )
        if dropped_widgets:
            detail += " Skipped: " + "; ".join(
                f"{d['title']} ({d['reason']})" for d in dropped_widgets[:6]
            )
        detail += (
            " Try a more specific request, or add data sources that support the "
            "metrics you want to see."
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail
        )

    # Step 3 — Build: for each surviving widget, reuse or create a SavedQuery.
    widgets_config: list[dict[str, Any]] = []
    created_queries: list[int] = []
    reused_queries: list[int] = []

    existing_queries_result = await session.scalars(
        select(SavedQuery).where(SavedQuery.project_id == project.id)
    )
    existing_queries = list(existing_queries_result)

    def _normalize_sql(sql: str) -> str:
        """Normalize SQL for comparison — collapse whitespace and lowercase."""
        return re.sub(r"\s+", " ", sql.strip().rstrip(";").lower())

    sql_to_query: dict[str, SavedQuery] = {}
    for eq in existing_queries:
        if eq.sql_text:
            sql_to_query[_normalize_sql(eq.sql_text)] = eq

    existing_with_sql = [eq for eq in existing_queries if eq.sql_text]

    async def _find_matching_query(widget_sql: str, widget_title: str) -> SavedQuery | None:
        """Use the dedicated /ai/query/match endpoint to find an equivalent query.

        Uses /ai/query/match (NOT the generic /ai/ask): the comparison is a
        purpose-built equivalence check that returns a structured match_id.
        """
        if not existing_with_sql:
            return None
        try:
            match_response = await _forward_to_ai("/ai/query/match", {
                "tenant_id": context.tenant_id,
                "user_id": context.user_id,
                "project_id": req.project_id,
                "candidate_title": widget_title,
                "candidate_sql": widget_sql,
                "existing_queries": [
                    {"id": eq.id, "name": eq.name, "sql": eq.sql_text}
                    for eq in existing_with_sql
                ],
            })
            match_id = match_response.get("match_id")
            if match_id is not None:
                for eq in existing_queries:
                    if eq.id == match_id:
                        return eq
        except Exception:
            logger.warning("AI query matching failed, will create new query")
        return None

    for idx, w in enumerate(kept_defs):
        widget_sql = (w.get("sql", "") or "").strip().rstrip(";")
        widget_title = str(w.get("title", f"Widget {idx + 1}"))
        widget_type = str(w.get("type", "bar"))
        aggregation = (w.get("aggregation") or "count").lower()
        x_col = w.get("label_column") or w.get("x_column") or ""
        y_col = w.get("value_column") or w.get("y_column") or ""
        y2_col = w.get("value_column_2") or ""

        # Tier 1: exact normalized SQL match.
        norm_sql = _normalize_sql(widget_sql)
        existing = sql_to_query.get(norm_sql)
        # Tier 2: AI semantic equivalence match.
        if not existing:
            existing = await _find_matching_query(widget_sql, widget_title)
        # Tier 3: name-based match.
        if not existing:
            candidate_name = f"AI - {widget_title}".lower().strip()
            for eq in existing_queries:
                if eq.name and eq.name.lower().strip() == candidate_name:
                    existing = eq
                    break

        if existing:
            reused_queries.append(existing.id)
            data_source: dict[str, Any] = {"kind": "query", "queryId": existing.id}
        else:
            left_ds = _detect_datasource(widget_sql, allowed_tables)
            query = SavedQuery(
                project_id=project.id,
                owner_id=context.user_id,
                name=f"AI - {widget_title}",
                description=str(w.get("business_question") or ""),
                sql_text=widget_sql,
                left_datasource=left_ds,
                ai_generated=True,
            )
            session.add(query)
            await session.flush()
            created_queries.append(query.id)
            data_source = {"kind": "query", "queryId": query.id}
            sql_to_query[norm_sql] = query
            existing_queries.append(query)

        base_type, subtype = _map_widget_visual(widget_type)
        default_w = {"kpi": 3, "table": 12, "pie": 5}.get(base_type, 6)
        default_h = {"kpi": 2, "table": 5}.get(base_type, 4)
        grid_w = int(w.get("gridW") or w.get("grid_w") or default_w)
        grid_h = int(w.get("gridH") or w.get("grid_h") or default_h)

        widget_conf: dict[str, Any] = {
            "id": f"ai_widget_{idx}",
            "title": widget_title,
            "type": base_type,
            "chartSubtype": subtype,
            # Preserve the planner's richer chart type so the UI can render it
            # natively later even though it maps to a base type for now.
            "aiChartType": widget_type,
            "dataSource": data_source,
            "xColumn": x_col,
            "yColumn": y_col,
            "aggregation": (
                aggregation
                if aggregation in ("sum", "avg", "count", "min", "max")
                else "count"
            ),
            "sortBy": "x_asc",
            "filters": [],
            "position": idx,
            "gridW": grid_w,
            "gridH": grid_h,
        }
        if y2_col:
            widget_conf["y2Column"] = y2_col

        # Per-widget execution validation metadata captured by the judge.
        validation_meta = w.get("_validation")
        if isinstance(validation_meta, dict):
            widget_conf["validation"] = validation_meta

        # Join-quality metadata when the widget uses a multi-table join.
        join_meta = _build_join_metadata(w)
        if join_meta is not None:
            widget_conf["joinMetadata"] = join_meta

        # Carry reference lines (thresholds/SLAs) the planner grounded in docs.
        ref_lines: list[dict[str, Any]] = []
        for rl in (w.get("reference_lines") or []):
            value = rl.get("value") if isinstance(rl, dict) else None
            if value is None:
                continue
            try:
                ref_lines.append(
                    {
                        "axis": "y",
                        "value": float(value),
                        "label": (rl.get("label") or rl.get("source_document") or ""),
                    }
                )
            except (TypeError, ValueError):
                continue
        if ref_lines:
            widget_conf["visualizationOptions"] = {"referenceLines": ref_lines}

        widgets_config.append(widget_conf)

    # Lay widgets out on the 12-column grid in priority order.
    _pack_grid(widgets_config)

    # Dashboard-level validation summary (doc §11). A simple quality score:
    # fraction of generated widgets that survived validation.
    approved_count = len(widgets_config)
    dropped_count = len(dropped_widgets)
    total_generated = approved_count + dropped_count
    quality_score = (
        round(approved_count / total_generated, 2) if total_generated else 0.0
    )
    validation_summary = (
        f"approved={approved_count} dropped={dropped_count} "
        f"repaired={repair_count} quality={quality_score}"
    )
    rejected_insights = list(suggestion.get("rejected_insights", []))

    logger.info(
        "AI dashboard validation | dashboard=%s approved=%d dropped=%d "
        "repaired=%d quality=%s",
        dashboard_title, approved_count, dropped_count, repair_count,
        quality_score,
    )

    # Step 4: Create the Dashboard
    dashboard = Dashboard(
        project_id=project.id,
        owner_id=context.user_id,
        tenant_id=context.tenant_id,
        name=dashboard_title,
        description=(
            req.description
            or suggestion.get("executive_summary")
            or req.prompt
            or ""
        ),
        status="draft",
        config={
            "widgets": widgets_config,
            "filters": [],
            "layout": "grid",
            "ai_generated": True,
            "generation_pipeline_version": "insight_first_v1",
            "business_domain": suggestion.get("business_domain", ""),
            "intended_audience": suggestion.get("intended_audience", ""),
            "executive_summary": suggestion.get("executive_summary", ""),
            "dashboard_quality_score": quality_score,
            "approved_widget_count": approved_count,
            "dropped_widget_count": dropped_count,
            "flagged_widget_count": len(flagged_widgets),
            "repair_count": repair_count,
            "rejected_insights": rejected_insights,
            "validation_summary": validation_summary,
        },
    )
    session.add(dashboard)
    await session.commit()
    await session.refresh(dashboard)

    logger.info(
        "AI action: generate_and_save_dashboard | dashboard_id=%d widgets=%d "
        "dropped=%d queries_created=%d queries_reused=%d project=%d tenant=%d user=%d",
        dashboard.id, len(widgets_config), len(dropped_widgets),
        len(created_queries), len(reused_queries), project.id,
        context.tenant_id, context.user_id,
    )
    return {
        "action": "generate_and_save_dashboard",
        "status": "saved",
        "dashboard_id": dashboard.id,
        "dashboard_name": dashboard_title,
        "widgets_created": len(widgets_config),
        "widgets_dropped": dropped_widgets,
        "widgets_flagged": flagged_widgets,
        "queries_created": created_queries,
        "queries_reused": reused_queries,
        "model_used": ai_result.get("model_used", ""),
    }


@router.post("/actions/suggest-dashboards")
async def ai_suggest_dashboards(
    req: AISuggestDashboardsRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Return >= 3 dashboard plan suggestions for a project (insight-first).

    Mirrors the Home "New Dashboard Suggestions" flow on the Dashboard page.
    These are previews only — nothing is saved. The user saves a chosen plan via
    the existing ``/actions/generate-and-save-dashboard`` pipeline, which runs the
    full SQL validation/judge and drops empty widgets.
    """
    await _check_project_access(session, context, req.project_id)

    # Allowed tables = the project's real datasources (reference docs excluded).
    ds_stmt = select(FileSourceMeta).where(
        FileSourceMeta.project_id == req.project_id,
        FileSourceMeta.tenant_id == context.tenant_id,
        FileSourceMeta.archived.is_(False),
    )
    ds_result = await session.execute(ds_stmt)
    allowed_tables = [ds.view_name for ds in ds_result.scalars()]

    # Real KPI names from the project graph (never invented).
    from app.models.ai_project_graph import AIProjectGraphNode

    kpi_rows = (
        await session.scalars(
            select(AIProjectGraphNode.name).where(
                AIProjectGraphNode.tenant_id == context.tenant_id,
                AIProjectGraphNode.project_id == req.project_id,
                AIProjectGraphNode.is_active.is_(True),
                AIProjectGraphNode.node_type.in_(("kpi", "metric")),
            )
        )
    ).all()
    kpis = [k for k in kpi_rows if k]

    kg_context = await _kg_context(session, context, req.project_id)

    desired = max(3, int(req.desired_count or 3))
    payload = {
        "tenant_id": context.tenant_id,
        "user_id": context.user_id,
        "project_id": req.project_id,
        "prompt": req.prompt or "",
        "audience": req.audience or "",
        "desired_count": desired,
        "allowed_tables": allowed_tables,
        "kpis": kpis,
        # Steer each preview toward the graph's risks/gaps/KPIs/governing docs.
        "knowledge_graph_context": kg_context,
    }
    ai_result = await _forward_to_ai("/ai/dashboard/suggest-multi", payload)
    raw_suggestions = ai_result.get("suggestions", []) or []

    # Compact, chip-friendly KG summary the FE renders on each preview card.
    kg_chips = _kg_context_chips(kg_context)

    # A runner bound to this project's VDB so each widget's SQL is executed and
    # turned into real, renderable chart series (same as the Home dashboard
    # suggestions). Previews are best-effort: a widget that fails or returns no
    # rows is still returned (status != "valid") so the preview never collapses.
    from app.routes.home_intelligence import _make_runner

    runner = _make_runner(session, context, req.project_id)

    suggestions: list[dict[str, Any]] = []
    for idx, s in enumerate(raw_suggestions):
        if not isinstance(s, dict):
            continue
        widgets = await _render_preview_widgets(runner, s.get("widgets", []))
        # Only surface allowed tables as data sources (defence in depth).
        data_sources = [
            str(d) for d in s.get("data_sources", []) if str(d) in allowed_tables
        ]
        title = str(s.get("title") or "AI Dashboard")
        description = str(s.get("description", ""))
        business_purpose = str(s.get("business_purpose", ""))
        audience = str(s.get("audience") or req.audience or "")
        kpi_names = [str(k) for k in s.get("kpis", []) if k]
        # savePayload is echoed back verbatim on Save so the save stage persists
        # *this* selected suggestion (its real widget SQL) rather than
        # re-deriving a plan from scratch.
        save_payload = {
            "title": title,
            "description": description,
            "businessPurpose": business_purpose,
            "audience": audience,
            "prompt": _suggestion_save_prompt(
                title, business_purpose, description, widgets, kpi_names
            ),
            "widgets": widgets,
            "kpis": kpi_names,
            "dataSources": data_sources,
        }
        suggestions.append(
            {
                "id": f"suggestion-{idx + 1}",
                "title": title,
                "description": description,
                "businessPurpose": business_purpose,
                "audience": audience,
                "widgets": widgets,
                "kpis": kpi_names,
                "dataSources": data_sources,
                "confidence": float(s.get("confidence") or 0.0),
                "qualityScore": int(s.get("quality_score") or 0),
                "validationSummary": "",
                "knowledgeGraphContext": kg_chips,
                "savePayload": save_payload,
            }
        )

    logger.info(
        "AI action: suggest_dashboards | count=%d project=%d tenant=%d user=%d",
        len(suggestions), req.project_id, context.tenant_id, context.user_id,
    )
    preview_note = (
        ""
        if suggestions
        else (
            "Tablescope could not build full dashboard previews from the current "
            "data. Refine the request or add more data sources, then try again."
        )
    )
    return {
        "action": "suggest_dashboards",
        "suggestions": suggestions,
        "previewNote": preview_note,
        "model_used": ai_result.get("model_used", ""),
    }


async def _render_preview_widgets(
    runner: Any, raw_widgets: list[Any]
) -> list[dict[str, Any]]:
    """Execute each plan widget's SQL and attach real, renderable chart data.

    Mirrors the Home "New Dashboard Suggestions" flow: the AI returns widget SQL
    grounded in the project's real tables, we run it against the project VDB and
    build a ``{label, value}`` chart series the FE renders with the same widget
    renderer the dashboard uses. Best-effort and side-effect free — a widget that
    has no SQL (narrative/risk/gap), fails to execute, or returns no rows is still
    returned with a non-``valid`` status so the preview never collapses to a
    "not enough strong widgets" error.
    """
    from app.services import home_intelligence as hi

    async def render(w: Any) -> dict[str, Any] | None:
        if not isinstance(w, dict):
            return None
        title = str(w.get("title", ""))
        chart_type = str(w.get("chart_type") or w.get("type") or "")
        business_question = str(w.get("business_question", ""))
        sql = (w.get("sql") or "").strip()
        label_col = str(w.get("label_column", ""))
        value_col = str(w.get("value_column", ""))
        widget: dict[str, Any] = {
            "title": title,
            "chartType": chart_type,
            "businessQuestion": business_question,
            "sql": sql,
            "labelColumn": label_col,
            "valueColumn": value_col,
            "chart": None,
            "previewData": {"columns": [], "rows": []},
            "status": "narrative" if not sql else "preview_only",
        }
        if not sql:
            return widget
        result = await hi._safe_query(runner, sql)
        if result and result.get("rows"):
            widget["previewData"] = {
                "columns": list(result.get("columns", [])),
                "rows": list(result.get("rows", []))[:100],
            }
            widget["status"] = "valid"
            chart = hi._build_chart(
                chart_type or "bar", title, result, label_col, value_col
            )
            if chart:
                widget["chart"] = chart
        return widget

    rendered = await asyncio.gather(
        *(render(w) for w in raw_widgets if isinstance(w, dict))
    )
    return [w for w in rendered if w]


def _suggestion_save_prompt(
    title: str,
    business_purpose: str,
    description: str,
    widgets: list[dict[str, Any]],
    kpis: list[str],
) -> str:
    """Build a focused prompt that pins the strict save stage to a chosen plan."""
    parts: list[str] = [p for p in (title, business_purpose, description) if p]
    for w in widgets:
        label = str(w.get("title") or "")
        question = str(w.get("businessQuestion") or "")
        if label or question:
            parts.append(": ".join(p for p in (label, question) if p))
    if kpis:
        parts.append("KPIs to cover: " + ", ".join(kpis))
    return ". ".join(parts)


@router.post("/actions/save-dashboard-suggestion")
async def ai_save_dashboard_suggestion(
    req: AISaveDashboardSuggestionRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Persist a previewed dashboard suggestion using strict save validation.

    Preview (``/actions/suggest-dashboards``) never persists and never raises the
    strict "needed 2, got N" error. Saving is a separate stage:

    * When the previewed suggestion carries executable widget SQL (the normal
      path now), persist exactly those widgets — each SQL is saved as a project
      query and referenced from the dashboard config — so the saved dashboard
      matches what the user previewed.
    * Otherwise fall back to the strict generate-and-save pipeline, which
      re-derives a plan from the prompt and drops widgets that fail to execute.
    """
    s = req.suggestion

    # Persist the previewed widgets directly when they carry runnable SQL.
    sql_widgets = [w for w in s.widgets if (w.sql or "").strip()]
    if sql_widgets:
        from app.routes.home_intelligence import (
            SaveDashboardRequest,
            SaveDashboardWidget,
            home_save_dashboard,
        )

        saved = await home_save_dashboard(
            SaveDashboardRequest(
                project_id=req.project_id,
                title=s.title or "AI Dashboard",
                widgets=[
                    SaveDashboardWidget(
                        title=w.title or "Widget",
                        sql=w.sql,
                        chartType=w.chartType or "bar",
                        labelColumn=w.labelColumn or None,
                        valueColumn=w.valueColumn or None,
                    )
                    for w in sql_widgets
                ],
            ),
            session=session,
            context=context,
        )
        dashboard_id = saved.get("dashboard_id")
        saved["action"] = "save_dashboard_suggestion"
        saved["suggestion_id"] = req.suggestionId
        saved["dashboard_name"] = saved.get("name")
        if dashboard_id is not None:
            saved["dashboard_url"] = (
                f"/projects/{req.project_id}/dashboards/{dashboard_id}"
            )
        logger.info(
            "AI action: save_dashboard_suggestion (direct) | dashboard_id=%s "
            "suggestion=%s widgets=%d project=%d tenant=%d user=%d",
            dashboard_id, req.suggestionId, len(sql_widgets), req.project_id,
            context.tenant_id, context.user_id,
        )
        return saved

    prompt = s.prompt or _suggestion_save_prompt(
        s.title,
        s.businessPurpose,
        s.description,
        [w.model_dump() for w in s.widgets],
        list(s.kpis),
    )
    saved = await ai_generate_and_save_dashboard(
        AIGenerateAndSaveDashboardRequest(
            project_id=req.project_id,
            prompt=prompt or None,
            name=s.title or None,
            description=s.description or None,
        ),
        session=session,
        context=context,
    )
    dashboard_id = saved.get("dashboard_id")
    saved["action"] = "save_dashboard_suggestion"
    saved["suggestion_id"] = req.suggestionId
    if dashboard_id is not None:
        saved["dashboard_url"] = (
            f"/projects/{req.project_id}/dashboards/{dashboard_id}"
        )
    logger.info(
        "AI action: save_dashboard_suggestion | dashboard_id=%s suggestion=%s "
        "project=%d tenant=%d user=%d",
        dashboard_id, req.suggestionId, req.project_id,
        context.tenant_id, context.user_id,
    )
    return saved


# Insight-first chart catalog → (dashboard WidgetType, ChartSubtype).
# The planner may request a rich type (horizontal_bar, dual_line, waterfall,
# bubble, …); the dashboard renderer expresses these as a base type plus a
# subtype, so map every planner type down to a supported pair.
_CHART_TYPE_MAP: dict[str, tuple[str, str]] = {
    "kpi": ("kpi", "kpi"),
    "kpi_grid": ("kpi", "kpi"),
    "bar": ("bar", "column"),
    "vertical_bar": ("bar", "column"),
    "horizontal_bar": ("bar", "horizontal_bar"),
    "stacked_bar": ("bar", "stacked_bar"),
    "grouped_bar": ("bar", "grouped_bar"),
    "waterfall": ("bar", "waterfall"),
    "bullet": ("bar", "horizontal_bar"),
    "line": ("line", ""),
    "dual_line": ("line", "biaxial_line"),
    "area": ("area", ""),
    "pie": ("pie", ""),
    "donut": ("pie", "donut"),
    "gauge": ("pie", "gauge"),
    "table": ("table", ""),
    "pivot_table": ("table", ""),
    "sparkline_table": ("table", ""),
    "heatmap": ("table", ""),
    "scatter": ("scatter", ""),
    "bubble": ("scatter", "bubble"),
    "treemap": ("treemap", ""),
    "funnel": ("funnel", ""),
    "radar": ("radar", ""),
}


def _map_widget_visual(ai_type: str) -> tuple[str, str]:
    """Map a planner chart type to a (WidgetType, ChartSubtype) pair."""
    return _CHART_TYPE_MAP.get((ai_type or "").lower(), ("bar", "column"))


def _map_chart_type(ai_type: str) -> str:
    """Map an AI-suggested chart type to the dashboard widget chart type."""
    return _map_widget_visual(ai_type)[0]


def _map_chart_subtype(ai_type: str) -> str:
    """Map an AI-suggested type to a chart subtype."""
    return _map_widget_visual(ai_type)[1]


def _build_join_metadata(widget: dict[str, Any]) -> dict[str, Any] | None:
    """Build join-quality metadata for a widget when it uses a join.

    Prefers the planner's ``relationship_plan``. If that is absent but the SQL
    contains a JOIN, emit best-effort metadata and flag it so the gap is
    visible. Returns None when the widget is single-table.
    """
    plan = widget.get("relationship_plan")
    sql = (widget.get("sql", "") or "")
    has_join = re.search(r"\bjoin\b", sql, re.IGNORECASE) is not None

    if isinstance(plan, dict) and (plan.get("requires_join") or has_join):
        return {
            "requiresJoin": bool(plan.get("requires_join") or has_join),
            "leftTable": str(plan.get("left_table") or ""),
            "rightTable": str(plan.get("right_table") or ""),
            "leftJoinKey": str(plan.get("left_join_key") or ""),
            "rightJoinKey": str(plan.get("right_join_key") or ""),
            "relationshipType": str(plan.get("relationship_type") or "unknown"),
            "joinConfidence": plan.get("join_confidence"),
            "confidenceReason": str(plan.get("confidence_reason") or ""),
            "rowMultiplicationRisk": str(plan.get("row_multiplication_risk") or ""),
            "validated": False,
            "matchRate": None,
            "rowMultiplicationRatio": None,
        }

    if has_join:
        logger.warning(
            "AI dashboard widget %r uses a JOIN with no relationship_plan; "
            "emitting best-effort join metadata",
            widget.get("title", "untitled"),
        )
        return {
            "requiresJoin": True,
            "leftTable": "",
            "rightTable": "",
            "leftJoinKey": "",
            "rightJoinKey": "",
            "relationshipType": "unknown",
            "joinConfidence": None,
            "confidenceReason": "inferred from SQL JOIN (no planner metadata)",
            "rowMultiplicationRisk": "unknown",
            "validated": False,
            "matchRate": None,
            "rowMultiplicationRatio": None,
        }

    return None


# ---------------------------------------------------------------------------
# Dashboard widget judge (executes each widget's SQL, drops empty/weak ones)
# ---------------------------------------------------------------------------

_TIME_SERIES_TYPES = frozenset({"line", "area", "dual_line"})
_PART_TO_WHOLE_TYPES = frozenset({"pie", "donut"})
_NARRATIVE_TYPES = frozenset({"narrative_insight", "none", "narrative"})


def _norm_col(name: str) -> str:
    return (name or "").strip().strip('"').lower()


def _judge_widget(
    widget: dict[str, Any], columns: list[str], rows: list[dict[str, Any]]
) -> tuple[bool, str]:
    """Decide whether an executed widget should be kept.

    Returns ``(keep, reason)``; ``reason`` explains the drop when ``keep`` is
    False. Mirrors the doc's judge rules: drop empty results, drop when the
    configured value column is missing/all-null, and drop time-series widgets
    with fewer than 3 periods.
    """
    wtype = str(widget.get("type", "bar")).lower()

    if not rows:
        return False, "returned no rows"

    vcol = widget.get("value_column") or widget.get("y_column") or ""
    if vcol:
        col_map = {_norm_col(c): c for c in columns}
        actual = col_map.get(_norm_col(vcol))
        if actual is None:
            return False, f"value column '{vcol}' missing from result"
        if all(r.get(actual) is None for r in rows):
            return False, f"value column '{vcol}' is entirely null"

    if wtype in _TIME_SERIES_TYPES and len(rows) < 3:
        return False, f"time-series needs >= 3 periods (got {len(rows)})"

    return True, ""


def _correct_widget_chart(
    widget: dict[str, Any], columns: list[str], rows: list[dict[str, Any]]
) -> None:
    """Apply safe in-place chart-type corrections after execution.

    - pie/donut with > 8 slices → horizontal_bar (ranking, not part-to-whole).
    - vertical bar with long category labels (or many bars) → horizontal_bar.
    """
    wtype = str(widget.get("type", "bar")).lower()

    if wtype in _PART_TO_WHOLE_TYPES and len(rows) > 8:
        widget["type"] = "horizontal_bar"
        return

    if wtype in ("bar", "vertical_bar"):
        lcol = widget.get("label_column") or widget.get("x_column") or ""
        col_map = {_norm_col(c): c for c in columns}
        actual = col_map.get(_norm_col(lcol))
        if actual:
            labels = [str(r.get(actual, "")) for r in rows[:20]]
            if labels:
                avg_len = sum(len(x) for x in labels) / len(labels)
                if avg_len > 16 or len(rows) > 8:
                    widget["type"] = "horizontal_bar"


def _pack_grid(widgets_config: list[dict[str, Any]]) -> None:
    """Lay widgets out left-to-right on a 12-column grid in priority order.

    KPI tiles are placed first across the top row; remaining widgets flow in a
    simple row-packing reading path. Mutates each widget's gridX/gridY/colSpan.
    """
    cursor_x = 0
    cursor_y = 0
    row_h = 0
    for w in widgets_config:
        gw = max(2, min(12, int(w.get("gridW") or 6)))
        gh = max(1, min(8, int(w.get("gridH") or 4)))
        if cursor_x + gw > 12:
            cursor_x = 0
            cursor_y += row_h
            row_h = 0
        w["gridX"] = cursor_x
        w["gridY"] = cursor_y
        w["gridW"] = gw
        w["gridH"] = gh
        w["colSpan"] = gw
        cursor_x += gw
        row_h = max(row_h, gh)


# ---------------------------------------------------------------------------
# Saved AI conversations (Home AI Assistant)
# ---------------------------------------------------------------------------


class ConversationCreate(BaseModel):
    title: str | None = None
    project_id: int | None = None


class ConversationRename(BaseModel):
    title: str


class ConversationMessageCreate(BaseModel):
    question: str
    project_id: int | None = None


def _message_dict(m: AiConversationMessage) -> dict[str, Any]:
    return {
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "data": m.data,
        "createdAt": m.created_at.isoformat() if m.created_at else None,
    }


def _chat_answer_text(question: str, run: dict[str, Any]) -> str:
    """Short natural-language answer for an executed chat query.

    Prefers the generator's plain-English explanation; otherwise states the
    single scalar result (KPI-style questions) or how many rows were returned.
    The full result table + chart are attached separately as structured data.
    """
    explanation = (run.get("explanation") or "").strip()
    columns = run.get("columns") or []
    rows = run.get("rows") or []
    if not rows:
        return explanation or "The query ran but returned no rows."
    if len(rows) == 1 and len(columns) == 1:
        value = rows[0].get(columns[0])
        scalar = f"{columns[0]}: {value}"
        return f"{explanation}\n\n{scalar}".strip() if explanation else scalar
    summary = f"Here are the results ({len(rows)} rows)."
    return f"{explanation}\n\n{summary}".strip() if explanation else summary


def _conversation_dict(
    c: AiConversation, *, include_messages: bool = False
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": c.id,
        "title": c.title,
        "projectId": c.project_id,
        "parentConversationId": c.parent_conversation_id,
        "branchedFromMessageId": c.branched_from_message_id,
        "createdAt": c.created_at.isoformat() if c.created_at else None,
        "updatedAt": c.updated_at.isoformat() if c.updated_at else None,
    }
    if include_messages:
        data["messages"] = [_message_dict(m) for m in c.messages]
    return data


async def _get_owned_conversation(
    session: AsyncSession,
    context: RequestContext,
    conversation_id: int,
    *,
    with_messages: bool = False,
) -> AiConversation:
    stmt = select(AiConversation).where(
        AiConversation.id == conversation_id,
        AiConversation.tenant_id == context.tenant_id,
        AiConversation.user_id == context.user_id,
    )
    if with_messages:
        stmt = stmt.options(selectinload(AiConversation.messages))
    convo = (await session.execute(stmt)).scalar_one_or_none()
    if convo is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return convo


async def _default_project_id(
    session: AsyncSession, context: RequestContext
) -> int | None:
    member_sub = select(ProjectMember.project_id).where(
        ProjectMember.user_id == context.user_id,
        ProjectMember.is_active.is_(True),
    )
    return await session.scalar(
        select(Project.id)
        .where(
            Project.tenant_id == context.tenant_id,
            or_(
                Project.owner_id == context.user_id,
                Project.id.in_(member_sub),
            ),
        )
        .order_by(Project.updated_at.desc())
        .limit(1)
    )


@router.get("/conversations")
async def list_conversations(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[dict[str, Any]]:
    """List the caller's saved AI conversations (most recent first)."""
    rows = list(
        await session.scalars(
            select(AiConversation)
            .where(
                AiConversation.tenant_id == context.tenant_id,
                AiConversation.user_id == context.user_id,
            )
            .order_by(AiConversation.updated_at.desc())
        )
    )
    return [_conversation_dict(c) for c in rows]


@router.post("/conversations")
async def create_conversation(
    req: ConversationCreate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Create a new (empty) conversation."""
    project_id = req.project_id
    if project_id is not None:
        await _check_project_access(session, context, project_id)
    convo = AiConversation(
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        project_id=project_id,
        title=(req.title or "New conversation")[:255],
    )
    session.add(convo)
    await session.commit()
    await session.refresh(convo)
    data = _conversation_dict(convo)
    data["messages"] = []
    return data


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Fetch a conversation with its full message history."""
    convo = await _get_owned_conversation(
        session, context, conversation_id, with_messages=True
    )
    return _conversation_dict(convo, include_messages=True)


@router.put("/conversations/{conversation_id}")
async def rename_conversation(
    conversation_id: int,
    req: ConversationRename,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Rename a conversation."""
    convo = await _get_owned_conversation(session, context, conversation_id)
    convo.title = req.title.strip()[:255] or convo.title
    await session.commit()
    await session.refresh(convo)
    return _conversation_dict(convo)


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> Response:
    """Delete a conversation and its messages."""
    convo = await _get_owned_conversation(session, context, conversation_id)
    await session.delete(convo)
    await session.commit()
    return Response(status_code=204)


@router.post("/conversations/{conversation_id}/messages")
async def add_conversation_message(
    conversation_id: int,
    req: ConversationMessageCreate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Append a user message, get an AI answer, and persist both."""
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is required")

    convo = await _get_owned_conversation(
        session, context, conversation_id, with_messages=True
    )

    # Prior turns (oldest→newest) so the AI can resolve follow-up references
    # like "explain more" or "the second option" without the user restating
    # context. Captured before the new user message is appended.
    history = [
        {"role": m.role, "content": m.content}
        for m in convo.messages[-CONVERSATION_HISTORY_LIMIT:]
        if (m.content or "").strip()
    ]

    # Resolve the project used to scope the AI answer.
    project_id = req.project_id or convo.project_id
    if project_id is not None:
        await _check_project_access(session, context, project_id)
    else:
        project_id = await _default_project_id(session, context)
    if project_id is not None and convo.project_id != project_id:
        convo.project_id = project_id

    # First user message becomes the conversation title.
    if not convo.messages:
        convo.title = question[:120]

    user_msg = AiConversationMessage(
        conversation_id=convo.id, role="user", content=question
    )
    session.add(user_msg)

    answer: str
    answer_data: dict[str, Any] | None = None
    if _is_query_summary_request(question):
        # Answered directly from the DB across all accessible projects — no
        # AI-server call, so it never fails with a signature error and always
        # reflects the caller's real authorized queries.
        answer = await _build_query_summary(session, context)
    elif project_id is None:
        answer = (
            "I couldn't find a project to ground my answer. Create a project "
            "with data first, then ask again."
        )
    else:
        # Answer data questions the same way the Project Insight page does:
        # auto-resolve the source, generate + execute SQL, and return the real
        # result (rows + suggested chart) rather than printing SQL. If the
        # question isn't a data question the source can ground (e.g. a document
        # or summary request), fall back to the free-text AI answer.
        run = await _ask_and_run_core(
            session, context,
            project_id=project_id,
            question=question,
            max_rows=CHAT_ANSWER_MAX_ROWS,
        )
        if run.get("status") == "success":
            answer = _chat_answer_text(question, run)
            answer_data = {
                "sql": run.get("sql", ""),
                "columns": run.get("columns", []),
                "rows": run.get("rows", []),
                "suggestedVisualization": run.get(
                    "suggestedVisualization", {"type": "table"}
                ),
                "explanation": run.get("explanation", ""),
                "dataSourcesUsed": run.get("dataSourcesUsed", []),
            }
        else:
            answer = await _forward_prose_answer(
                context,
                project_id=project_id,
                question=question,
                history=history,
            ) or "The AI returned an empty response."

    assistant_msg = AiConversationMessage(
        conversation_id=convo.id, role="assistant", content=answer,
        data=answer_data,
    )
    session.add(assistant_msg)
    await session.commit()

    # Vectorize the Q+A pair for future learning/retrieval.
    try:
        await _forward_to_ai("/ai/index/conversation", {
            "tenant_id": context.tenant_id,
            "user_id": context.user_id,
            "project_id": project_id,
            "conversation_id": convo.id,
            "question": question,
            "answer": answer,
        })
    except Exception:
        pass  # best-effort — don't block the response

    # Expire the (stale, empty) messages collection so the re-query below
    # actually reloads it with the just-appended user/assistant pair — without
    # this the identity-mapped object would return its earlier-loaded state.
    session.expire(convo, ["messages"])
    refreshed = await _get_owned_conversation(
        session, context, conversation_id, with_messages=True
    )
    return _conversation_dict(refreshed, include_messages=True)


class ConversationBranchCreate(BaseModel):
    # When omitted, the branch forks from the last message of the source.
    message_id: int | None = None
    title: str | None = None


@router.post("/conversations/{conversation_id}/branch")
async def branch_conversation(
    conversation_id: int,
    req: ConversationBranchCreate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Fork a new conversation from a point in an existing one.

    Copies every message up to and including ``message_id`` into a fresh
    conversation that records its parent + the branch point, so the user can
    explore an alternative direction without disturbing the original thread.
    """
    source = await _get_owned_conversation(
        session, context, conversation_id, with_messages=True
    )
    if req.message_id is None:
        # Branch from the tail of the thread.
        if not source.messages:
            raise HTTPException(
                status_code=400, detail="Cannot branch an empty conversation"
            )
        branch_point: AiConversationMessage = source.messages[-1]
    else:
        found: AiConversationMessage | None = None
        for _m in source.messages:
            if _m.id == req.message_id:
                found = _m
                break
        if found is None:
            raise HTTPException(
                status_code=404,
                detail="Branch message not found in conversation",
            )
        branch_point = found

    title = (req.title or "").strip() or f"Branch of {source.title}"
    branch = AiConversation(
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        project_id=source.project_id,
        title=title[:255],
        parent_conversation_id=source.id,
        branched_from_message_id=branch_point.id,
    )
    session.add(branch)
    await session.flush()

    for m in source.messages:
        session.add(
            AiConversationMessage(
                conversation_id=branch.id, role=m.role, content=m.content,
                data=m.data,
            )
        )
        if m.id == branch_point.id:
            break

    await session.commit()
    refreshed = await _get_owned_conversation(
        session, context, branch.id, with_messages=True
    )
    return _conversation_dict(refreshed, include_messages=True)
