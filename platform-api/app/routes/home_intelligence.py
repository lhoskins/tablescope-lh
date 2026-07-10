"""Home AI Intelligence routes — per-project diagnostic suite + SSE feed.

- ``POST /api/ai/run-intelligence-suite`` runs the suite for a single project
  (used by the report viewer to re-execute on open).
- ``GET  /api/ai/home-intelligence/stream`` streams per-project results as
  Server-Sent Events so cards appear as each project finishes.

Every run is written to ``audit_events`` (event_type ``home_intelligence``) so
the project Audit Log reflects exactly which tables/documents were read.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import SessionLocal, get_db
from app.models.audit_event import AuditEvent
from app.models.dashboard import Dashboard
from app.models.file_source_meta import FileSourceMeta
from app.models.intelligence_snapshot import IntelligenceSnapshot
from app.models.project import Project, ProjectMember
from app.models.saved_query import SavedQuery
from app.routes.query import _auto_cast_aggregates, _resolve_vdb_database, _run_sql
from app.services import home_intel_queue as q
from app.services import home_intelligence as hi
from app.services.ai_intelligence_client import AIUnavailableError
from app.services.presentation_engine import PresentationMode
from app.services.response_envelope import attach_envelope
from app.services.tenant_teiid_resolver import TenantTeiidResolver
from app.tasks.workflows import enqueue_analyze_project_intelligence

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["AI Intelligence"])

# SSE consumer loop: how long to wait between store polls (a pub/sub wakeup
# cuts this short) and the overall wall-clock cap before the stream gives up
# waiting (the run still finishes server-side and the snapshot is written).
_STREAM_POLL_SECONDS = 1.0
_STREAM_DEADLINE_SECONDS = 1800.0


async def _accessible_projects(
    session: AsyncSession, context: RequestContext
) -> list[Project]:
    member_sub = select(ProjectMember.project_id).where(
        ProjectMember.user_id == context.user_id,
        ProjectMember.is_active.is_(True),
    )
    rows = await session.scalars(
        select(Project)
        .where(
            Project.tenant_id == context.tenant_id,
            or_(
                Project.owner_id == context.user_id,
                Project.id.in_(member_sub),
            ),
        )
        .order_by(Project.updated_at.desc())
    )
    return list(rows)


def _make_runner(
    session: AsyncSession, context: RequestContext, project_id: int
):
    """Build an async ``runner(sql) -> {columns, rows}`` bound to a project VDB.

    Returns ``None`` if the project has no active VDB to query (file/db sources
    not yet materialised), so prompts that need live data are skipped cleanly.
    """

    async def runner(sql: str) -> dict[str, Any]:
        database = await _resolve_vdb_database(
            session=session, context=context, project_id=project_id
        )
        endpoint = await TenantTeiidResolver(session).resolve_for_org(
            context.tenant_id
        )
        return await _run_sql(
            database=database,
            sql=_auto_cast_aggregates(sql),
            teiid_host=endpoint.pg_host,
            teiid_port=endpoint.pg_port,
        )

    return runner


async def _run_for_project(
    session: AsyncSession,
    context: RequestContext,
    project: Project,
    prompt_types: list[str],
    *,
    write_audit: bool = True,
    granularity: int = 3,
    plan_semaphore: asyncio.Semaphore | None = None,
) -> list[dict[str, Any]]:
    started = datetime.now(UTC)
    ctx = await hi.gather_project_context(session, project)
    runner = _make_runner(session, context, project.id)

    # Only the AI-driven analyst loop (plan -> execute real SQL -> interpret).
    # A disabled AI feature degrades to no cards; an enabled-but-unavailable AI
    # must bubble to the SSE project_error branch instead of looking like a valid
    # empty result.
    cards: list[dict[str, Any]] | None = None
    try:
        cards = await hi.run_ai_intelligence(
            project,
            ctx,
            runner,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            granularity=granularity,
            plan_semaphore=plan_semaphore,
        )
    except AIUnavailableError:
        raise
    except Exception as exc:
        logger.warning("AI intelligence failed for project %s: %s", project.id, exc)
        cards = None
    if cards is None:
        cards = []

    if write_audit and cards:
        duration_ms = int(
            (datetime.now(UTC) - started).total_seconds() * 1000
        )
        for card in cards:
            session.add(
                AuditEvent(
                    tenant_id=context.tenant_id,
                    project_id=project.id,
                    user_id=context.user_id,
                    event_type="home_intelligence",
                    prompt_type=card.get("insightType"),
                    scope="home_intelligence",
                    title=card.get("title"),
                    tables_queried=card.get("sources", {}).get("tables", []),
                    documents_read=card.get("sources", {}).get("documents", []),
                    duration_ms=duration_ms,
                )
            )
        await session.commit()
    return cards


# ─────────────────────────────────────────────────────────────────────────────
# Single-project suite (report refresh / on-demand)
# ─────────────────────────────────────────────────────────────────────────────

class RunSuiteRequest(BaseModel):
    project_id: int
    prompt_types: list[str] | None = None
    granularity: int = 3


@router.post("/run-intelligence-suite")
async def run_intelligence_suite(
    req: RunSuiteRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Run the diagnostic suite for one project the caller can access."""
    project = await session.get(Project, req.project_id)
    if (
        project is None
        or project.tenant_id != context.tenant_id
        or not await _has_access(session, context, project)
    ):
        return {"projectId": str(req.project_id), "insights": [], "error": "no_access"}

    prompts = req.prompt_types or hi.ALL_PROMPT_TYPES
    cards = await _run_for_project(
        session, context, project, prompts, granularity=req.granularity
    )
    return {
        "projectId": str(project.id),
        "projectName": project.name,
        "projectColor": hi.project_color(project.id),
        "insights": cards,
    }


