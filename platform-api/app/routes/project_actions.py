"""Project Actions API.

Tenant- and project-scoped governed action items created from insights.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.audit_event import AuditEvent
from app.models.project import Project, ProjectMember
from app.models.project_action import ProjectAction, ProjectActionSubtask
from app.models.user import User
from app.schemas.project_action import (
    ProjectActionCountForInsightRequest,
    ProjectActionCountForInsightResponse,
    ProjectActionCreate,
    ProjectActionListItem,
    ProjectActionListResponse,
    ProjectActionOut,
    ProjectActionSubtaskCreate,
    ProjectActionSubtaskOut,
    ProjectActionSubtaskUpdate,
    ProjectActionUpdate,
)
from app.services.project_ai_context import invalidate_project_ai_context
from app.services.project_insight_service import mark_project_insight_stale

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["project-actions"])

_STATUS_ORDER: dict[str, int] = {
    "not_started": 0,
    "blocked": 1,
    "in_progress": 2,
    "completed": 3,
    "cancelled": 4,
}

_PRIORITY_ORDER: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}


def _normalized(value: str | None) -> str:
    return " ".join((value or "").lower().split())


def _insight_fingerprint(
    project_id: int,
    source_type: str | None,
    title: str | None,
    snapshot: dict[str, Any] | None,
) -> str | None:
    """Stable content-derived fingerprint for cross-run insight deduplication."""
    if not title:
        return None

    evidence: list[str] = []
    if snapshot:
        sources = snapshot.get("sources") or {}
        if isinstance(sources, dict):
            evidence.extend(sources.get("tables") or [])
            evidence.extend(sources.get("documents") or [])
        evidence.extend(snapshot.get("supporting_sources") or [])
        evidence.extend(snapshot.get("source_tables") or [])
        evidence.extend(snapshot.get("evidence") or [])

    components = [
        str(project_id),
        _normalized(source_type),
        _normalized(title),
        *sorted({_normalized(str(e)) for e in evidence if e}),
    ]

    payload = "|".join(components)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:64]


def _status_percent(status: str) -> int:
    if status == "completed":
        return 100
    if status in ("not_started", "cancelled"):
        return 0
    return -1  # preserve explicit percent for in_progress/blocked


def _validate_status_value(value: str) -> None:
    allowed = {"not_started", "in_progress", "blocked", "completed", "cancelled"}
    if value not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid status '{value}'; allowed: {allowed}",
        )


def _validate_priority_value(value: str) -> None:
    allowed = {"low", "medium", "high", "critical"}
    if value not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid priority '{value}'; allowed: {allowed}",
        )


async def _require_project_access(
    project_id: int,
    session: AsyncSession,
    context: RequestContext,
) -> Project:
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No access to this project",
        )
    return project


async def _is_active_project_member(
    project_id: int,
    user_id: int | None,
    session: AsyncSession,
) -> bool:
    if user_id is None:
        return True
    member = await session.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
            ProjectMember.is_active.is_(True),
        )
    )
    return member is not None


async def _get_action(
    session: AsyncSession,
    context: RequestContext,
    project_id: int,
    action_id: int,
    active_only: bool = True,
) -> ProjectAction:
    stmt = (
        select(ProjectAction)
        .options(selectinload(ProjectAction.subtasks))
        .where(
            ProjectAction.tenant_id == context.tenant_id,
            ProjectAction.project_id == project_id,
            ProjectAction.id == action_id,
        )
    )
    if active_only:
        stmt = stmt.where(ProjectAction.archived_at.is_(None))
    action = await session.scalar(stmt)
    if action is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Action not found",
        )
    return action


def _blocking_subtasks(action: ProjectAction) -> list[ProjectActionSubtask]:
    """Return active required subtasks that are not completed."""
    return [
        s
        for s in action.subtasks
        if s.archived_at is None
        and s.is_required
        and s.status != "cancelled"
        and s.status != "completed"
    ]


def _active_required_subtasks(action: ProjectAction) -> list[ProjectActionSubtask]:
    return [
        s
        for s in action.subtasks
        if s.archived_at is None and s.is_required and s.status != "cancelled"
    ]


def _recalculate_action_progress(action: ProjectAction) -> None:
    """Recompute parent percent and consistency from active required subtasks."""
    active = _active_required_subtasks(action)
    if not active:
        if action.status == "completed":
            action.percent_complete = 100
        else:
            action.percent_complete = 0
        return

    for s in active:
        sp = _status_percent(s.status)
        if sp >= 0:
            s.percent_complete = sp

    total = sum(s.percent_complete for s in active)
    action.percent_complete = round(total / len(active))

    if all(s.status == "completed" for s in active) and action.status != "completed":
        action.status = "completed"
        action.completed_at = datetime.now(UTC)
        action.percent_complete = 100
    elif action.status == "completed" and not all(
        s.status == "completed" for s in active
    ):
        action.status = "in_progress"
        action.completed_at = None

    if action.status == "completed" and action.percent_complete != 100:
        action.percent_complete = 100


def _ensure_can_complete(action: ProjectAction) -> None:
    blocking = _blocking_subtasks(action)
    if blocking:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Cannot complete while required subtasks remain incomplete",
                "blocking_subtasks": [{"id": s.id, "title": s.title} for s in blocking],
            },
        )


def _apply_status_transition(action: ProjectAction, new_status: str) -> None:
    now = datetime.now(UTC)
    if new_status == action.status:
        return
    if new_status == "completed":
        _ensure_can_complete(action)
        action.status = "completed"
        action.completed_at = now
        action.percent_complete = 100
    else:
        if action.status == "completed":
            action.completed_at = None
        action.status = new_status
        if new_status in ("in_progress", "blocked") and action.started_at is None:
            action.started_at = now
        if new_status == "not_started":
            action.started_at = None
            action.percent_complete = 0
        _recalculate_action_progress(action)


async def _validate_owner(
    project_id: int,
    owner_user_id: int | None,
    session: AsyncSession,
) -> None:
    if owner_user_id is None:
        return
    if not await _is_active_project_member(project_id, owner_user_id, session):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Owner must be an active project member",
        )


async def _audit(
    session: AsyncSession,
    *,
    context: RequestContext,
    event_type: str,
    project_id: int,
    action_id: int | None = None,
    subtask_id: int | None = None,
    title: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    audit_title = title
    if payload:
        audit_title = f"{title} | {json.dumps(payload, default=str, separators=(',', ':'))[:500]}"
    session.add(
        AuditEvent(
            tenant_id=context.tenant_id,
            project_id=project_id,
            user_id=context.user_id,
            event_type=event_type,
            scope="project_action",
            prompt_type=(f"{action_id}:{subtask_id}" if action_id and subtask_id else str(action_id))[:100],
            title=audit_title,
            tables_queried=[],
            documents_read=[],
            duration_ms=None,
        )
    )


async def _after_mutation(
    session: AsyncSession,
    context: RequestContext,
    project_id: int,
) -> None:
    """Invalidate caches and mark Project Insight stale (best-effort)."""
    invalidate_project_ai_context(context.tenant_id, project_id)
    try:
        await mark_project_insight_stale(
            session,
            tenant_id=context.tenant_id,
            project_id=project_id,
        )
    except Exception:
        logger.exception("mark_project_insight_stale failed for project %s", project_id)


def _subtask_payload(subtask: ProjectActionSubtask) -> dict[str, Any]:
    return {
        "id": subtask.id,
        "title": subtask.title,
        "status": subtask.status,
        "percent_complete": subtask.percent_complete,
        "is_required": subtask.is_required,
    }


@router.get("/{project_id}/actions", response_model=ProjectActionListResponse)
async def list_actions(
    project_id: int,
    status: str | None = None,
    priority: str | None = None,
    owner_user_id: int | None = None,
    overdue: bool | None = None,
    source_insight_fingerprint: str | None = None,
    q: str | None = None,
    include_archived: bool = False,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> ProjectActionListResponse:
    """List project actions with filters and subtask counts."""
    await _require_project_access(project_id, session, context)

    base = select(ProjectAction).where(
        ProjectAction.tenant_id == context.tenant_id,
        ProjectAction.project_id == project_id,
    )
    if not include_archived:
        base = base.where(ProjectAction.archived_at.is_(None))
    if status:
        _validate_status_value(status)
        base = base.where(ProjectAction.status == status)
    if priority:
        _validate_priority_value(priority)
        base = base.where(ProjectAction.priority == priority)
    if owner_user_id is not None:
        base = base.where(ProjectAction.owner_user_id == owner_user_id)
    if overdue is not None:
        now = datetime.now(UTC)
        if overdue:
            base = base.where(
                ProjectAction.due_date.isnot(None),
                ProjectAction.due_date < now,
                ProjectAction.status.notin_(["completed", "cancelled"]),
                ProjectAction.archived_at.is_(None),
            )
        else:
            base = base.where(
                (ProjectAction.due_date.is_(None)) | (ProjectAction.due_date >= now)
            )
    if source_insight_fingerprint:
        base = base.where(
            ProjectAction.source_insight_fingerprint == source_insight_fingerprint
        )
    if q:
        pattern = f"%{q}%"
        base = base.where(
            (ProjectAction.title.ilike(pattern))
            | (ProjectAction.description.ilike(pattern))
            | (ProjectAction.source_insight_title.ilike(pattern))
        )

    total = await session.scalar(
        select(func.count()).select_from(base.subquery())
    ) or 0

    priority_order = case(
        (ProjectAction.priority == "critical", _PRIORITY_ORDER["critical"]),
        (ProjectAction.priority == "high", _PRIORITY_ORDER["high"]),
        (ProjectAction.priority == "medium", _PRIORITY_ORDER["medium"]),
        (ProjectAction.priority == "low", _PRIORITY_ORDER["low"]),
        else_=_PRIORITY_ORDER["medium"],
    )

    stmt = (
        base.order_by(
            priority_order,
            ProjectAction.due_date.asc(),
            ProjectAction.updated_at.desc(),
        )
        .limit(limit)
        .offset(offset)
    )

    rows = (await session.execute(stmt)).scalars().all()

    owner_ids = {a.owner_user_id for a in rows if a.owner_user_id}
    users = {}
    if owner_ids:
        users = {
            u.id: (u.display_name or u.email or "")
            for u in (await session.scalars(select(User).where(User.id.in_(owner_ids)))).all()
        }

    action_ids = [a.id for a in rows]
    subtask_counts: dict[int, tuple[int, int]] = {}
    if action_ids:
        counts = await session.execute(
            select(
                ProjectActionSubtask.action_id,
                func.count(),
                func.coalesce(
                    func.sum(
                        case(
                            (ProjectActionSubtask.archived_at.is_(None), 1),
                            else_=0,
                        )
                    ),
                    0,
                ),
            )
            .where(ProjectActionSubtask.action_id.in_(action_ids))
            .group_by(ProjectActionSubtask.action_id)
        )
        for aid, total_st, active_st in counts:
            subtask_counts[aid] = (int(active_st), int(total_st))

    items = []
    for a in rows:
        active, total = subtask_counts.get(a.id, (0, 0))
        items.append(
            ProjectActionListItem(
                id=a.id,
                title=a.title,
                status=a.status,
                priority=a.priority,
                owner_user_id=a.owner_user_id,
                owner_name=users.get(a.owner_user_id) if a.owner_user_id is not None else None,
                due_date=a.due_date,
                percent_complete=a.percent_complete,
                source_insight_type=a.source_insight_type,
                source_insight_title=a.source_insight_title,
                source_insight_snapshot=a.source_insight_snapshot,
                active_subtasks=active,
                total_subtasks=total,
                updated_at=a.updated_at,
                archived_at=a.archived_at,
            )
        )
    return ProjectActionListResponse(items=items, total=total)


@router.post("/{project_id}/actions", response_model=ProjectActionOut, status_code=201)
async def create_action(
    project_id: int,
    body: ProjectActionCreate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> ProjectActionOut:
    """Create a project action, optionally with initial subtasks."""
    await _require_project_access(project_id, session, context)

    if body.idempotency_key:
        existing = await session.scalar(
            select(ProjectAction).where(
                ProjectAction.tenant_id == context.tenant_id,
                ProjectAction.project_id == project_id,
                ProjectAction.idempotency_key == body.idempotency_key,
            )
        )
        if existing:
            await session.refresh(existing, ["subtasks"])
            return ProjectActionOut.model_validate(existing)

    if body.status != "not_started":
        _validate_status_value(body.status)
    if body.priority:
        _validate_priority_value(body.priority)

    await _validate_owner(project_id, body.owner_user_id, session)
    for st in body.initial_subtasks:
        if st.owner_user_id is not None:
            await _validate_owner(project_id, st.owner_user_id, session)

    fingerprint = _insight_fingerprint(
        project_id,
        body.source_insight_type,
        body.source_insight_title or body.title,
        body.source_insight_snapshot,
    )

    action = ProjectAction(
        tenant_id=context.tenant_id,
        project_id=project_id,
        title=body.title.strip(),
        description=body.description.strip() if body.description else None,
        status=body.status,
        priority=body.priority,
        owner_user_id=body.owner_user_id,
        due_date=body.due_date,
        source_type=body.source_type,
        source_insight_id=body.source_insight_id,
        source_insight_fingerprint=fingerprint,
        source_insight_type=body.source_insight_type,
        source_insight_title=body.source_insight_title,
        source_insight_snapshot=body.source_insight_snapshot,
        created_by_user_id=context.user_id,
        updated_by_user_id=context.user_id,
        idempotency_key=body.idempotency_key,
    )

    if action.status in ("in_progress", "blocked"):
        action.started_at = datetime.now(UTC)

    session.add(action)
    await session.flush()
    await session.refresh(action)

    for i, st in enumerate(body.initial_subtasks):
        sub = ProjectActionSubtask(
            tenant_id=context.tenant_id,
            project_id=project_id,
            action_id=action.id,
            title=st.title.strip(),
            description=st.description.strip() if st.description else None,
            status=st.status,
            percent_complete=st.percent_complete,
            owner_user_id=st.owner_user_id,
            due_date=st.due_date,
            position=i,
            is_required=st.is_required,
            created_by_user_id=context.user_id,
            updated_by_user_id=context.user_id,
        )
        sp = _status_percent(sub.status)
        if sp >= 0:
            sub.percent_complete = sp
        session.add(sub)

    await session.flush()
    await session.refresh(action, ["subtasks"])
    _recalculate_action_progress(action)

    if action.status == "completed":
        _ensure_can_complete(action)
        action.completed_at = datetime.now(UTC)
        action.percent_complete = 100

    await _audit(
        session,
        context=context,
        event_type="project_action_created",
        project_id=project_id,
        action_id=action.id,
        title=action.title,
        payload={
            "source_insight_type": action.source_insight_type,
            "source_insight_title": action.source_insight_title,
        },
    )
    await session.commit()
    await session.refresh(action, ["subtasks"])
    await _after_mutation(session, context, project_id)

    return ProjectActionOut.model_validate(action)


@router.post(
    "/{project_id}/actions:count-for-insight",
    response_model=ProjectActionCountForInsightResponse,
)
async def count_for_insight(
    project_id: int,
    body: ProjectActionCountForInsightRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> ProjectActionCountForInsightResponse:
    """Return how many active actions match the supplied insight fingerprint."""
    await _require_project_access(project_id, session, context)
    fingerprint = _insight_fingerprint(
        project_id,
        body.source_insight_type,
        body.source_insight_title,
        body.source_insight_snapshot,
    )
    if fingerprint is None:
        return ProjectActionCountForInsightResponse(count=0, action_ids=[])
    rows = (
        await session.scalars(
            select(ProjectAction.id).where(
                ProjectAction.tenant_id == context.tenant_id,
                ProjectAction.project_id == project_id,
                ProjectAction.source_insight_fingerprint == fingerprint,
                ProjectAction.archived_at.is_(None),
            )
        )
    ).all()
    return ProjectActionCountForInsightResponse(
        count=len(rows), action_ids=list(rows)
    )


@router.get("/{project_id}/actions/{action_id}", response_model=ProjectActionOut)
async def get_action(
    project_id: int,
    action_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> ProjectActionOut:
    """Return action detail with ordered subtasks."""
    await _require_project_access(project_id, session, context)
    action = await _get_action(session, context, project_id, action_id)
    return ProjectActionOut.model_validate(action)


@router.patch("/{project_id}/actions/{action_id}", response_model=ProjectActionOut)
async def update_action(
    project_id: int,
    action_id: int,
    body: ProjectActionUpdate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> ProjectActionOut:
    """Update action metadata, status, or due date; server recomputes percent."""
    await _require_project_access(project_id, session, context)
    action = await _get_action(session, context, project_id, action_id)

    if action.archived_at is not None and body.archived_at is None:
        action.archived_at = None

    if body.title is not None:
        action.title = body.title.strip()
    if body.description is not None:
        action.description = body.description.strip() if body.description else None
    if body.priority is not None:
        _validate_priority_value(body.priority)
        action.priority = body.priority
    if body.owner_user_id is not None:
        await _validate_owner(project_id, body.owner_user_id, session)
        action.owner_user_id = body.owner_user_id
    if body.due_date is not None:
        action.due_date = body.due_date
    if body.status is not None:
        _validate_status_value(body.status)
        _apply_status_transition(action, body.status)

    action.updated_by_user_id = context.user_id

    old_subtasks = [s.id for s in action.subtasks]
    await _audit(
        session,
        context=context,
        event_type="project_action_updated",
        project_id=project_id,
        action_id=action.id,
        title=action.title,
        payload={
            "status": action.status,
            "percent_complete": action.percent_complete,
            "subtasks": old_subtasks,
        },
    )
    await session.commit()
    await session.refresh(action, ["subtasks"])
    await _after_mutation(session, context, project_id)

    return ProjectActionOut.model_validate(action)


@router.delete("/{project_id}/actions/{action_id}")
async def archive_action(
    project_id: int,
    action_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Soft-archive an action and its subtasks."""
    await _require_project_access(project_id, session, context)
    action = await _get_action(session, context, project_id, action_id)
    now = datetime.now(UTC)
    action.archived_at = now
    action.updated_by_user_id = context.user_id
    for sub in action.subtasks:
        sub.archived_at = now
        sub.updated_by_user_id = context.user_id

    await _audit(
        session,
        context=context,
        event_type="project_action_archived",
        project_id=project_id,
        action_id=action.id,
        title=action.title,
        payload={"subtasks_archived": [s.id for s in action.subtasks]},
    )
    await session.commit()
    await _after_mutation(session, context, project_id)
    return {"status": "archived", "id": action.id}


