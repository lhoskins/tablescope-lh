"""Project Insight API — project-scoped executive AI insight + acknowledgements.

- ``GET  /api/projects/{project_id}/insight`` builds the project-scoped report.
- ``POST /api/projects/{project_id}/insights/{insight_id}/acknowledge`` records
  that a user reviewed an insight (audited: who + when). Reviewed does NOT mean
  approved — there is no Approve/Reject.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.audit_event import AuditEvent
from app.models.business_insight_result import BusinessInsightResult
from app.models.project import Project, ProjectMember
from app.models.project_insight_acknowledgement import (
    ProjectInsightAcknowledgement,
)
from app.models.project_intelligence_snapshot import (
    ProjectIntelligenceSnapshot,
)
from app.models.user import User
from app.schemas.project_insight import (
    AcknowledgeInsightRequest,
    AcknowledgeInsightResponse,
    ProjectInsightResponse,
    ReopenInsightResponse,
    ReviewedInsight,
    ReviewedInsightsResponse,
)
from app.services import home_intel_queue as q
from app.services.project_insight_service import build_project_insight
from app.tasks.workflows import enqueue_rebuild_project_insight

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["project-insight"])


async def _require_project_access(
    project_id: int, session: AsyncSession, context: RequestContext
) -> Project:
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.owner_id == context.user_id:
        return project
    # TS-ISO-003: `is_shared` used to short-circuit here and grant any
    # same-tenant user access without checking membership at all -- it
    # controls discoverability, not automatic authorization (see
    # app.services.project_access, the single canonical policy). A shared
    # project still requires ACTIVE membership for non-owners.
    member = await session.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == context.user_id,
            ProjectMember.is_active.is_(True),
        )
    )
    if member is None:
        raise HTTPException(status_code=403, detail="No access to this project")
    return project


async def _get_snapshot(
    session: AsyncSession,
    context: RequestContext,
    project_id: int,
    suite: str = "project_insight",
) -> ProjectIntelligenceSnapshot | None:
    return await session.scalar(
        select(ProjectIntelligenceSnapshot).where(
            ProjectIntelligenceSnapshot.tenant_id == context.tenant_id,
            ProjectIntelligenceSnapshot.user_id == context.user_id,
            ProjectIntelligenceSnapshot.project_id == project_id,
            ProjectIntelligenceSnapshot.suite == suite,
        )
    )


async def _save_snapshot(
    session: AsyncSession,
    context: RequestContext,
    project_id: int,
    payload: dict,
    suite: str = "project_insight",
    *,
    is_stale: bool = False,
) -> None:
    """Upsert the caller's latest completed run for one project suite.

    Committing only the completed result guarantees a hydrating page never
    shows a blanked report: the prior snapshot stays until a fresh run finishes.
    """
    snap = await _get_snapshot(session, context, project_id, suite=suite)
    if snap is None:
        snap = ProjectIntelligenceSnapshot(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            project_id=project_id,
            suite=suite,
        )
        session.add(snap)
    snap.payload = payload
    snap.is_stale = is_stale
    await session.commit()


@router.get("/{project_id}/insight", response_model=ProjectInsightResponse)
async def get_project_insight(
    project_id: int,
    refresh: bool = False,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> ProjectInsightResponse:
    """Return the project-scoped executive insight report for one project.

    Snapshot behavior mirrors Business Insight: without ``refresh`` a saved
    snapshot is returned immediately so the page hydrates instantly; the client
    then re-runs with ``refresh=true`` in the background and commits the fresh
    result only once the run completes. A completed run overwrites the snapshot.
    """
    from app.routes.home_intelligence_suite import _make_runner

    project = await _require_project_access(project_id, session, context)

    if not refresh:
        snap = await _get_snapshot(session, context, project_id)
        if snap is not None:
            payload = dict(snap.payload)
            payload["stale"] = snap.is_stale
            if "project" not in payload:
                payload["project"] = {
                    "id": project.id,
                    "name": project.name,
                    "status": project.type or "Active",
                }
            if snap.updated_at:
                payload["generatedAt"] = snap.updated_at.isoformat()
            return ProjectInsightResponse.model_validate(payload)

    runner = _make_runner(session, context, project.id)
    report = await build_project_insight(
        session,
        project=project,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        runner=runner,
    )
    await _save_snapshot(
        session,
        context,
        project_id,
        report.model_dump(mode="json"),
        suite="project_insight",
        is_stale=False,
    )
    return report


@router.post("/{project_id}/insight/refresh", response_model=ProjectInsightResponse)
async def refresh_project_insight(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> ProjectInsightResponse:
    """Queue a background rebuild of the project insight snapshot.

    Marks the caller's snapshot stale and returns it immediately; the arq
    worker rebuilds the report and writes the fresh snapshot. The client polls
    ``GET /api/projects/{project_id}/insight`` — it returns ``stale=true``
    until the rebuild completes.
    """
    project = await _require_project_access(project_id, session, context)

    now_iso = datetime.now(UTC).isoformat()

    snap = await _get_snapshot(session, context, project_id)
    if snap is None:
        payload: dict[str, Any] = {
            "project": {
                "id": project.id,
                "name": project.name,
                "status": project.type or "Active",
            },
            "stale": True,
            "generatedAt": now_iso,
            "lastUpdatedAt": now_iso,
        }
        snap = ProjectIntelligenceSnapshot(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            project_id=project_id,
            suite="project_insight",
            payload=payload,
            is_stale=True,
        )
        session.add(snap)
    else:
        snap.is_stale = True
        payload = dict(snap.payload)
        payload["stale"] = True
        payload["lastUpdatedAt"] = now_iso
        if "generatedAt" not in payload:
            payload["generatedAt"] = now_iso
        snap.payload = payload
    await session.commit()

    await enqueue_rebuild_project_insight(
        tenant_id=context.tenant_id, project_id=project_id
    )

    if "project" not in payload:
        payload["project"] = {
            "id": project.id,
            "name": project.name,
            "status": project.type or "Active",
        }
    return ProjectInsightResponse.model_validate(payload)


@router.post("/{project_id}/insight/clear-cache", response_model=ProjectInsightResponse)
async def clear_project_insight_cache(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> ProjectInsightResponse:
    """Clear Project Insight caches for a single project.

    Deletes shared Business Insight result rows for this project and marks the
    per-user ``project_insight`` snapshot stale so the page never goes blank.
    A background rebuild is queued; the client sees the existing snapshot with
    ``stale=true`` until the fresh run completes.
    """
    from datetime import UTC, datetime

    project = await _require_project_access(project_id, session, context)
    now_iso = datetime.now(UTC).isoformat()

    await session.execute(
        delete(BusinessInsightResult).where(
            BusinessInsightResult.tenant_id == context.tenant_id,
            BusinessInsightResult.project_id == project.id,
        )
    )

    snap = await _get_snapshot(session, context, project_id, suite="project_insight")
    if snap is None:
        payload: dict[str, Any] = {
            "project": {
                "id": project.id,
                "name": project.name,
                "status": project.type or "Active",
            },
            "stale": True,
            "generatedAt": now_iso,
            "lastUpdatedAt": now_iso,
        }
        snap = ProjectIntelligenceSnapshot(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            project_id=project_id,
            suite="project_insight",
            payload=payload,
            is_stale=True,
        )
        session.add(snap)
    else:
        payload = dict(snap.payload)
        payload["stale"] = True
        payload["lastUpdatedAt"] = now_iso
        if "generatedAt" not in payload:
            payload["generatedAt"] = now_iso
        if "project" not in payload:
            payload["project"] = {
                "id": project.id,
                "name": project.name,
                "status": project.type or "Active",
            }
        snap.payload = payload
        snap.is_stale = True

    session.add(
        AuditEvent(
            tenant_id=context.tenant_id,
            project_id=project.id,
            user_id=context.user_id,
            event_type="project_settings",
            scope="project_insight_cache_clear",
            title="Cleared project insight cache",
        )
    )
    await session.commit()

    try:
        redis = q.get_redis()
        pcs_keys = await redis.keys(f"pcs:{context.tenant_id}:*")
        if pcs_keys:
            await redis.delete(*pcs_keys)
    except Exception:
        logger.exception("Failed to clear Percent Change Summary cache")

    await enqueue_rebuild_project_insight(
        tenant_id=context.tenant_id, project_id=project_id
    )

    return ProjectInsightResponse.model_validate(payload)


@router.post(
    "/{project_id}/insights/{insight_id}/acknowledge",
    response_model=AcknowledgeInsightResponse,
)
async def acknowledge_insight(
    project_id: int,
    insight_id: str,
    body: AcknowledgeInsightRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> AcknowledgeInsightResponse:
    """Mark an insight as Reviewed / Acknowledged (audited who + when).

    Idempotent per (project, insight): re-acknowledging updates the marker.
    """
    await _require_project_access(project_id, session, context)

    ack = await session.scalar(
        select(ProjectInsightAcknowledgement).where(
            ProjectInsightAcknowledgement.project_id == project_id,
            ProjectInsightAcknowledgement.insight_id == insight_id,
        )
    )
    if ack is None:
        ack = ProjectInsightAcknowledgement(
            tenant_id=context.tenant_id,
            project_id=project_id,
            insight_id=insight_id,
        )
        session.add(ack)
    ack.user_id = context.user_id
    ack.status = "reviewed"
    ack.note = body.note
    # Persist the snapshot so the Reviewed list survives report regeneration.
    if body.title is not None:
        ack.title = body.title
    if body.summary is not None:
        ack.summary = body.summary
    if body.category is not None:
        ack.category = body.category
    if body.severity is not None:
        ack.severity = body.severity

    session.add(
        AuditEvent(
            tenant_id=context.tenant_id,
            project_id=project_id,
            user_id=context.user_id,
            event_type="project_insight_acknowledged",
            prompt_type=insight_id[:100],
            scope="project_insight",
            title=f"Reviewed insight {insight_id}",
        )
    )
    await session.commit()
    await session.refresh(ack)

    user = await session.get(User, context.user_id)
    name = ""
    if user is not None:
        name = user.display_name or user.email or ""

    return AcknowledgeInsightResponse(
        insightId=insight_id,
        status="reviewed",
        acknowledgedByUserId=context.user_id,
        acknowledgedByName=name,
        acknowledgedAt=ack.updated_at or datetime.now(UTC),
    )


@router.get(
    "/{project_id}/insights/reviewed",
    response_model=ReviewedInsightsResponse,
)
async def list_reviewed_insights(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> ReviewedInsightsResponse:
    """List insights that have been reviewed for a project (most recent first)."""
    await _require_project_access(project_id, session, context)

    rows = (
        await session.execute(
            select(
                ProjectInsightAcknowledgement, User.display_name, User.email
            )
            .join(
                User,
                User.id == ProjectInsightAcknowledgement.user_id,
                isouter=True,
            )
            .where(
                ProjectInsightAcknowledgement.project_id == project_id,
                ProjectInsightAcknowledgement.status == "reviewed",
            )
            .order_by(ProjectInsightAcknowledgement.updated_at.desc())
        )
    ).all()

    items = [
        ReviewedInsight(
            insightId=ack.insight_id,
            title=ack.title or "",
            summary=ack.summary or "",
            category=ack.category or "",
            severity=ack.severity or "",
            note=ack.note,
            reviewedByUserId=ack.user_id,
            reviewedByName=display_name or email or "",
            reviewedAt=ack.updated_at,
        )
        for ack, display_name, email in rows
    ]
    return ReviewedInsightsResponse(items=items)


@router.post(
    "/{project_id}/insights/{insight_id}/reopen",
    response_model=ReopenInsightResponse,
)
async def reopen_insight(
    project_id: int,
    insight_id: str,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> ReopenInsightResponse:
    """Reopen a reviewed insight so it returns to the Open list (audited)."""
    await _require_project_access(project_id, session, context)

    ack = await session.scalar(
        select(ProjectInsightAcknowledgement).where(
            ProjectInsightAcknowledgement.project_id == project_id,
            ProjectInsightAcknowledgement.insight_id == insight_id,
        )
    )
    if ack is None:
        raise HTTPException(status_code=404, detail="Insight not reviewed")

    ack.status = "reopened"
    ack.user_id = context.user_id

    session.add(
        AuditEvent(
            tenant_id=context.tenant_id,
            project_id=project_id,
            user_id=context.user_id,
            event_type="project_insight_reopened",
            prompt_type=insight_id[:100],
            scope="project_insight",
            title=f"Reopened insight {insight_id}",
        )
    )
    await session.commit()

    return ReopenInsightResponse(insightId=insight_id, status="reopened")
