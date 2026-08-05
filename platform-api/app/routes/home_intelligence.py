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
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.database import SessionLocal, get_db
from app.models.audit_event import AuditEvent
from app.models.business_insight_result import BusinessInsightResult
from app.models.dashboard import Dashboard
from app.models.file_source_meta import FileSourceMeta
from app.models.intelligence_snapshot import IntelligenceSnapshot
from app.models.project import Project, ProjectMember
from app.models.project_intelligence_snapshot import ProjectIntelligenceSnapshot
from app.models.saved_query import SavedQuery
from app.routes.query_sql_helpers import (
    _auto_cast_aggregates,
    _execute_sql_with_repair,
    _resolve_vdb_database,
    _sample_project_columns,
)
from app.services import dashboard_widget as dw
from app.services import home_intel_queue as q
from app.services import home_intelligence as hi
from app.services import percent_change_summary as pcs
from app.services import time_series_transform as tst
from app.services.ai_intelligence_client import AIUnavailableError
from app.services.home_intel_queue import get_redis
from app.services.presentation_engine import PresentationMode
from app.services.response_envelope import attach_envelope
from app.services.teiid_sql import (
    normalize_teiid_identifiers,
    normalize_teiid_timestamps,
    project_table_schema,
)
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

    # Lazy-load schema context once; the same project tables are reused for every
    # plan/execute call in a single run.
    ctx: dict[str, Any] = {}

    async def _ensure_ctx() -> dict[str, Any]:
        if ctx:
            return ctx
        database = await _resolve_vdb_database(
            session=session, context=context, project_id=project_id
        )
        endpoint = await TenantTeiidResolver(session).resolve_for_org(
            context.tenant_id
        )
        table_schema = await project_table_schema(
            session, tenant_id=context.tenant_id, project_id=project_id
        )
        allowed_tables = [
            str(t)
            for entry in table_schema
            if (t := entry.get("table")) is not None
        ]
        column_types = {
            str(col.get("name")): str(col.get("type") or "")
            for entry in table_schema
            for col in (entry.get("columns") or [])
            if isinstance(col, dict) and col.get("name")
        }
        column_samples = await _sample_project_columns(
            database=database,
            tables=allowed_tables,
            teiid_host=endpoint.pg_host,
            teiid_port=endpoint.pg_port,
        )
        ctx.update(
            {
                "database": database,
                "endpoint": endpoint,
                "table_schema": table_schema,
                "allowed_tables": allowed_tables,
                "column_types": column_types,
                "column_samples": column_samples,
            }
        )
        return ctx

    async def runner(sql: str) -> dict[str, Any]:
        ctx_data = await _ensure_ctx()
        result, _ = await _execute_sql_with_repair(
            raw_sql=sql,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            project_id=project_id,
            database=ctx_data["database"],
            endpoint=ctx_data["endpoint"],
            table_schema=ctx_data["table_schema"],
            allowed_tables=ctx_data["allowed_tables"],
            column_types=ctx_data["column_types"],
            column_samples=ctx_data["column_samples"],
            max_attempts=2,
        )
        if result is None:
            raise HTTPException(
                status_code=502, detail=f"Could not execute generated SQL: {sql}"
            )
        return result

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
    raise_on_error: bool = False,
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
            session=session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            granularity=granularity,
            plan_semaphore=plan_semaphore,
        )
    except AIUnavailableError:
        raise
    except Exception as exc:
        logger.warning("AI intelligence failed for project %s: %s", project.id, exc)
        if raise_on_error:
            raise
        cards = None
    if cards is None:
        cards = []

    # Deeper analysis, in order of depth:
    # 1) Governed analytical methods (forecast, anomaly, change point,
    #    contribution, correlation, group comparison) executed through the
    #    Analytical Method Engine and gated on materiality — the cards that
    #    genuinely earn the "deeper" label.
    # 2) Shape templates as a fallback for tables where no method applies, so a
    #    project without method-eligible data still gets richer charts.
    # 1) Dissect the findings the user already cares about. Diagnostics attach
    #    to their originating Risk/Trend/Opportunity card (they do not add new
    #    cards), so the section reads as a drill-down with proposed actions
    #    rather than a second, unrelated feed.
    try:
        await hi._card_diagnostic_insights(
            project, ctx, runner, session, tenant_id=context.tenant_id, cards=cards
        )
    except Exception as exc:
        logger.warning("card diagnostics failed for project %s: %s", project.id, exc)

    # 2) Standalone governed analyses for tables no card covers.
    deep_cards: list[dict[str, Any]] = []
    try:
        deep_cards = await hi._method_driven_insights(
            project, ctx, runner, session, tenant_id=context.tenant_id
        )
        if deep_cards:
            cards.extend(deep_cards)
    except Exception as exc:
        logger.warning("method-driven insights failed for project %s: %s", project.id, exc)

    try:
        shape_cards = await hi._shape_template_insights(
            project, ctx, runner, max_total=max(0, 4 - len(deep_cards))
        )
        if shape_cards:
            cards.extend(shape_cards)
    except Exception as exc:
        logger.warning("shape-template insights failed for project %s: %s", project.id, exc)

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


