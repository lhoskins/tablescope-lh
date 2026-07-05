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
