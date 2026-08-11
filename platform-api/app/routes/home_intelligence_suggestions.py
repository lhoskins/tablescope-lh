"""Home AI suggestions: query/dashboard suggestions, insights, insight cards.

All AI-driven (no hard-coded metrics), run across every accessible project
while keeping per-project data isolation: each project resolves its own VDB and
is planned/queried independently. Results are generated in memory and returned
for preview; nothing is persisted unless the user explicitly saves (see
``home_intelligence_dashboard_save.py``).

Split from ``home_intelligence.py``; siblings: ``home_intelligence_suite.py``
and ``home_intelligence_snapshot.py``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.database import SessionLocal, get_db
from app.models.business_insight_result import BusinessInsightResult
from app.models.intelligence_snapshot import IntelligenceSnapshot
from app.models.project import Project, ProjectMember
from app.models.project_intelligence_snapshot import ProjectIntelligenceSnapshot
from app.routes.home_intelligence_suite import (
    _accessible_projects,
    _has_access,
    _make_runner,
    _run_for_project,
)
from app.routes.query_sql_helpers import (
    _auto_cast_aggregates,
    _execute_sql_with_repair,
    _resolve_vdb_database,
    _sample_project_columns,
)
from app.services import home_intelligence as hi
from app.services import percent_change_summary as pcs
from app.services import time_series_transform as tst
from app.services.home_intel_queue import get_redis
from app.services.presentation_engine import PresentationMode
from app.services.response_envelope import attach_envelope
from app.services.teiid_sql import (
    normalize_teiid_identifiers,
    normalize_teiid_timestamps,
)
from app.services.tenant_teiid_resolver import TenantTeiidResolver

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["AI Intelligence"])

# Bounded concurrency/timeouts so one slow project (or a cold AI model) cannot
# hang the Home "New Query / New Dashboard" pills for every project.
_SUGGESTION_CONCURRENCY = 3
_QUERY_SUGGESTION_TIMEOUT = 90.0
_DASHBOARD_SUGGESTION_TIMEOUT = 120.0
_suggestion_sem = asyncio.Semaphore(_SUGGESTION_CONCURRENCY)


async def _bounded_suggestion(
    project: Project,
    work: Callable[[Project], Awaitable[dict[str, Any]]],
    timeout: float,
    empty_key: str,
    empty_value: Any,
) -> dict[str, Any]:
    """Run a per-project suggestion coroutine with a timeout and semaphore.

    If the work times out or fails, return the project entry with the empty
    payload so the Home pills still render results for other projects.
    """
    async with _suggestion_sem:
        try:
            return await asyncio.wait_for(work(project), timeout=timeout)
        except TimeoutError:
            logger.warning("Suggestion timed out for project %s", project.id)
        except Exception as exc:
            logger.warning("Suggestion failed for project %s: %s", project.id, exc)
    return {
        "projectId": str(project.id),
        "projectName": project.name,
        "projectColor": hi.project_color(project.id),
        empty_key: empty_value,
        "timedOut": True,
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
    # When set, generate for this single project only (Project Insight page).
    # None keeps the original every-accessible-project behavior (Home page).
    project_id: int | None = None


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
    if not analyses:
        return []

    # Sample live table values so generated timestamp casts can be rewritten to
    # Teiid PARSETIMESTAMP with the right mask before the preview is run.
    database = await _resolve_vdb_database(
        session=session, context=context, project_id=project.id
    )
    endpoint = await TenantTeiidResolver(session).resolve_for_org(
        context.tenant_id
    )
    column_samples = await _sample_project_columns(
        database=database,
        tables=allowed_tables,
        teiid_host=endpoint.pg_host,
        teiid_port=endpoint.pg_port,
    )
    column_types = {
        str(col.get("name")): str(col.get("type") or "")
        for entry in table_schema
        for col in (entry.get("columns") or [])
        if isinstance(col, dict) and col.get("name")
    }
    valid_analyses: list[dict[str, Any]] = []
    for a in analyses:
        sql = (a.get("sql") or "").strip()
        if not sql:
            continue
        sql = normalize_teiid_identifiers(sql, table_schema)
        sql = normalize_teiid_timestamps(
            sql,
            column_types=column_types,
            column_samples=column_samples,
        )
        sql = _auto_cast_aggregates(sql).rstrip().rstrip(";")
        # Do not surface suggestions whose SQL cannot be executed even after the
        # repair loop; otherwise the preview modal will show a Teiid error.
        result, final_sql = await _execute_sql_with_repair(
            raw_sql=sql,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            project_id=project.id,
            database=database,
            endpoint=endpoint,
            table_schema=table_schema,
            allowed_tables=allowed_tables,
            column_types=column_types,
            column_samples=column_samples,
            max_attempts=3,
        )
        if result is not None:
            a["sql"] = final_sql
            a["result"] = result
            valid_analyses.append(a)
    return valid_analyses


def _derive_dashboard_title(
    project_name: str, widgets: list[dict[str, Any]]
) -> str:
    """Build a descriptive, non-generic dashboard title from the widget content."""
    titles = [
        str(w.get("title") or "").strip()
        for w in widgets
        if w.get("title") and str(w.get("title")).strip() not in ("", "Widget")
    ]
    seen: list[str] = []
    for t in titles:
        if t not in seen:
            seen.append(t)
        if len(seen) == 2:
            break
    if seen:
        base = " & ".join(seen)
        if "dashboard" not in base.lower():
            base = f"{base} Dashboard"
        return base
    return f"{project_name} — AI Dashboard"


@router.post("/home/query-suggestions")
async def home_query_suggestions(
    req: SuggestRequest,
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """AI-suggested queries for every accessible project (in memory, unsaved).

    ``project_id`` restricts generation to that single project (Project
    Insight page); omitted, all accessible projects are covered (Home page).
    """
    async with SessionLocal() as session:
        projects = await _accessible_projects(session, context)
    if req.project_id is not None:
        projects = [p for p in projects if p.id == req.project_id]
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
                "chartType": a.get("chart_type") or "",
                "labelColumn": a.get("label_column") or "",
                "valueColumn": a.get("value_column") or "",
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

    results = await asyncio.gather(
        *(
            _bounded_suggestion(
                p,
                work,
                _QUERY_SUGGESTION_TIMEOUT,
                "suggestions",
                [],
            )
            for p in projects
        )
    )
    return {"projects": list(results)}


@router.post("/home/dashboard-suggestions")
async def home_dashboard_suggestions(
    req: SuggestRequest,
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """AI-suggested dashboards for every accessible project.

    The plan's SQL is executed server-side against each project's own VDB and
    turned into renderable chart series so the Home can render the dashboard
    from memory. Nothing is saved until the user clicks Save. ``project_id``
    restricts generation to that single project (Project Insight page).
    """
    async with SessionLocal() as session:
        projects = await _accessible_projects(session, context)
    if req.project_id is not None:
        projects = [p for p in projects if p.id == req.project_id]
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
                    session=session,
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
                {
                    "title": _derive_dashboard_title(project.name, widgets),
                    "widgets": widgets,
                }
                if widgets
                else None
            ),
        }

    results = await asyncio.gather(
        *(
            _bounded_suggestion(
                p,
                work,
                _DASHBOARD_SUGGESTION_TIMEOUT,
                "dashboard",
                None,
            )
            for p in projects
        )
    )
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
            session=session,
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
            "title": _derive_dashboard_title(project.name, widgets),
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
    refresh: bool = False,
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """AI insights & opportunities for accessible projects; cached per project."""
    async with SessionLocal() as session:
        projects = await _accessible_projects(session, context)
        if req.project_id is not None:
            projects = [p for p in projects if p.id == req.project_id]
    if not projects:
        return {"projects": []}

    async def _get_insights_snapshot(
        session: AsyncSession, project: Project
    ) -> ProjectIntelligenceSnapshot | None:
        return await session.scalar(
            select(ProjectIntelligenceSnapshot).where(
                ProjectIntelligenceSnapshot.tenant_id == context.tenant_id,
                ProjectIntelligenceSnapshot.user_id == context.user_id,
                ProjectIntelligenceSnapshot.project_id == project.id,
                ProjectIntelligenceSnapshot.suite == "insights",
            )
        )

    async def _save_insights_snapshot(
        session: AsyncSession, project: Project, payload: dict[str, Any]
    ) -> None:
        snap = await _get_insights_snapshot(session, project)
        if snap is None:
            snap = ProjectIntelligenceSnapshot(
                tenant_id=context.tenant_id,
                user_id=context.user_id,
                project_id=project.id,
                suite="insights",
            )
            session.add(snap)
        snap.payload = payload
        await session.commit()

    async def work(project: Project) -> dict[str, Any]:
        async with SessionLocal() as session:
            if not refresh:
                snap = await _get_insights_snapshot(session, project)
                if snap is not None:
                    return snap.payload
            try:
                cards = await _run_for_project(
                    session,
                    context,
                    project,
                    hi.ALL_PROMPT_TYPES,
                    write_audit=False,
                    granularity=req.granularity,
                    raise_on_error=True,
                )
            except Exception as exc:
                logger.warning(
                    "insights failed for project %s: %s", project.id, exc
                )
                snap = await _get_insights_snapshot(session, project)
                if snap is not None:
                    return snap.payload
                return {
                    "projectId": str(project.id),
                    "projectName": project.name,
                    "projectColor": hi.project_color(project.id),
                    "insights": [],
                }
            payload = {
                "projectId": str(project.id),
                "projectName": project.name,
                "projectColor": hi.project_color(project.id),
                "insights": cards,
            }
            await _save_insights_snapshot(session, project, payload)
            return payload

    results = await asyncio.gather(*(work(p) for p in projects))
    return {"projects": list(results)}



def _find_card_in_payload(payload: Any, insight_id: str) -> dict[str, Any] | None:
    """Flatten nested insight lists and locate a card by insightId or id."""
    if not isinstance(payload, dict):
        return None
    for key in (
        "insights",
        "risks",
        "trends",
        "opportunities",
        "analysis",
        "trendDetection",
        "recommendedKpis",
    ):
        items = payload.get(key)
        if not isinstance(items, list):
            continue
        for card in items:
            if isinstance(card, dict) and (
                card.get("insightId") == insight_id or str(card.get("id")) == insight_id
            ):
                return card
    results = payload.get("results")
    if isinstance(results, list):
        for r in results:
            card = _find_card_in_payload(r, insight_id)
            if card is not None:
                return card
    return None


async def _resolve_insight_card(
    session: AsyncSession,
    context: RequestContext,
    project: Project,
    insight_id: str,
) -> dict[str, Any] | None:
    """Find the canonical insight card across all authorized snapshot stores."""
    snap = await session.scalar(
        select(IntelligenceSnapshot).where(IntelligenceSnapshot.user_id == context.user_id)
    )
    if snap and snap.payload:
        card = _find_card_in_payload(snap.payload, insight_id)
        if card and str(card.get("projectId") or card.get("project_id") or "") == str(project.id):
            return card

    pis = await session.scalar(
        select(ProjectIntelligenceSnapshot).where(
            ProjectIntelligenceSnapshot.tenant_id == context.tenant_id,
            ProjectIntelligenceSnapshot.user_id == context.user_id,
            ProjectIntelligenceSnapshot.project_id == project.id,
            ProjectIntelligenceSnapshot.suite == "project_insight",
        )
    )
    if pis and pis.payload:
        card = _find_card_in_payload(pis.payload, insight_id)
        if card:
            return card

    bis = await session.scalar(
        select(BusinessInsightResult).where(
            BusinessInsightResult.tenant_id == context.tenant_id,
            BusinessInsightResult.project_id == project.id,
        )
    )
    if bis and bis.payload:
        card = _find_card_in_payload(bis.payload, insight_id)
        if card:
            return card
    return None


@router.get("/insights/{insight_id}/time-series")
async def get_insight_time_series(
    insight_id: str,
    project_id: int,
    interval: str = "month",
    range: str = "1y",
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Return deterministic time-series points and percent-change for a card."""
    project = await session.get(Project, project_id)
    if (
        project is None
        or project.tenant_id != context.tenant_id
        or not await _has_access(session, context, project)
    ):
        raise HTTPException(status_code=404, detail="Insight not found")

    card = await _resolve_insight_card(session, context, project, insight_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Insight not found")

    fp = (card.get("evidenceFingerprint") or {}).get("resultFingerprint") or ""
    cache_key = (
        f"ts:{context.tenant_id}:{project.id}:{insight_id}:{interval}:{range}:"
        f"{fp or card.get('insightId') or card.get('id')}:v1"
    )
    try:
        redis = get_redis()
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(str(cached))
    except Exception:
        logger.exception("time-series cache read failed")

    timezone_name = "UTC"
    response = tst.transform_card_time_series(
        card, insight_id, interval, range, timezone_name
    )

    try:
        ttl = max(60, get_settings().home_intelligence_run_result_ttl_seconds)
        await redis.setex(
            cache_key,
            ttl,
            json.dumps(response.model_dump(mode="json"), default=str),
        )
    except Exception:
        logger.exception("time-series cache write failed")

    return response.model_dump(mode="json")


@router.post("/insights/percent-change-summary")
async def get_percent_change_summary(
    request: pcs.PercentChangeSummaryRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Return a cross-project percent-change summary aligned to one shared axis.

    The caller may supply a subset of project IDs; the server intersects that
    list with the projects the user is authorized to view. Unauthorized IDs are
    ignored and are never reflected in counts or response bodies.
    """
    accessible = await _accessible_projects(session, context)

    if request.project_ids:
        allowed = [p for p in accessible if p.id in set(request.project_ids)]
    else:
        allowed = accessible

    snap = await session.scalar(
        select(IntelligenceSnapshot).where(
            IntelligenceSnapshot.user_id == context.user_id,
        )
    )
    snapshot_payload: dict[str, Any] = {}
    snapshot_fingerprint = "none"
    if snap and snap.payload:
        snapshot_payload = snap.payload
        snapshot_fingerprint = (
            snap.updated_at.isoformat() if snap.updated_at else "none"
        )

    as_of = datetime.now(UTC).date()
    project_id_str = ",".join(str(p.id) for p in sorted(allowed, key=lambda p: p.id))
    sort = request.sort or pcs.SummarySort()
    cache_key = (
        f"pcs:{context.tenant_id}:{context.user_id}:{snapshot_fingerprint}:"
        f"{project_id_str}:{request.interval}:{request.range}:{as_of}:"
        f"{request.search or ''}:{sort.field}:{sort.direction}:"
        f"{request.cursor or ''}:{request.page_size}:v1"
    )

    try:
        redis = get_redis()
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(str(cached))
    except Exception:
        logger.exception("percent-change-summary cache read failed")

    try:
        response = await asyncio.to_thread(
            pcs.build_percent_change_summary,
            allowed,
            snapshot_payload,
            request,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    try:
        await redis.setex(
            cache_key,
            120,
            json.dumps(response.model_dump(mode="json"), default=str),
        )
    except Exception:
        logger.exception("percent-change-summary cache write failed")

    return response.model_dump(mode="json")