async def _has_project_edit(
    session: AsyncSession, context: RequestContext, project: Project
) -> bool:
    """Check whether the caller may edit dashboards/queries in this project."""
    if project.owner_id == context.user_id:
        return True
    if context.role == Role.ADMIN.value:
        return True
    member = await session.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == context.user_id,
            ProjectMember.is_active.is_(True),
        )
    )
    return member is not None and member.role in ("editor", "admin", "owner")


# ─────────────────────────────────────────────────────────────────────────────
# Shared business-intelligence run orchestration
# ─────────────────────────────────────────────────────────────────────────────

async def _start_home_intelligence_run(
    context: RequestContext,
    cross_project: bool,
    granularity: int,
) -> tuple[str, list[dict[str, Any]]]:
    """Register a business-inselligence run and enqueue one arq job per project."""
    async with SessionLocal() as session:
        projects = await _accessible_projects(session, context)

    if not projects:
        return ("", [])

    project_meta = [
        {"id": str(p.id), "name": p.name, "color": hi.project_color(p.id)}
        for p in projects
    ]
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
    return run_id, project_meta


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
        run_id, project_meta = await _start_home_intelligence_run(
            context, cross_project, granularity
        )
        if not run_id:
            yield _sse({"type": "done", "projectCount": 0})
            return

        yield _sse({"type": "start", "projects": project_meta})

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
                        len(project_meta),
                    )
                    break
                await q.wait_for_wakeup(pubsub, timeout=_STREAM_POLL_SECONDS)

        yield _sse({"type": "done", "projectCount": len(project_meta)})

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
        # Keep a previous synthesis if this update carries no replacement (e.g.
        # a refresh that has not yet produced a new synthesis).
        prior_synthesis = (snap.payload or {}).get("synthesis") if snap else None
        if payload.get("synthesis") is None and prior_synthesis is not None:
            payload = {**payload, "synthesis": prior_synthesis}
        snap.payload = payload
        await session.commit()


def _as_utc(dt: datetime | None) -> datetime | None:
    """Normalize a possibly-naive DB timestamp to aware UTC for comparison."""
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


async def _stale_project_ids(
    session: AsyncSession,
    context: RequestContext,
    snap: IntelligenceSnapshot,
) -> list[str]:
    """Projects whose Knowledge Graph rebuilt after this briefing was written.

    The KG lifecycle already rebuilds on every data change, so "a KG build
    postdates the snapshot" is a faithful, DB-only proxy for "the data behind
    this briefing changed" — no AI calls, one indexed query.
    """
    from app.models import KnowledgeGraph

    project_ids: list[int] = []
    for p in (snap.payload or {}).get("projects") or []:
        try:
            project_ids.append(int(p.get("id")))
        except (TypeError, ValueError):
            continue
    snap_time = _as_utc(snap.updated_at)
    if not project_ids or snap_time is None:
        return []

    graphs = (
        await session.scalars(
            select(KnowledgeGraph).where(
                KnowledgeGraph.tenant_id == context.tenant_id,
                KnowledgeGraph.project_id.in_(project_ids),
            )
        )
    ).all()
    stale: list[str] = []
    for graph in graphs:
        built = _as_utc(graph.last_successful_build_at)
        if built is not None and built > snap_time:
            stale.append(str(graph.project_id))
    return stale


