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
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import SessionLocal, get_db
from app.models.audit_event import AuditEvent
from app.models.project import Project, ProjectMember
from app.routes.query import _auto_cast_aggregates, _resolve_vdb_database, _run_sql
from app.services import home_intelligence as hi
from app.services.tenant_teiid_resolver import TenantTeiidResolver

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["AI Intelligence"])


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
) -> list[dict[str, Any]]:
    started = datetime.now(UTC)
    ctx = await hi.gather_project_context(session, project)
    runner = _make_runner(session, context, project.id)

    # Primary path: AI-driven analyst loop (plan -> execute real SQL -> interpret).
    # Falls back to the deterministic suite only if the AI server is unavailable.
    cards: list[dict[str, Any]] | None = None
    try:
        cards = await hi.run_ai_intelligence(
            project,
            ctx,
            runner,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
    except Exception as exc:
        logger.warning("AI intelligence failed for project %s: %s", project.id, exc)
        cards = None
    if cards is None:
        cards = await hi.run_intelligence_suite(project, ctx, prompt_types, runner)

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
    cards = await _run_for_project(session, context, project, prompts)
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

        yield _sse(
            {
                "type": "start",
                "projects": [
                    {
                        "id": str(p.id),
                        "name": p.name,
                        "color": hi.project_color(p.id),
                    }
                    for p in projects
                ],
            }
        )

        summaries: list[dict[str, Any]] = []

        async def work(project: Project) -> dict[str, Any]:
            async with SessionLocal() as session:
                cards = await _run_for_project(
                    session, context, project, hi.ALL_PROMPT_TYPES
                )
            return {
                "projectId": str(project.id),
                "projectName": project.name,
                "projectColor": hi.project_color(project.id),
                "insights": cards,
            }

        tasks = {asyncio.create_task(work(p)): p for p in projects}
        for coro in asyncio.as_completed(list(tasks)):
            try:
                result = await coro
                summaries.append(
                    {
                        "projectId": result["projectId"],
                        "projectName": result["projectName"],
                        "insightSummaries": [
                            c["summary"] for c in result["insights"]
                        ],
                    }
                )
                yield _sse({"type": "project_complete", **result})
            except Exception as exc:
                logger.warning("project intelligence failed: %s", exc)
                yield _sse(
                    {"type": "project_error", "error": str(exc)}
                )

        if cross_project:
            synthesis = hi.synthesise_cross_project(summaries)
            if synthesis is not None:
                yield _sse({"type": "synthesis_complete", "synthesis": synthesis})

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
