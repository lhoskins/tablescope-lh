"""Shared helpers for the Project Actions API.

Validation, access checks, progress/status math, audit and grouping helpers
used by ``project_actions_crud.py``, ``project_actions_lifecycle.py`` and
``project_actions_comments.py``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.context import RequestContext
from app.models.audit_event import AuditEvent
from app.models.project import Project, ProjectMember
from app.models.project_action import ProjectAction, ProjectActionSubtask
from app.services.project_ai_context import invalidate_project_ai_context
from app.services.project_insight_service import mark_project_insight_stale

logger = logging.getLogger(__name__)

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
    exclude_deleted: bool = True,
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
        stmt = stmt.where(
            ProjectAction.archived_at.is_(None),
            ProjectAction.deleted_at.is_(None),
        )
    elif exclude_deleted:
        stmt = stmt.where(ProjectAction.deleted_at.is_(None))
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