@router.post(
    "/{project_id}/actions/{action_id}/subtasks",
    response_model=ProjectActionSubtaskOut,
    status_code=201,
)
async def create_subtask(
    project_id: int,
    action_id: int,
    body: ProjectActionSubtaskCreate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> ProjectActionSubtaskOut:
    """Add a subtask to an action; recomputes parent progress."""
    await _require_project_access(project_id, session, context)
    action = await _get_action(session, context, project_id, action_id)

    if body.owner_user_id is not None:
        await _validate_owner(project_id, body.owner_user_id, session)

    max_position = await session.scalar(
        select(func.coalesce(func.max(ProjectActionSubtask.position), -1)).where(
            ProjectActionSubtask.action_id == action.id
        )
    )
    if max_position is None:
        max_position = -1

    sub = ProjectActionSubtask(
        tenant_id=context.tenant_id,
        project_id=project_id,
        action_id=action.id,
        title=body.title.strip(),
        description=body.description.strip() if body.description else None,
        status=body.status,
        percent_complete=body.percent_complete,
        owner_user_id=body.owner_user_id,
        due_date=body.due_date,
        position=max_position + 1,
        is_required=body.is_required,
        created_by_user_id=context.user_id,
        updated_by_user_id=context.user_id,
    )
    sp = _status_percent(sub.status)
    if sp >= 0:
        sub.percent_complete = sp
    session.add(sub)
    await session.flush()
    await session.refresh(action, ["subtasks"])
    _recalculate_action_progress(action)
    action.updated_by_user_id = context.user_id

    await _audit(
        session,
        context=context,
        event_type="project_action_subtask_created",
        project_id=project_id,
        action_id=action.id,
        subtask_id=sub.id,
        title=sub.title,
        payload=_subtask_payload(sub),
    )
    await session.commit()
    await session.refresh(sub)
    await _after_mutation(session, context, project_id)
    return ProjectActionSubtaskOut.model_validate(sub)


@router.patch(
    "/{project_id}/actions/{action_id}/subtasks/{subtask_id}",
    response_model=ProjectActionSubtaskOut,
)
async def update_subtask(
    project_id: int,
    action_id: int,
    subtask_id: int,
    body: ProjectActionSubtaskUpdate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> ProjectActionSubtaskOut:
    """Update a subtask; parent progress and completion are recalculated."""
    await _require_project_access(project_id, session, context)
    action = await _get_action(session, context, project_id, action_id)
    sub = next((s for s in action.subtasks if s.id == subtask_id), None)
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subtask not found",
        )

    if sub.archived_at is not None and body.archived_at is None:
        sub.archived_at = None

    if body.title is not None:
        sub.title = body.title.strip()
    if body.description is not None:
        sub.description = body.description.strip() if body.description else None
    if body.status is not None:
        _validate_status_value(body.status)
        sub.status = body.status
        sp = _status_percent(sub.status)
        if sp >= 0:
            sub.percent_complete = sp
    if body.percent_complete is not None:
        if sub.status == "completed":
            sub.percent_complete = 100
        elif sub.status == "not_started":
            sub.percent_complete = 0
        else:
            sub.percent_complete = max(0, min(100, body.percent_complete))
    if body.owner_user_id is not None:
        await _validate_owner(project_id, body.owner_user_id, session)
        sub.owner_user_id = body.owner_user_id
    if body.due_date is not None:
        sub.due_date = body.due_date
    if body.position is not None:
        sub.position = body.position
    if body.is_required is not None:
        sub.is_required = body.is_required

    sub.updated_by_user_id = context.user_id
    await session.flush()
    _recalculate_action_progress(action)
    action.updated_by_user_id = context.user_id

    await _audit(
        session,
        context=context,
        event_type="project_action_subtask_updated",
        project_id=project_id,
        action_id=action.id,
        subtask_id=sub.id,
        title=sub.title,
        payload=_subtask_payload(sub),
    )
    await session.commit()
    await session.refresh(sub)
    await _after_mutation(session, context, project_id)
    return ProjectActionSubtaskOut.model_validate(sub)


@router.delete("/{project_id}/actions/{action_id}/subtasks/{subtask_id}")
async def archive_subtask(
    project_id: int,
    action_id: int,
    subtask_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Soft-archive a subtask; recomputes parent progress."""
    await _require_project_access(project_id, session, context)
    action = await _get_action(session, context, project_id, action_id)
    sub = next((s for s in action.subtasks if s.id == subtask_id), None)
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subtask not found",
        )
    now = datetime.now(UTC)
    sub.archived_at = now
    sub.updated_by_user_id = context.user_id
    await session.flush()
    _recalculate_action_progress(action)
    action.updated_by_user_id = context.user_id

    await _audit(
        session,
        context=context,
        event_type="project_action_subtask_archived",
        project_id=project_id,
        action_id=action.id,
        subtask_id=sub.id,
        title=sub.title,
        payload={"archived_at": now.isoformat()},
    )
    await session.commit()
    await _after_mutation(session, context, project_id)
    return {"status": "archived", "id": sub.id}
