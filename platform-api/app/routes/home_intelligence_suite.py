"""Home AI Intelligence — per-project diagnostic suite + SSE feed.

- ``POST /api/ai/run-intelligence-suite`` runs the suite for a single project
  (used by the report viewer to re-execute on open).
- ``GET  /api/ai/home-intelligence/stream`` streams per-project results as
  Server-Sent Events so cards appear as each project finishes.

Every run is written to ``audit_events`` (event_type ``home_intelligence``) so
the project Audit Log reflects exactly which tables/documents were read.

The shared run helpers (``_make_runner``, ``_run_for_project``, access checks)
live here and are imported by the sibling modules
``home_intelligence_snapshot.py``, ``home_intelligence_suggestions.py`` and
``home_intelligence_dashboard_save.py``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import SessionLocal, get_db
from app.models.audit_event import AuditEvent
from app.models.project import Project, ProjectMember
from app.routes.query_sql_helpers import (
    _execute_sql_with_repair,
    _resolve_vdb_database,
    _sample_project_columns,
)
from app.services import home_intel_queue as q
from app.services import home_intelligence as hi
from app.services.ai_intelligence_client import AIUnavailableError
from app.services.teiid_sql import (
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
        result, _, _ = await _execute_sql_with_repair(
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
    grounding_sink: dict[str, Any] | None = None,
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
            grounding_sink=grounding_sink,
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
    # KG-50: the active KG version + evidence ids that grounded this run's
    # plan, so a client can verify (or an evaluation prove) which evidence
    # actually influenced these insights.
    grounding_sink: dict[str, Any] = {}
    cards = await _run_for_project(
        session, context, project, prompts, granularity=req.granularity,
        grounding_sink=grounding_sink,
    )
    return {
        "projectId": str(project.id),
        "projectName": project.name,
        "projectColor": hi.project_color(project.id),
        "insights": cards,
        "kgGrounding": grounding_sink.get("kg_grounding"),
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
    run_id: str | None = None,
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> StreamingResponse:
    """Stream per-project intelligence as Server-Sent Events.

    Each project runs in its own DB session so a slow project never blocks the
    others, and results are enqueued the moment a project finishes. Pass
    ``run_id`` to reconnect to an in-progress run instead of starting a new one.
    """

    async def event_stream() -> AsyncIterator[str]:
        project_meta: list[dict[str, Any]] = []
        active_run_id: str
        active_cross_project = cross_project
        if run_id:
            meta = await q.get_meta(run_id)
            if (
                meta is None
                or meta["tenant_id"] != context.tenant_id
                or meta["user_id"] != context.user_id
            ):
                raise HTTPException(status_code=404, detail="Run not found")
            active_run_id = run_id
            active_cross_project = meta["cross_project"]
            project_meta = meta["projects"]
        else:
            active_run_id, project_meta = await _start_home_intelligence_run(
                context, cross_project, granularity
            )
            if not active_run_id:
                yield _sse({"type": "done", "projectCount": 0})
                return

        yield _sse({"type": "start", "projects": project_meta})

        emitted: set[str] = set()
        deadline = asyncio.get_event_loop().time() + _STREAM_DEADLINE_SECONDS

        def _emit_results(results: dict[str, dict[str, Any]]) -> list[str]:
            events: list[str] = []
            for pid, result in results.items():
                if pid in emitted:
                    continue
                emitted.add(pid)
                if "insights" in result:
                    events.append(_sse({"type": "project_complete", **result}))
                else:
                    events.append(_sse({"type": "project_error", **result}))
            return events

        # Emit any results already written before this connection opened.
        for sse in _emit_results(await q.get_results(active_run_id)):
            yield sse

        async with q.subscribe(active_run_id) as pubsub:
            while True:
                for sse in _emit_results(await q.get_results(active_run_id)):
                    yield sse

                stored, synthesis = await q.get_synthesis(active_run_id)
                if stored:
                    if active_cross_project and synthesis is not None:
                        yield _sse(
                            {"type": "synthesis_complete", "synthesis": synthesis}
                        )
                    break
                if asyncio.get_event_loop().time() > deadline:
                    logger.warning(
                        "home-intel stream %s timed out after %ss with %s/%s "
                        "projects reported",
                        active_run_id,
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
