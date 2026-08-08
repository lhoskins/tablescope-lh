"""Project membership: list, invite, role changes and removal.

Split from ``projects.py``; see ``projects_shared.py`` for the helper cluster.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.database import get_db
from app.models.audit_event import AuditEvent
from app.models.project import Project, ProjectMember
from app.models.tenant import Tenant
from app.models.user import User
from app.routes.projects_shared import _is_project_admin
from app.schemas.project import (
    AddableUserRead,
    ProjectMemberRead,
)
from app.services.email_service import EmailService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/{project_id}/members", response_model=list[ProjectMemberRead])
async def list_members(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[ProjectMemberRead]:
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")
    rows = await session.scalars(
        select(ProjectMember).where(ProjectMember.project_id == project_id)
    )
    result = []
    for m in rows:
        user = await session.get(User, m.user_id)
        result.append(ProjectMemberRead(
            project_id=m.project_id,
            user_id=m.user_id,
            role=m.role,
            is_active=m.is_active,
            email=user.email if user else "",
            display_name=user.display_name if user else None,
        ))
    return result


@router.get("/{project_id}/addable-users", response_model=list[AddableUserRead])
async def list_addable_users(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[AddableUserRead]:
    """Active tenant users who can be added to the project.

    Excludes users who are already active members and the project owner.
    Restricted to project managers (owner / project-admin / tenant admin) so the
    member picker isn't exposed to plain viewers.
    """
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")
    if not await _is_project_admin(session, project, context):
        raise HTTPException(
            status_code=403,
            detail="Only a project owner or admin can manage members",
        )

    existing = await session.scalars(
        select(ProjectMember.user_id).where(
            ProjectMember.project_id == project_id,
            ProjectMember.is_active.is_(True),
        )
    )
    member_ids = set(existing.all())
    if project.owner_id:
        member_ids.add(project.owner_id)

    rows = await session.scalars(
        select(User)
        .where(User.tenant_id == context.tenant_id, User.is_active.is_(True))
        .order_by(User.email)
    )
    return [
        AddableUserRead(
            user_id=u.id,
            email=u.email,
            display_name=u.display_name,
            role=u.role,
        )
        for u in rows
        if u.id not in member_ids
    ]


@router.post("/{project_id}/members", response_model=ProjectMemberRead,
             status_code=status.HTTP_201_CREATED)
async def add_member(
    project_id: int,
    payload: dict,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> ProjectMemberRead:
    """Add a user to a project (project owner or admin only)."""
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")

    is_owner = project.owner_id == context.user_id
    is_project_admin = await session.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == context.user_id,
            ProjectMember.role.in_(["owner", "admin"]),
        )
    )
    if not is_owner and not is_project_admin and context.role != "admin":
        raise HTTPException(status_code=403, detail="Only project owner/admin can add members")

    user_id = payload.get("user_id")
    role = payload.get("role", "viewer")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    if role not in ("viewer", "editor", "admin"):
        raise HTTPException(
            status_code=400,
            detail="Invalid role. Must be viewer, editor, or admin",
        )

    user = await session.get(User, user_id)
    if user is None or user.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="User not found in tenant")

    existing = await session.get(ProjectMember, (project_id, user_id))
    if existing:
        if not existing.is_active:
            existing.is_active = True
            existing.role = role
            await session.commit()
        else:
            raise HTTPException(status_code=409, detail="User is already a member")
    else:
        member = ProjectMember(
            project_id=project_id, user_id=user_id, role=role, is_active=True,
        )
        session.add(member)
        await session.commit()

    result = ProjectMemberRead(
        project_id=project_id, user_id=user_id, role=role,
        is_active=True,
        email=user.email, display_name=user.display_name,
    )

    # Best-effort membership email; failures must not roll back the membership.
    try:
        tenant = await session.get(Tenant, project.tenant_id)
        actor = await session.get(User, context.user_id)
        settings = get_settings()
        await EmailService().send_transactional_email(
            to=user.email,
            template="project_membership",
            variables={
                "first_name": user.display_name or "",
                "project_name": project.name,
                "actor_name": (actor.display_name or actor.email if actor else None) or "A Tablescope user",
                "role_name": role.replace("_", " ").title(),
                "workspace_name": tenant.name if tenant else "Tablescope",
                "project_url": f"{settings.app_base_url}/projects/{project.id}",
            },
            tenant_id=project.tenant_id,
        )
    except Exception as exc:
        logger.warning(
            "Failed to send project membership email to %s for project %s: %s",
            user.email, project.id, exc,
        )

    return result


@router.put("/{project_id}/members/{user_id}/role")
async def update_member_role(
    project_id: int,
    user_id: int,
    payload: dict,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> ProjectMemberRead:
    """Update a project member's role. Only owner or project admin can do this."""
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.owner_id != context.user_id and context.role != "admin":
        caller_member = await session.get(ProjectMember, (project_id, context.user_id))
        if caller_member is None or caller_member.role != "admin":
            raise HTTPException(status_code=403, detail="Only project owner or admin can update roles")

    member = await session.get(ProjectMember, (project_id, user_id))
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")

    if member.role == "owner":
        raise HTTPException(status_code=403, detail="Cannot change the owner's role")

    new_role = payload.get("role", member.role)
    if new_role not in ("viewer", "editor", "admin"):
        raise HTTPException(status_code=400, detail="Invalid role. Must be viewer, editor, or admin")

    old_role = member.role
    if old_role == new_role:
        target_user = await session.get(User, user_id)
        return ProjectMemberRead(
            project_id=project_id,
            user_id=user_id,
            role=member.role,
            is_active=member.is_active,
            email=target_user.email if target_user else "",
            display_name=target_user.display_name if target_user else None,
        )

    member.role = new_role
    session.add(
        AuditEvent(
            tenant_id=context.tenant_id,
            project_id=project_id,
            user_id=context.user_id,
            event_type="project_member_role_change",
            scope=f"{old_role} -> {new_role}",
            title=f"Project member role changed{' (self)' if user_id == context.user_id else ''}",
            prompt_type="project_member_role_change",
            tables_queried=[],
            documents_read=[],
        )
    )
    await session.commit()

    target_user = await session.get(User, user_id)
    return ProjectMemberRead(
        project_id=project_id,
        user_id=user_id,
        role=member.role,
        is_active=member.is_active,
        email=target_user.email if target_user else "",
        display_name=target_user.display_name if target_user else None,
    )


