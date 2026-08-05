"""Project Action comments.

Split from ``project_actions.py``; siblings: ``project_actions_shared.py``,
``project_actions_crud.py`` and ``project_actions_lifecycle.py``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.project_action import ProjectActionComment
from app.models.user import User
from app.routes.project_actions_shared import (
    _audit,
    _get_action,
    _require_project_access,
)
from app.schemas.project_action import (
    ProjectActionCommentCreate,
    ProjectActionCommentOut,
    ProjectActionCommentUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["project-actions"])

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