async def _has_access(
    session: AsyncSession, context: RequestContext, project: Project
) -> bool:
    if project.owner_id == context.user_id:
        return True
    member = await session.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == context.user_id,
            ProjectMember.is_active.is_(True),
        )
    )
    return member is not None


# ─────────────────────────────────────────────────────────────────────────────
# SSE stream — runs all accessible projects, streams as each completes
# ─────────────────────────────────────────────────────────────────────────────

def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


@router.get("/home-intelligence/stream")
async def home_intelligence_stream(
    cross_project: bool = True,
    granularity: int = 3,
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> StreamingResponse:
    """Stream per-project intelligence as Server-Sent Events.

    Each project runs in its own DB session so a slow project never blocks the
    others, and results are enqueued the moment a project finishes.
    """

    async def event_stream() -> AsyncIterator[str]:
        # Resolve accessible projects up front in a short-lived session.
        async with SessionLocal() as session:
            projects = await _accessible_projects(session, context)

        if not projects:
            yield _sse({"type": "done", "projectCount": 0})
            return

        project_meta = [
            {"id": str(p.id), "name": p.name, "color": hi.project_color(p.id)}
            for p in projects
        ]
        yield _sse({"type": "start", "projects": project_meta})

        # Move per-project analysis off the request path into the durable
        # Redis + arq queue: register the run, enqueue one job per project,
        # then stream results as workers write them to the per-run store. The
        # workers own synthesis + snapshot persistence, so the run completes
        # (and the snapshot is written) even if this SSE connection drops.
        run_id = uuid.uuid4().hex
        await q.create_run(
            run_id=run_id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            granularity=granularity,
            cross_project=cross_project,
            projects=project_meta,
        )
        for p in projects:
            await enqueue_analyze_project_intelligence(
                tenant_id=context.tenant_id,
                user_id=context.user_id,
                project_id=p.id,
                granularity=granularity,
                run_id=run_id,
            )

        emitted: set[str] = set()
        deadline = asyncio.get_event_loop().time() + _STREAM_DEADLINE_SECONDS
        async with q.subscribe(run_id) as pubsub:
            while True:
                results = await q.get_results(run_id)
                for pid, result in results.items():
                    if pid in emitted:
                        continue
                    emitted.add(pid)
                    if "insights" in result:
                        yield _sse({"type": "project_complete", **result})
                    else:
                        yield _sse({"type": "project_error", **result})

                stored, synthesis = await q.get_synthesis(run_id)
                if stored:
                    if cross_project and synthesis is not None:
                        yield _sse(
                            {"type": "synthesis_complete", "synthesis": synthesis}
                        )
                    break
                if asyncio.get_event_loop().time() > deadline:
                    logger.warning(
                        "home-intel stream %s timed out after %ss with %s/%s "
                        "projects reported",
                        run_id,
                        _STREAM_DEADLINE_SECONDS,
                        len(emitted),
                        len(projects),
                    )
                    break
                await q.wait_for_wakeup(pubsub, timeout=_STREAM_POLL_SECONDS)

        yield _sse({"type": "done", "projectCount": len(projects)})

    # ``X-Accel-Buffering: no`` tells nginx to stream this response unbuffered.
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot — persist the latest completed run; hydrate instantly on open
# ─────────────────────────────────────────────────────────────────────────────

async def _save_snapshot(
    context: RequestContext,
    granularity: int,
    payload: dict[str, Any],
    *,
    failed_project_count: int = 0,
) -> None:
    """Upsert the caller's single latest intelligence snapshot.

    Results are *merged* with the prior snapshot rather than replacing it: the
    new run's per-project results win, but any project that produced no fresh
    result this run (because it ended terminally errored, or the run drained
    before it finished) keeps its previous entry. This guarantees a partial or
    failed refresh never wipes a good prior result with a blank one. The merge
    is scoped to the projects the current run actually covered, so results for
    projects the caller can no longer access are dropped.
    """
    async with SessionLocal() as session:
        snap = await session.scalar(
            select(IntelligenceSnapshot).where(
                IntelligenceSnapshot.user_id == context.user_id
            )
        )
        prior_results = (snap.payload.get("results") or []) if snap else []
        new_results = payload.get("results") or []
        merged: dict[str, dict[str, Any]] = {
            str(r.get("projectId")): r for r in prior_results
        }
        for r in new_results:
            merged[str(r.get("projectId"))] = r
        current_ids = {str(p.get("id")) for p in (payload.get("projects") or [])}
        if current_ids:
            merged = {
                pid: r for pid, r in merged.items() if pid in current_ids
            }
        if failed_project_count:
            logger.info(
                "home intelligence snapshot for user %s finalized with %s project "
                "failure(s); merged %s new result(s) over %s prior into %s total",
                context.user_id,
                failed_project_count,
                len(new_results),
                len(prior_results),
                len(merged),
            )
        payload = {**payload, "results": list(merged.values())}
        if snap is None:
            snap = IntelligenceSnapshot(
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
            session.add(snap)
        snap.tenant_id = context.tenant_id
        snap.granularity = granularity
        snap.payload = payload
        await session.commit()


@router.get("/home-intelligence/snapshot")
async def get_intelligence_snapshot(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Return the caller's latest persisted run (or ``snapshot: null``)."""
    snap = await session.scalar(
        select(IntelligenceSnapshot).where(
            IntelligenceSnapshot.user_id == context.user_id
        )
    )
    if snap is None:
        return {"snapshot": None}
    return {
        "snapshot": {
            "granularity": snap.granularity,
            "updatedAt": snap.updated_at.isoformat() if snap.updated_at else None,
            **snap.payload,
        }
    }


# ─────────────────────────────────────────────────────────────────────────────
# Home AI suggestions — the three hero pills (New Query / New Dashboard /
# Insights & Opportunities). All AI-driven (no hard-coded metrics), run across
# every accessible project while keeping per-project data isolation: each
# project resolves its own VDB and is planned/queried independently. Results are
# generated in memory and returned for preview; nothing is persisted unless the
# user explicitly saves (save-query / save-dashboard below).
# ─────────────────────────────────────────────────────────────────────────────


class SuggestRequest(BaseModel):
    max_per_project: int = 5
    granularity: int = 3


class ProjectDashboardRequest(BaseModel):
    project_id: int
    max_widgets: int = 6
    granularity: int = 3


async def _project_for_access(
    session: AsyncSession, context: RequestContext, project_id: int
) -> Project:
    """Fetch one project the caller can access, or raise 404 (tenant-scoped)."""
    member_sub = select(ProjectMember.project_id).where(
        ProjectMember.user_id == context.user_id,
        ProjectMember.is_active.is_(True),
    )
    project = await session.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.tenant_id == context.tenant_id,
            or_(
                Project.owner_id == context.user_id,
                Project.id.in_(member_sub),
            ),
        )
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _plan_analyses(
    session: AsyncSession,
    context: RequestContext,
    project: Project,
    *,
    max_analyses: int,
    granularity: int,
) -> list[dict[str, Any]]:
    """Ask the AI to plan high-value analyses (with SQL) for one project."""
    from app.services import ai_intelligence_client as ai

    ctx = await hi.gather_project_context(session, project)
    allowed_tables = [t.view_name for t in ctx.tables]
    table_schema = [
        {
            "table": t.view_name,
            "storage": "text" if t.kind == "file" else "native",
            "columns": [{"name": n, "type": ty} for (n, ty) in t.columns],
        }
        for t in ctx.tables
    ]
    documents = [
        {
            "title": d.title,
            "summary": d.ai_summary or "",
            "tags": [
                str(t)
                for t in (d.ai_metadata.get("tags") or [])
                if isinstance(t, str | int | float)
            ],
        }
        for d in ctx.documents
    ]
    analyses = await ai.plan(
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        project_id=project.id,
        allowed_tables=allowed_tables,
        documents=documents,
        table_schema=table_schema,
        max_analyses=max_analyses,
        granularity=granularity,
    )
    return analyses or []


@router.post("/home/query-suggestions")
async def home_query_suggestions(
    req: SuggestRequest,
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """AI-suggested queries for every accessible project (in memory, unsaved)."""
    async with SessionLocal() as session:
        projects = await _accessible_projects(session, context)
    if not projects:
        return {"projects": []}

    async def work(project: Project) -> dict[str, Any]:
        analyses: list[dict[str, Any]] = []
        async with SessionLocal() as session:
            try:
                analyses = await _plan_analyses(
                    session,
                    context,
                    project,
                    max_analyses=req.max_per_project,
                    granularity=req.granularity,
                )
            except Exception as exc:
                logger.warning(
                    "query suggestions failed for project %s: %s", project.id, exc
                )
        suggestions = [
            {
                "title": a.get("title") or "Query",
                "description": a.get("rationale") or "",
                "sql": (a.get("sql") or "").strip(),
            }
            for a in analyses
            if (a.get("sql") or "").strip()
        ][: req.max_per_project]
        return {
            "projectId": str(project.id),
            "projectName": project.name,
            "projectColor": hi.project_color(project.id),
            "suggestions": suggestions,
        }

    results = await asyncio.gather(*(work(p) for p in projects))
    return {"projects": list(results)}


@router.post("/home/dashboard-suggestions")
async def home_dashboard_suggestions(
    req: SuggestRequest,
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """AI-suggested dashboards for every accessible project.

    The plan's SQL is executed server-side against each project's own VDB and
    turned into renderable chart series so the Home can render the dashboard
    from memory. Nothing is saved until the user clicks Save.
    """
    async with SessionLocal() as session:
        projects = await _accessible_projects(session, context)
    if not projects:
        return {"projects": []}

    async def work(project: Project) -> dict[str, Any]:
        widgets: list[dict[str, Any]] = []
        async with SessionLocal() as session:
            runner = _make_runner(session, context, project.id)
            ctx = await hi.gather_project_context(session, project)
            try:
                executed = await hi.plan_and_execute_widgets(
                    project,
                    ctx,
                    runner,
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                    max_analyses=req.max_per_project,
                    granularity=req.granularity,
                )
            except Exception as exc:
                logger.warning(
                    "dashboard suggestions failed for project %s: %s",
                    project.id,
                    exc,
                )
                executed = []
            for a in executed:
                result = a["result"]
                chart = hi._build_chart(
                    a.get("chart_type", "bar"),
                    a.get("title", ""),
                    result,
                    a.get("label_column", ""),
                    a.get("value_column", ""),
                )
                if not chart:
                    continue
                widgets.append(
                    {
                        "title": a.get("title") or "Widget",
                        "chartType": a.get("chart_type", "bar"),
                        "chart": chart,
                        "sql": a.get("sql", ""),
                        "labelColumn": a.get("label_column", ""),
                        "valueColumn": a.get("value_column", ""),
                    }
                )
        return {
            "projectId": str(project.id),
            "projectName": project.name,
            "projectColor": hi.project_color(project.id),
            "dashboard": (
                {"title": f"{project.name} — AI Dashboard", "widgets": widgets}
                if widgets
                else None
            ),
        }

    results = await asyncio.gather(*(work(p) for p in projects))
    return {"projects": list(results)}


@router.post("/home/project-dashboard")
async def home_project_dashboard(
    req: ProjectDashboardRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Generate a real, chart-rendered dashboard for ONE project.

    Mirrors the Home "New Dashboard Suggestions" flow (plan → execute real SQL →
    build renderable chart series) but scoped to a single project, so the Project
    Insight page can generate a working dashboard instead of a preview. Widgets
    whose SQL does not execute or returns no rows are dropped (never surfaced as
    preview-only). Nothing is saved until the user clicks Save.
    """
    project = await _project_for_access(session, context, req.project_id)
    runner = _make_runner(session, context, project.id)
    ctx = await hi.gather_project_context(session, project)
    widgets: list[dict[str, Any]] = []
    try:
        executed = await hi.plan_and_execute_widgets(
            project,
            ctx,
            runner,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            max_analyses=req.max_widgets,
            granularity=req.granularity,
        )
    except Exception as exc:
        logger.warning(
            "project dashboard plan failed for project %s: %s",
            project.id,
            exc,
        )
        executed = []
    for a in executed:
        sql = a.get("sql", "")
        result = a["result"]
        chart = hi._build_chart(
            a.get("chart_type", "bar"),
            a.get("title", ""),
            result,
            a.get("label_column", ""),
            a.get("value_column", ""),
        )
        if not chart:
            continue
        value_label = a.get("value_column", "") or ""
        hi.enhance_bar_readability(chart)
        fmt = hi._detect_value_format(
            value_label, chart.get("data", {}).get("series") or []
        )
        explanation = hi.build_widget_explanation(chart, value_label, fmt)
        # Persist the horizontal orientation we chose so the saved dashboard
        # renders the same readable chart, not a jumbled vertical bar.
        chart_type_out = (
            "horizontal_bar"
            if chart.get("type") == "bar"
            and chart.get("subtype") == "horizontal_bar"
            else a.get("chart_type", "bar")
        )
        widgets.append(
            {
                "title": a.get("title") or "Widget",
                "subtitle": a.get("rationale") or "",
                "explanation": explanation,
                "format": fmt,
                "chartType": chart_type_out,
                "chart": chart,
                "sql": sql,
                "labelColumn": a.get("label_column", ""),
                "valueColumn": value_label,
            }
        )

    narrative = hi.build_dashboard_narrative(widgets)
    dashboard = (
        {
            "title": f"{project.name} — AI Dashboard",
            "summary": narrative["summary"],
            "keyFindings": narrative["keyFindings"],
            "recommendedActions": narrative["recommendedActions"],
            "widgets": widgets,
        }
        if widgets
        else None
    )
    response: dict[str, Any] = {
        "projectId": str(project.id),
        "projectName": project.name,
        "projectColor": hi.project_color(project.id),
        "dashboard": dashboard,
    }
    # M4 fast-follow (surface 6): a generated dashboard is the `dashboard` mode —
    # stamp the shared ResponseEnvelope so the modal renders via the same
    # ResponsePresenter as the other surfaces. Additive/fail-closed; the modal
    # falls back to its legacy body when the envelope is absent.
    if dashboard is not None:
        attach_envelope(
            response,
            PresentationMode.DASHBOARD,
            executive_summary=narrative["summary"] or None,
            key_findings=narrative["keyFindings"] or None,
            recommended_actions=narrative["recommendedActions"] or None,
            chart_cards=widgets or None,
        )
    return response


@router.post("/home/insights")
async def home_insights(
    req: SuggestRequest,
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """AI insights & opportunities for every accessible project (in memory)."""
    async with SessionLocal() as session:
        projects = await _accessible_projects(session, context)
    if not projects:
        return {"projects": []}

    async def work(project: Project) -> dict[str, Any]:
        cards: list[dict[str, Any]] = []
        async with SessionLocal() as session:
            try:
                cards = await _run_for_project(
                    session,
                    context,
                    project,
                    hi.ALL_PROMPT_TYPES,
                    write_audit=False,
                    granularity=req.granularity,
                )
            except Exception as exc:
                logger.warning(
                    "insights failed for project %s: %s", project.id, exc
                )
        return {
            "projectId": str(project.id),
            "projectName": project.name,
            "projectColor": hi.project_color(project.id),
            "insights": cards,
        }

    results = await asyncio.gather(*(work(p) for p in projects))
    return {"projects": list(results)}


# ── Save a suggestion (explicit user action) ─────────────────────────


class SaveDashboardWidget(BaseModel):
    title: str
    sql: str
    chartType: str = "bar"
    explanation: str | None = None
    labelColumn: str | None = None
    valueColumn: str | None = None


class SaveDashboardRequest(BaseModel):
    project_id: int
    title: str
    widgets: list[SaveDashboardWidget]
    summary: str | None = None
    keyFindings: list[str] = []
    recommendedActions: list[str] = []


@router.post("/home/save-dashboard")
async def home_save_dashboard(
    req: SaveDashboardRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Persist an in-memory dashboard suggestion as a real dashboard.

    Each widget's SQL is saved as a project query (reusing an existing one when
    the SQL matches) and referenced from the dashboard's widget config.
    """
    from app.routes.ai_proxy import (
        _detect_datasource,
        _map_chart_subtype,
        _map_chart_type,
    )

    project = await session.get(Project, req.project_id)
    if (
        project is None
        or project.tenant_id != context.tenant_id
        or not await _has_access(session, context, project)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Project not accessible"
        )
    if not req.widgets:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Dashboard has no widgets to save",
        )

    ds_result = await session.execute(
        select(FileSourceMeta).where(
            FileSourceMeta.project_id == req.project_id,
            FileSourceMeta.tenant_id == context.tenant_id,
            FileSourceMeta.archived.is_(False),
        )
    )
    allowed_tables = [ds.view_name for ds in ds_result.scalars()]

    existing = list(
        await session.scalars(
            select(SavedQuery).where(SavedQuery.project_id == project.id)
        )
    )

    def _norm(sql: str) -> str:
        import re as _re

        return _re.sub(r"\s+", " ", sql.strip().rstrip(";").lower())

    by_sql = {q.sql_text and _norm(q.sql_text): q for q in existing if q.sql_text}

    widgets_config: list[dict[str, Any]] = []
    for idx, w in enumerate(req.widgets):
        sql = (w.sql or "").strip().rstrip(";")
        if not sql:
            continue
        match = by_sql.get(_norm(sql))
        if match is not None:
            query_id = match.id
        else:
            query = SavedQuery(
                project_id=project.id,
                owner_id=context.user_id,
                name=f"AI - {w.title}",
                description="",
                sql_text=sql,
                left_datasource=_detect_datasource(sql, allowed_tables),
                ai_generated=True,
            )
            session.add(query)
            await session.flush()
            query_id = query.id
            by_sql[_norm(sql)] = query

        mapped_type = _map_chart_type(w.chartType)
        default_w = {"kpi": 3, "table": 12, "pie": 4}.get(mapped_type, 6)
        default_h = {"kpi": 2, "table": 5}.get(mapped_type, 4)
        widgets_config.append(
            {
                "id": f"ai_widget_{idx}",
                "title": w.title,
                "explanation": w.explanation or "",
                "type": mapped_type,
                "chartSubtype": _map_chart_subtype(w.chartType),
                "dataSource": {"kind": "query", "queryId": query_id},
                "xColumn": w.labelColumn or "",
                "yColumn": w.valueColumn or "",
                "aggregation": "sum",
                "sortBy": "x_asc",
                "filters": [],
                "colSpan": default_w,
                "position": idx,
                "gridX": (idx % 2) * 6,
                "gridY": (idx // 2) * default_h,
                "gridW": default_w,
                "gridH": default_h,
            }
        )

    dashboard = Dashboard(
        project_id=project.id,
        owner_id=context.user_id,
        tenant_id=context.tenant_id,
        name=req.title or "AI Dashboard",
        description="",
        status="draft",
        config={
            "widgets": widgets_config,
            "globalFilters": [],
            "layout": "grid",
            "ai_generated": True,
            "summary": req.summary or "",
            "keyFindings": req.keyFindings,
            "recommendedActions": req.recommendedActions,
        },
    )
    session.add(dashboard)
    await session.commit()
    await session.refresh(dashboard)
    return {
        "status": "saved",
        "dashboard_id": dashboard.id,
        "name": dashboard.name,
        "project_id": project.id,
        "widgets_created": len(widgets_config),
    }
