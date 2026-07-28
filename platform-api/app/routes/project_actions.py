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
from app.models.project_action import ProjectAction, ProjectActionComment, ProjectActionSubtask
from app.models.user import User
from app.schemas.project_action import (
    ProjectActionBoardSummary,
    ProjectActionBulkResponse,
    ProjectActionBulkResultItem,
    ProjectActionBulkUpdate,
    ProjectActionCommentCreate,
    ProjectActionCommentOut,
    ProjectActionCommentUpdate,
    ProjectActionCountForInsightRequest,
    ProjectActionCountForInsightResponse,
    ProjectActionCreate,
    ProjectActionGroupSummary,
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

_BOARD_GROUP_ORDER: dict[str, int] = {
    "blocked": 0,
    "in_progress": 1,
    "not_started": 2,
    "completed": 3,
    "cancelled": 4,
}

_GROUP_LABELS: dict[str, str] = {
    "blocked": "Blocked",
    "in_progress": "In progress",
    "not_started": "Not started",
    "completed": "Completed",
    "cancelled": "Cancelled",
}

_DUE_STATE_ORDER: dict[str, int] = {
    "overdue": 0,
    "due_today": 1,
    "due_this_week": 2,
    "upcoming": 3,
    "no_due": 4,
}

_DUE_STATE_LABELS: dict[str, str] = {
    "overdue": "Overdue",
    "due_today": "Due today",
    "due_this_week": "Due this week",
    "upcoming": "Upcoming",
    "no_due": "No due date",
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


def _due_state(due_date: datetime | None, now: datetime) -> str:
    if due_date is None:
        return "no_due"
    if due_date < now:
        return "overdue"
    if due_date.date() == now.date():
        return "due_today"
    delta = (due_date - now).days
    if delta <= 7:
        return "due_this_week"
    return "upcoming"


def _risk_impact_from_snapshot(snapshot: dict[str, Any] | None) -> str | None:
    if not snapshot:
        return None
    severity = snapshot.get("severity")
    if severity:
        return str(severity)
    return None


def _group_key(action: ProjectAction, group_by: str, now: datetime) -> str:
    if group_by == "priority":
        return action.priority
    if group_by == "owner":
        return str(action.owner_user_id or "unassigned")
    if group_by == "due_state":
        return _due_state(action.due_date, now)
    if group_by == "source_type":
        return action.source_type or "none"
    return action.status


def _group_sort_key(group_by: str, key: str) -> int | str:
    if group_by == "status":
        return _BOARD_GROUP_ORDER.get(key, 99)
    if group_by == "due_state":
        return _DUE_STATE_ORDER.get(key, 99)
    if group_by == "priority":
        return _PRIORITY_ORDER.get(key, 99)
    return key


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
                risk_impact=_risk_impact_from_snapshot(a.source_insight_snapshot),
                active_subtasks=active,
                total_subtasks=total,
                created_at=a.created_at,
                updated_at=a.updated_at,
                archived_at=a.archived_at,
                lock_version=a.lock_version,
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


@router.get("/{project_id}/actions/board", response_model=ProjectActionListResponse)
async def board_actions(
    project_id: int,
    status: str | None = None,
    priority: str | None = None,
    owner_user_id: int | None = None,
    overdue: bool | None = None,
    due_from: datetime | None = None,
    due_to: datetime | None = None,
    source_type: str | None = None,
    source_insight_type: str | None = None,
    source_insight_fingerprint: str | None = None,
    risk_impact: str | None = None,
    has_incomplete_required_subtasks: bool | None = None,
    q: str | None = None,
    include_archived: bool = False,
    sort_by: str = Query("updated", pattern="^(updated|created|due_date|priority|progress|title)$"),
    sort_direction: str = Query("desc", pattern="^(asc|desc)$"),
    group_by: str = Query("status", pattern="^(status|priority|owner|due_state|source_type|none)$"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> ProjectActionListResponse:
    """Monday-style board: filtered, grouped, sorted actions with summary."""
    await _require_project_access(project_id, session, context)

    if status:
        _validate_status_value(status)
    if priority:
        _validate_priority_value(priority)

    base = select(ProjectAction).where(
        ProjectAction.tenant_id == context.tenant_id,
        ProjectAction.project_id == project_id,
    )
    if not include_archived:
        base = base.where(ProjectAction.archived_at.is_(None))
    if status:
        base = base.where(ProjectAction.status == status)
    if priority:
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
    if due_from is not None:
        base = base.where(ProjectAction.due_date >= due_from)
    if due_to is not None:
        base = base.where(ProjectAction.due_date <= due_to)
    if source_type:
        base = base.where(ProjectAction.source_type == source_type)
    if source_insight_type:
        base = base.where(ProjectAction.source_insight_type == source_insight_type)
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

    rows = (await session.execute(base)).scalars().all()

    all_action_ids = [a.id for a in rows]
    subtask_stats: dict[int, tuple[int, int, int, int]] = {}
    if all_action_ids:
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
                func.coalesce(
                    func.sum(
                        case(
                            (
                                (ProjectActionSubtask.archived_at.is_(None))
                                & (ProjectActionSubtask.is_required.is_(True))
                                & (ProjectActionSubtask.status != "cancelled"),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                (ProjectActionSubtask.archived_at.is_(None))
                                & (ProjectActionSubtask.is_required.is_(True))
                                & (ProjectActionSubtask.status == "completed"),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
            )
            .where(ProjectActionSubtask.action_id.in_(all_action_ids))
            .group_by(ProjectActionSubtask.action_id)
        )
        for (
            aid,
            total_st,
            active_st,
            required_st,
            completed_required_st,
        ) in counts:
            subtask_stats[aid] = (
                int(active_st),
                int(total_st),
                int(required_st),
                int(completed_required_st),
            )

    comment_counts: dict[int, int] = {}
    if all_action_ids:
        counts = await session.execute(
            select(
                ProjectActionComment.action_id,
                func.count(),
            )
            .where(
                ProjectActionComment.action_id.in_(all_action_ids),
                ProjectActionComment.archived_at.is_(None),
            )
            .group_by(ProjectActionComment.action_id)
        )
        for aid, cnt in counts:
            comment_counts[aid] = int(cnt)

    filtered = []
    for a in rows:
        if risk_impact is not None:
            impact = _risk_impact_from_snapshot(a.source_insight_snapshot)
            if (impact or "").lower() != risk_impact.lower():
                continue
        if has_incomplete_required_subtasks is not None:
            _, _, required, completed = subtask_stats.get(a.id, (0, 0, 0, 0))
            incomplete = required - completed
            if has_incomplete_required_subtasks and incomplete == 0:
                continue
            if not has_incomplete_required_subtasks and incomplete > 0:
                continue
        filtered.append(a)

    total = len(filtered)
    now = datetime.now(UTC)

    summary = ProjectActionBoardSummary()
    for a in filtered:
        if a.archived_at is None and a.status not in ("completed", "cancelled"):
            summary.active += 1
            if a.due_date is not None and a.due_date < now:
                summary.overdue += 1
            summary.avg_progress += a.percent_complete
        if a.status == "completed" and a.archived_at is None:
            if (a.source_insight_type or "").lower() == "risk" or (
                (a.source_insight_snapshot or {}).get("insight_type") == "risk"
            ):
                summary.risk_mitigations_completed += 1
    active_for_avg = [
        a for a in filtered if a.archived_at is None and a.status not in ("completed", "cancelled")
    ]
    if active_for_avg:
        summary.avg_progress = round(
            sum(a.percent_complete for a in active_for_avg) / len(active_for_avg)
        )
    else:
        summary.avg_progress = 0

    group_map: dict[str, dict[str, Any]] = {}
    for a in filtered:
        key = _group_key(a, group_by, now)
        if key not in group_map:
            group_map[key] = {"count": 0, "overdue": 0, "progress_sum": 0, "progress_n": 0}
        g = group_map[key]
        g["count"] += 1
        if a.due_date is not None and a.due_date < now and a.status not in ("completed", "cancelled"):
            g["overdue"] += 1
        if a.archived_at is None and a.status not in ("completed", "cancelled"):
            g["progress_sum"] += a.percent_complete
            g["progress_n"] += 1
    groups = []
    for key in sorted(group_map.keys(), key=lambda k: _group_sort_key(group_by, k)):
        g = group_map[key]
        avg = round(g["progress_sum"] / g["progress_n"]) if g["progress_n"] else 0
        label = _GROUP_LABELS.get(key) or _DUE_STATE_LABELS.get(key) or key.capitalize()
        groups.append(
            ProjectActionGroupSummary(
                group=key,
                label=label,
                count=g["count"],
                overdue_count=g["overdue"],
                avg_progress=avg,
            )
        )
    summary.groups = groups

    def _sort_key(a: ProjectAction) -> tuple:
        group_rank = _group_sort_key(group_by, _group_key(a, group_by, now))
        val: Any
        if sort_by == "due_date":
            val = a.due_date or datetime.max.replace(tzinfo=UTC)
        elif sort_by == "priority":
            val = _PRIORITY_ORDER.get(a.priority, 99)
        elif sort_by == "progress":
            val = a.percent_complete
        elif sort_by == "title":
            val = (a.title or "").lower()
        elif sort_by == "created":
            val = a.created_at
        else:
            val = a.updated_at
        if sort_direction == "desc":
            if isinstance(val, datetime):
                val = -val.timestamp()
            elif isinstance(val, str):
                pass
            else:
                val = -val
        return (group_rank, val, a.id)

    sorted_rows = sorted(filtered, key=_sort_key)
    page = sorted_rows[offset : offset + limit]

    owner_ids = {a.owner_user_id for a in page if a.owner_user_id}
    users = {}
    if owner_ids:
        users = {
            u.id: (u.display_name or u.email or "")
            for u in (await session.scalars(select(User).where(User.id.in_(owner_ids)))).all()
        }

    items = []
    for a in page:
        active, total, required, completed_required = subtask_stats.get(a.id, (0, 0, 0, 0))
        items.append(
            ProjectActionListItem(
                id=a.id,
                title=a.title,
                description=a.description,
                status=a.status,
                priority=a.priority,
                owner_user_id=a.owner_user_id,
                owner_name=users.get(a.owner_user_id) if a.owner_user_id is not None else None,
                due_date=a.due_date,
                percent_complete=a.percent_complete,
                source_type=a.source_type,
                source_insight_id=a.source_insight_id,
                source_insight_fingerprint=a.source_insight_fingerprint,
                source_insight_type=a.source_insight_type,
                source_insight_title=a.source_insight_title,
                source_insight_snapshot=a.source_insight_snapshot,
                risk_impact=_risk_impact_from_snapshot(a.source_insight_snapshot),
                active_subtasks=active,
                total_subtasks=total,
                required_subtasks=required,
                completed_required_subtasks=completed_required,
                comment_count=comment_counts.get(a.id, 0),
                created_at=a.created_at,
                started_at=a.started_at,
                completed_at=a.completed_at,
                updated_at=a.updated_at,
                archived_at=a.archived_at,
                lock_version=a.lock_version,
            )
        )

    return ProjectActionListResponse(items=items, total=total, summary=summary)


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
    action = await _get_action(session, context, project_id, action_id, active_only=False)

    if body.expected_version is not None and action.lock_version != body.expected_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "This action changed while you were editing. Review the latest values and try again.",
                "expected_version": body.expected_version,
                "current_version": action.lock_version,
            },
        )

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
    action.lock_version = action.lock_version + 1

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
            "lock_version": action.lock_version,
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
    expected_version: int | None = Query(None),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Soft-archive an action and its subtasks."""
    await _require_project_access(project_id, session, context)
    action = await _get_action(session, context, project_id, action_id)
    if expected_version is not None and action.lock_version != expected_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "This action changed while you were editing. Review the latest values and try again.",
                "expected_version": expected_version,
                "current_version": action.lock_version,
            },
        )
    now = datetime.now(UTC)
    action.archived_at = now
    action.lock_version = action.lock_version + 1
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
    return {"status": "archived", "id": action.id, "lock_version": action.lock_version}


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

    now = datetime.now(UTC)
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
        effort_points=body.effort_points,
        completed_at=now if body.status == "completed" else None,
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

    if body.expected_version is not None and sub.lock_version != body.expected_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "This subtask changed while you were editing. Review the latest values and try again.",
                "expected_version": body.expected_version,
                "current_version": sub.lock_version,
            },
        )

    now = datetime.now(UTC)
    if sub.archived_at is not None and body.archived_at is None:
        sub.archived_at = None

    if body.title is not None:
        sub.title = body.title.strip()
    if body.description is not None:
        sub.description = body.description.strip() if body.description else None
    if body.status is not None:
        _validate_status_value(body.status)
        sub.status = body.status
        if sub.status == "completed":
            sub.percent_complete = 100
            sub.completed_at = now
        else:
            sp = _status_percent(sub.status)
            if sp >= 0:
                sub.percent_complete = sp
            if sub.completed_at is not None:
                sub.completed_at = None
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
    if body.effort_points is not None:
        sub.effort_points = body.effort_points

    sub.updated_by_user_id = context.user_id
    sub.lock_version = sub.lock_version + 1
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
    expected_version: int | None = Query(None),
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
    if expected_version is not None and sub.lock_version != expected_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "This subtask changed while you were editing. Review the latest values and try again.",
                "expected_version": expected_version,
                "current_version": sub.lock_version,
            },
        )
    now = datetime.now(UTC)
    sub.archived_at = now
    sub.lock_version = sub.lock_version + 1
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
    return {"status": "archived", "id": sub.id, "lock_version": sub.lock_version}


@router.post("/{project_id}/actions/{action_id}/restore", response_model=ProjectActionOut)
async def restore_action(
    project_id: int,
    action_id: int,
    expected_version: int | None = Query(None),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> ProjectActionOut:
    """Restore an archived action and its subtasks."""
    await _require_project_access(project_id, session, context)
    action = await _get_action(session, context, project_id, action_id, active_only=False)
    if action.archived_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action is not archived",
        )
    if expected_version is not None and action.lock_version != expected_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "This action changed while you were editing. Review the latest values and try again.",
                "expected_version": expected_version,
                "current_version": action.lock_version,
            },
        )
    action.archived_at = None
    action.lock_version = action.lock_version + 1
    action.updated_by_user_id = context.user_id
    for sub in action.subtasks:
        sub.archived_at = None
        sub.updated_by_user_id = context.user_id

    await _audit(
        session,
        context=context,
        event_type="project_action_restored",
        project_id=project_id,
        action_id=action.id,
        title=action.title,
        payload={"subtasks_restored": [s.id for s in action.subtasks]},
    )
    await session.commit()
    await session.refresh(action, ["subtasks"])
    await _after_mutation(session, context, project_id)
    return ProjectActionOut.model_validate(action)


@router.patch("/{project_id}/actions/bulk", response_model=ProjectActionBulkResponse)
async def bulk_update_actions(
    project_id: int,
    body: ProjectActionBulkUpdate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> ProjectActionBulkResponse:
    """Apply one field change to multiple actions in the same project."""
    await _require_project_access(project_id, session, context)

    actions = (
        await session.scalars(
            select(ProjectAction).where(
                ProjectAction.tenant_id == context.tenant_id,
                ProjectAction.project_id == project_id,
                ProjectAction.id.in_(body.action_ids),
            )
        )
    ).all()
    by_id = {a.id: a for a in actions}

    results = []
    for aid in body.action_ids:
        action = by_id.get(aid)
        if action is None:
            results.append(
                ProjectActionBulkResultItem(
                    action_id=aid,
                    success=False,
                    error="Action not found",
                )
            )
            continue
        expected = body.expected_versions.get(aid)
        if expected is not None and action.lock_version != expected:
            results.append(
                ProjectActionBulkResultItem(
                    action_id=aid,
                    success=False,
                    error="Conflict: action changed while editing",
                )
            )
            continue
        if action.archived_at is not None:
            results.append(
                ProjectActionBulkResultItem(
                    action_id=aid,
                    success=False,
                    error="Action is archived",
                )
            )
            continue

        try:
            if body.status is not None:
                _validate_status_value(body.status)
                _apply_status_transition(action, body.status)
            if body.priority is not None:
                _validate_priority_value(body.priority)
                action.priority = body.priority
            if body.owner_user_id is not None:
                await _validate_owner(project_id, body.owner_user_id, session)
                action.owner_user_id = body.owner_user_id
            if body.due_date is not None:
                action.due_date = body.due_date
        except HTTPException as e:
            results.append(
                ProjectActionBulkResultItem(
                    action_id=aid,
                    success=False,
                    error=str(e.detail),
                )
            )
            continue

        action.updated_by_user_id = context.user_id
        action.lock_version = action.lock_version + 1
        await _audit(
            session,
            context=context,
            event_type="project_action_bulk_updated",
            project_id=project_id,
            action_id=action.id,
            title=action.title,
            payload={"status": action.status, "priority": action.priority},
        )
        results.append(
            ProjectActionBulkResultItem(
                action_id=aid,
                success=True,
                lock_version=action.lock_version,
            )
        )

    await session.commit()
    for res in results:
        if res.success:
            action = by_id.get(res.action_id)
            if action:
                await session.refresh(action, ["subtasks"])
    await _after_mutation(session, context, project_id)
    return ProjectActionBulkResponse(results=results)


@router.get("/{project_id}/actions/{action_id}/comments", response_model=list[ProjectActionCommentOut])
async def list_comments(
    project_id: int,
    action_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[ProjectActionCommentOut]:
    """List active comments for an action."""
    await _require_project_access(project_id, session, context)
    action = await _get_action(session, context, project_id, action_id, active_only=False)
    comments = (
        await session.scalars(
            select(ProjectActionComment)
            .where(
                ProjectActionComment.tenant_id == context.tenant_id,
                ProjectActionComment.project_id == project_id,
                ProjectActionComment.action_id == action.id,
                ProjectActionComment.archived_at.is_(None),
            )
            .order_by(ProjectActionComment.created_at.desc())
        )
    ).all()
    user_ids = {c.author_user_id for c in comments if c.author_user_id}
    users = {}
    if user_ids:
        users = {
            u.id: (u.display_name or u.email or "")
            for u in (await session.scalars(select(User).where(User.id.in_(user_ids)))).all()
        }
    return [
        ProjectActionCommentOut(
            id=c.id,
            tenant_id=c.tenant_id,
            project_id=c.project_id,
            action_id=c.action_id,
            author_user_id=c.author_user_id,
            author_name=users.get(c.author_user_id) if c.author_user_id is not None else None,
            body=c.body,
            created_at=c.created_at,
            updated_at=c.updated_at,
            archived_at=c.archived_at,
        )
        for c in comments
    ]


@router.post(
    "/{project_id}/actions/{action_id}/comments",
    response_model=ProjectActionCommentOut,
    status_code=201,
)
async def create_comment(
    project_id: int,
    action_id: int,
    body: ProjectActionCommentCreate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> ProjectActionCommentOut:
    """Add a comment to an action."""
    await _require_project_access(project_id, session, context)
    action = await _get_action(session, context, project_id, action_id, active_only=False)
    comment = ProjectActionComment(
        tenant_id=context.tenant_id,
        project_id=project_id,
        action_id=action.id,
        author_user_id=context.user_id,
        body=body.body.strip(),
    )
    session.add(comment)
    await _audit(
        session,
        context=context,
        event_type="project_action_comment_created",
        project_id=project_id,
        action_id=action.id,
        title=action.title,
        payload={"comment_id": comment.id},
    )
    await session.commit()
    await session.refresh(comment)
    return ProjectActionCommentOut.model_validate(comment)


@router.patch("/{project_id}/actions/{action_id}/comments/{comment_id}", response_model=ProjectActionCommentOut)
async def update_comment(
    project_id: int,
    action_id: int,
    comment_id: int,
    body: ProjectActionCommentUpdate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> ProjectActionCommentOut:
    """Update or soft-delete a comment."""
    await _require_project_access(project_id, session, context)
    comment = await session.scalar(
        select(ProjectActionComment).where(
            ProjectActionComment.tenant_id == context.tenant_id,
            ProjectActionComment.project_id == project_id,
            ProjectActionComment.action_id == action_id,
            ProjectActionComment.id == comment_id,
        )
    )
    if comment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    is_admin = context.role in {"admin", "tenant_admin", "root_admin", "super_admin"}
    if comment.author_user_id != context.user_id and not is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to edit this comment")
    comment.body = body.body.strip()
    await _audit(
        session,
        context=context,
        event_type="project_action_comment_updated",
        project_id=project_id,
        action_id=action_id,
        title=comment.body[:100],
        payload={"comment_id": comment.id},
    )
    await session.commit()
    await session.refresh(comment)
    return ProjectActionCommentOut.model_validate(comment)


@router.delete("/{project_id}/actions/{action_id}/comments/{comment_id}")
async def archive_comment(
    project_id: int,
    action_id: int,
    comment_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Soft-delete a comment."""
    await _require_project_access(project_id, session, context)
    comment = await session.scalar(
        select(ProjectActionComment).where(
            ProjectActionComment.tenant_id == context.tenant_id,
            ProjectActionComment.project_id == project_id,
            ProjectActionComment.action_id == action_id,
            ProjectActionComment.id == comment_id,
        )
    )
    if comment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    is_admin = context.role in {"admin", "tenant_admin", "root_admin", "super_admin"}
    if comment.author_user_id != context.user_id and not is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to delete this comment")
    comment.archived_at = datetime.now(UTC)
    await _audit(
        session,
        context=context,
        event_type="project_action_comment_archived",
        project_id=project_id,
        action_id=action_id,
        title=comment.body[:100],
        payload={"comment_id": comment.id},
    )
    await session.commit()
    await session.refresh(comment)
    return {"status": "archived", "id": comment.id}