async def _snapshot_payload_dict(
    session: AsyncSession,
    context: RequestContext,
    snap: IntelligenceSnapshot,
) -> dict[str, Any]:
    """Build the snapshot response, honouring both KG-drift and in-progress runs."""
    project_ids: set[str] = set()
    if isinstance(snap.payload, dict):
        for p in snap.payload.get("projects") or []:
            try:
                project_ids.add(str(p["id"]))
            except (TypeError, KeyError, ValueError):
                pass

    kg_stale: set[str] = set()
    try:
        kg_stale = set(await _stale_project_ids(session, context, snap))
    except Exception:  # staleness is advisory — never break the snapshot read
        logger.exception("Failed to compute snapshot staleness")

    payload_stale = False
    payload_stale_projects: set[str] = set()
    if isinstance(snap.payload, dict):
        payload_stale = bool(snap.payload.get("stale"))
        for pid in snap.payload.get("staleProjects") or []:
            try:
                payload_stale_projects.add(str(pid))
            except (TypeError, ValueError):
                pass

    if payload_stale:
        stale_projects = project_ids | kg_stale | payload_stale_projects
    else:
        stale_projects = kg_stale | payload_stale_projects

    payload = dict(snap.payload) if isinstance(snap.payload, dict) else {}
    payload.pop("stale", None)
    payload.pop("staleProjects", None)

    return {
        "granularity": snap.granularity,
        "updatedAt": snap.updated_at.isoformat() if snap.updated_at else None,
        **payload,
        "stale": bool(stale_projects),
        "staleProjects": sorted(stale_projects),
    }


