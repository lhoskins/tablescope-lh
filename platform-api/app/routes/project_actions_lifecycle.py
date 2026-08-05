"""Project Actions lifecycle: archive/restore, subtasks and bulk updates.

Split from ``project_actions.py``; siblings: ``project_actions_shared.py``,
``project_actions_crud.py`` and ``project_actions_comments.py``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.project_action import ProjectAction, ProjectActionSubtask
from app.routes.project_actions_shared import (
    _after_mutation,
    _apply_status_transition,
    _audit,
    _get_action,
    _recalculate_action_progress,
    _require_project_access,
    _status_percent,
    _subtask_payload,
    _validate_owner,
    _validate_priority_value,
    _validate_status_value,
)
from app.schemas.project_action import (
    ProjectActionBulkResponse,
    ProjectActionBulkResultItem,
    ProjectActionBulkUpdate,
    ProjectActionOut,
    ProjectActionSubtaskCreate,
    ProjectActionSubtaskOut,
    ProjectActionSubtaskUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["project-actions"])

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


@router.delete("/{project_id}/actions/{action_id}/permanent")
async def delete_action_permanently(
    project_id: int,
    action_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Permanently tombstone an already-archived action. Requires prior archival."""
    await _require_project_access(project_id, session, context)
    action = await _get_action(
        session, context, project_id, action_id, active_only=False
    )
    if action.archived_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Archive the action before deletion",
        )
    previous = {
        "title": action.title,
        "archived_at": action.archived_at.isoformat() if action.archived_at else None,
    }
    action.deleted_at = datetime.now(UTC)
    action.lock_version = action.lock_version + 1
    action.updated_by_user_id = context.user_id

    await _audit(
        session,
        context=context,
        event_type="project_action_deleted_permanently",
        project_id=project_id,
        action_id=action.id,
        title=action.title,
        payload=previous,
    )
    await session.commit()
    await _after_mutation(session, context, project_id)
    return {"status": "deleted", "id": action.id, "lock_version": action.lock_version}


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