@router.put("/{project_id}/members/{user_id}/deactivate")
async def deactivate_member(
    project_id: int,
    user_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> ProjectMemberRead:
    """Deactivate a project member (set inactive). Does not delete."""
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.owner_id != context.user_id and context.role != "admin":
        raise HTTPException(status_code=403, detail="Only project owner or admin can remove members")

    member = await session.get(ProjectMember, (project_id, user_id))
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")

    if member.role == "owner":
        raise HTTPException(status_code=403, detail="Cannot deactivate the project owner")

    member.is_active = False
    await session.commit()

    target_user = await session.get(User, user_id)
    return ProjectMemberRead(
        project_id=project_id,
        user_id=user_id,
        role=member.role,
        is_active=False,
        email=target_user.email if target_user else "",
        display_name=target_user.display_name if target_user else None,
    )


@router.delete("/{project_id}/members/{user_id}")
async def remove_member(
    project_id: int,
    user_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> Response:
    """Permanently delete an inactive member and move their datasources back.

    Only inactive members can be permanently deleted. When deleted, any
    datasources that were contributed by this user to the shared project
    are moved back to the user's private folder.
    """
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.owner_id != context.user_id and context.role != "admin":
        raise HTTPException(status_code=403, detail="Only project owner or admin can delete members")

    member = await session.get(ProjectMember, (project_id, user_id))
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")

    if member.is_active:
        raise HTTPException(
            status_code=400,
            detail="Member must be deactivated before permanent removal",
        )

    # Move shared datasources back to the user's private folder
    if project.is_shared:
        tenant = await session.get(Tenant, context.tenant_id)
        target_user = await session.get(User, user_id)
        if tenant and target_user:
            _move_shared_files_to_user(
                tenant_id=tenant.id,
                user_id=target_user.id,
            )

    await session.delete(member)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _move_shared_files_to_user(*, tenant_id: int, user_id: int) -> None:
    """Move datasources from shared folder back to user's private uploads."""
    import shutil

    settings = get_settings()
    base = Path(settings.customer_base_path)
    shared_uploads = base / str(tenant_id) / "shared" / "uploads"
    user_uploads = base / str(tenant_id) / str(user_id) / "uploads"

    if not shared_uploads.is_dir():
        return

    user_uploads.mkdir(parents=True, exist_ok=True)

    for f in shared_uploads.iterdir():
        if f.is_file():
            dest = user_uploads / f.name
            if not dest.exists():
                shutil.move(str(f), str(dest))
                logger.info("Moved %s back to user %s private folder", f.name, user_id)

