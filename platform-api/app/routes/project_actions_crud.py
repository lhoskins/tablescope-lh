"""Project Actions: list, board, create, read and update.

Split from ``project_actions.py``; siblings: ``project_actions_shared.py``,
``project_actions_lifecycle.py`` and ``project_actions_comments.py``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.project_action import ProjectAction, ProjectActionComment, ProjectActionSubtask
from app.models.user import User
from app.routes.project_actions_shared import (
    _DUE_STATE_LABELS,
    _GROUP_LABELS,
    _PRIORITY_ORDER,
    _after_mutation,
    _apply_status_transition,
    _audit,
    _ensure_can_complete,
    _get_action,
    _group_key,
    _group_sort_key,
    _insight_fingerprint,
    _recalculate_action_progress,
    _require_project_access,
    _risk_impact_from_snapshot,
    _status_percent,
    _validate_owner,
    _validate_priority_value,
    _validate_status_value,
)
from app.schemas.project_action import (
    ProjectActionBoardSummary,
    ProjectActionCountForInsightRequest,
    ProjectActionCountForInsightResponse,
    ProjectActionCreate,
    ProjectActionGroupSummary,
    ProjectActionListItem,
    ProjectActionListResponse,
    ProjectActionOut,
    ProjectActionUpdate,
)
from app.services.ai_intelligence_client import AIUnavailableError, generate_action_draft

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["project-actions"])

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
        ProjectAction.deleted_at.is_(None),
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


class DraftActionFromInsightRequest(BaseModel):
    insight_type: str
    title: str
    summary: str
    recommended_action: str = ""
    severity: str = "info"
    sources: dict[str, Any] = Field(default_factory=dict)
    supporting_sources: list[str] = Field(default_factory=list)
    explanation: dict[str, Any] | None = None


@router.post("/{project_id}/actions/draft-from-insight")
async def draft_action_from_insight(
    project_id: int,
    body: DraftActionFromInsightRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Generate a structured action draft from an insight using the AI server."""
    await _require_project_access(project_id, session, context)
    try:
        draft = await generate_action_draft(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            project_id=project_id,
            insight=body.model_dump(),
        )
    except AIUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service is disabled or unavailable",
        )
    return draft


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
                ProjectAction.deleted_at.is_(None),
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
        ProjectAction.deleted_at.is_(None),
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

