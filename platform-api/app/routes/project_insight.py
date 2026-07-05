"""Project Insight API — project-scoped executive AI insight + acknowledgements.

- ``GET  /api/projects/{project_id}/insight`` builds the project-scoped report.
- ``POST /api/projects/{project_id}/insights/{insight_id}/acknowledge`` records
  that a user reviewed an insight (audited: who + when). Reviewed does NOT mean
  approved — there is no Approve/Reject.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.audit_event import AuditEvent
from app.models.project import Project, ProjectMember
from app.models.project_insight_acknowledgement import (
    ProjectInsightAcknowledgement,
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
from app.services.project_insight_service import build_project_insight

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["project-insight"])


async def _require_project_access(
    project_id: int, session: AsyncSession, context: RequestContext
) -> Project:
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.owner_id == context.user_id or project.is_shared:
        return project
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


@router.get("/{project_id}/insight", response_model=ProjectInsightResponse)
async def get_project_insight(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> ProjectInsightResponse:
    """Return the project-scoped executive insight report for one project."""
    project = await _require_project_access(project_id, session, context)
    return await build_project_insight(
        session,
        project=project,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
    )


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