@router.get("/home-intelligence/snapshot")
async def get_intelligence_snapshot(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Return the caller's latest persisted run (or ``snapshot: null``).

    ``stale``/``staleProjects`` flag projects whose data changed (Knowledge
    Graph rebuilt) after this briefing was written, so the UI can nudge a
    refresh without spending any AI capacity.
    """
    snap = await session.scalar(
        select(IntelligenceSnapshot).where(
            IntelligenceSnapshot.user_id == context.user_id
        )
    )
    if snap is None:
        return {"snapshot": None}

    return {"snapshot": await _snapshot_payload_dict(session, context, snap)}


class RefreshHomeIntelligenceRequest(BaseModel):
    cross_project: bool = True
    granularity: int = 3


@router.post("/home-intelligence/refresh")
async def refresh_home_intelligence(
    req: RefreshHomeIntelligenceRequest | None = None,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Queue a background business-intelligence run and return immediately.

    The caller can poll ``GET /api/ai/home-intelligence/snapshot`` (or
    ``/run/{run_id}``) to update the cards once the arq workers finish.
    """
    cross_project = req.cross_project if req else True
    granularity = req.granularity if req else 3
    run_id, project_meta = await _start_home_intelligence_run(
        context, cross_project, granularity
    )
    if not run_id:
        return {"snapshot": None, "run_id": None}

    payload: dict[str, Any] = {
        "projects": project_meta,
        "results": [],
        "synthesis": None,
        "generatedAt": datetime.now(UTC).isoformat(),
        "stale": True,
        "staleProjects": [p["id"] for p in project_meta],
    }
    await _save_snapshot(context, granularity, payload)

    snap = await session.scalar(
        select(IntelligenceSnapshot).where(
            IntelligenceSnapshot.user_id == context.user_id
        )
    )
    return {
        "snapshot": await _snapshot_payload_dict(session, context, snap) if snap else None,
        "run_id": run_id,
    }


@router.get("/home-intelligence/run/{run_id}")
async def home_intelligence_run_status(
    run_id: str,
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Return whether a queued business-intelligence run has finalized."""
    stored, _ = await q.get_synthesis(run_id)
    return {"run_id": run_id, "complete": stored}


@router.post("/home-intelligence/clear-cache")
async def clear_home_intelligence_cache(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> dict[str, Any]:
    """Clear Business Insight caches for the caller's tenant.

    Deletes the tenant's shared Business Insight result cache, the stream
    snapshot, and per-user project snapshots used by the Business Insight feed.
    The next feed refresh regenerates cards with the latest ranking.
    """
    r1 = await session.execute(
        delete(BusinessInsightResult).where(
            BusinessInsightResult.tenant_id == context.tenant_id
        )
    )
    r2 = await session.execute(
        delete(IntelligenceSnapshot).where(
            IntelligenceSnapshot.tenant_id == context.tenant_id
        )
    )
    r3 = await session.execute(
        delete(ProjectIntelligenceSnapshot).where(
            ProjectIntelligenceSnapshot.tenant_id == context.tenant_id,
            ProjectIntelligenceSnapshot.suite == "insights",
        )
    )
    business_count = int(getattr(r1, "rowcount", 0) or 0)
    snapshot_count = int(getattr(r2, "rowcount", 0) or 0)
    insight_snapshot_count = int(getattr(r3, "rowcount", 0) or 0)
    session.add(
        AuditEvent(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            event_type="tenant_settings",
            scope="business_insight_cache_clear",
            title="Cleared business insight cache",
        )
    )
    await session.commit()
    return {
        "deleted": {
            "business_insight_results": business_count,
            "intelligence_snapshots": snapshot_count,
            "project_insight_snapshots": insight_snapshot_count,
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


# ── Save a suggestion (explicit user action) ─────────────────────────


class SaveDashboardWidget(BaseModel):
    title: str
    sql: str
    chartType: str = "bar"
    explanation: str | None = None
    labelColumn: str | None = None
    valueColumn: str | None = None
    valueColumn2: str | None = None
    visualizationOptions: dict[str, Any] | None = None


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
    project = await session.get(Project, req.project_id)
    if (
        project is None
        or project.tenant_id != context.tenant_id
        or not await _has_project_edit(session, context, project)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Project not editable"
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

    existing_by_sql: dict[str, SavedQuery] = {}
    widgets_config: list[dict[str, Any]] = []
    for idx, w in enumerate(req.widgets):
        sql = (w.sql or "").strip().rstrip(";")
        if not sql:
            continue
        query = await dw.find_or_create_saved_query(
            session,
            project_id=project.id,
            title=f"AI - {w.title}",
            sql=sql,
            user_id=context.user_id,
            allowed_tables=allowed_tables,
            existing_by_sql=existing_by_sql,
        )
        widgets_config.append(
            dw.build_widget_config(
                title=w.title,
                query_id=query.id,
                chart_type=w.chartType,
                label_column=w.labelColumn,
                value_column=w.valueColumn,
                value_column_2=w.valueColumn2,
                visualization_options=w.visualizationOptions,
                explanation=w.explanation or "",
                index=idx,
            )
        )

    dashboard = Dashboard(
        project_id=project.id,
        owner_id=context.user_id,
        tenant_id=context.tenant_id,
        name=req.title or _derive_dashboard_title(project.name, [w.model_dump() for w in req.widgets]),
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


class SaveCardToDashboardRequest(BaseModel):
    project_id: int
    source_project_id: int | None = None
    dashboard_id: int | None = None
    dashboard_name: str | None = None
    title: str
    sql: str
    chartType: str = "bar"
    labelColumn: str | None = None
    valueColumn: str | None = None
    valueColumn2: str | None = None
    visualizationOptions: dict[str, Any] | None = None


@router.post("/home/save-card-to-dashboard")
async def save_card_to_dashboard(
    req: SaveCardToDashboardRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Save a single insight card's chart to a new or existing dashboard."""
    project = await session.get(Project, req.project_id)
    if (
        project is None
        or project.tenant_id != context.tenant_id
        or not await _has_project_edit(session, context, project)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Project not editable"
        )

    if (
        req.source_project_id is not None
        and req.source_project_id != project.id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dashboard project must match the insight's source project",
        )

    sql = (req.sql or "").strip().rstrip(";")
    if not sql:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="SQL is required to save a chart",
        )
    if not req.title or not req.title.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Widget title is required",
        )

    if req.dashboard_id is not None and req.dashboard_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide either dashboard_id or dashboard_name, not both",
        )

    dashboard: Dashboard | None = None
    if req.dashboard_id is not None:
        dashboard = await session.get(Dashboard, req.dashboard_id)
        if dashboard is None or dashboard.tenant_id != context.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Dashboard not found"
            )
        if dashboard.project_id != project.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Dashboard does not belong to the selected project",
            )
        if dashboard.owner_id != context.user_id and not (
            await _has_project_edit(session, context, project)
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not allowed to edit this dashboard",
            )
    elif not req.dashboard_name or not req.dashboard_name.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="New dashboard name is required",
        )

    ds_result = await session.execute(
        select(FileSourceMeta).where(
            FileSourceMeta.project_id == project.id,
            FileSourceMeta.tenant_id == context.tenant_id,
            FileSourceMeta.archived.is_(False),
        )
    )
    allowed_tables = [ds.view_name for ds in ds_result.scalars()]

    query = await dw.find_or_create_saved_query(
        session,
        project_id=project.id,
        title=req.title,
        sql=sql,
        user_id=context.user_id,
        allowed_tables=allowed_tables,
    )

    if dashboard is None:
        assert req.dashboard_name is not None
        widget_id = f"ai_widget_0_{int(datetime.now(UTC).timestamp() * 1000) % 100000}"
        widget_config = dw.build_widget_config(
            title=req.title,
            query_id=query.id,
            chart_type=req.chartType,
            label_column=req.labelColumn,
            value_column=req.valueColumn,
            value_column_2=req.valueColumn2,
            visualization_options=req.visualizationOptions,
            widget_id=widget_id,
            index=0,
        )
        dashboard = Dashboard(
            project_id=project.id,
            owner_id=context.user_id,
            tenant_id=context.tenant_id,
            name=req.dashboard_name.strip(),
            description="",
            status="draft",
            config={
                "widgets": [widget_config],
                "globalFilters": [],
                "layout": "grid",
                "ai_generated": True,
            },
        )
        session.add(dashboard)
    else:
        config = dict(dashboard.config or {})
        widgets: list[dict[str, Any]] = list(config.get("widgets") or [])
        position = len(widgets)
        used_ids = {w.get("id") for w in widgets if w.get("id")}
        suffix = 0
        base_id = f"ai_widget_{position}"
        widget_id = base_id
        while widget_id in used_ids:
            suffix += 1
            widget_id = f"{base_id}_{suffix}"
        widget_config = dw.build_widget_config(
            title=req.title,
            query_id=query.id,
            chart_type=req.chartType,
            label_column=req.labelColumn,
            value_column=req.valueColumn,
            value_column_2=req.valueColumn2,
            visualization_options=req.visualizationOptions,
            widget_id=widget_id,
            index=position,
        )
        widgets.append(widget_config)
        config["widgets"] = widgets
        dashboard.config = config

    await session.flush()
    await session.commit()
    await session.refresh(dashboard)
    return {
        "status": "saved",
        "dashboard_id": dashboard.id,
        "name": dashboard.name,
        "project_id": project.id,
        "query_id": query.id,
        "widget_id": widget_config["id"],
    }


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
