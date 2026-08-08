"""Project CRUD routes with tenant scoping.

Every project belongs to a tenant. The owner is the user who created it.
Private projects (is_shared=False) are visible only to the owner and assigned
members. Shared projects are visible to all active members.

Split from ``projects.py``; see ``projects_shared.py`` for the helper cluster.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.project import Project, ProjectMember
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.project import (
    ProjectCreate,
    ProjectRead,
    ProjectUpdate,
)
from app.services.customer_folders import CustomerFolderService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectRead])
async def list_projects(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[ProjectRead]:
    """List projects visible to the caller.

    A project is visible if:
    - The user is the owner, OR
    - The user is an active member of the project.
    """
    member_sub = (
        select(ProjectMember.project_id)
        .where(
            ProjectMember.user_id == context.user_id,
            ProjectMember.is_active.is_(True),
        )
    )
    query = (
        select(Project)
        .where(
            Project.tenant_id == context.tenant_id,
            or_(
                Project.owner_id == context.user_id,
                Project.id.in_(member_sub),
            ),
        )
        .order_by(Project.created_at.desc())
    )
    rows = await session.scalars(query)
    return [ProjectRead.model_validate(p) for p in rows]


@router.post(
    "",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_project(
    payload: ProjectCreate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> ProjectRead:
    """Create a new project owned by the caller."""
    tenant = await session.get(Tenant, context.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    user = await session.get(User, context.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    project = Project(
        tenant_id=context.tenant_id,
        owner_id=context.user_id,
        name=payload.name,
        description=payload.description,
        type=payload.type,
        is_shared=False,
    )
    session.add(project)
    await session.flush()

    member = ProjectMember(
        project_id=project.id,
        user_id=context.user_id,
        role="owner",
        is_active=True,
    )
    session.add(member)

    folders = CustomerFolderService()
    user_ext = user.external_id or str(user.id)
    folders.ensure_user_folders(tenant.slug, user_ext)

    await session.commit()
    await session.refresh(project)
    return ProjectRead.model_validate(project)


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> ProjectRead:
    """Get a project by ID (must be owner or active member)."""
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.owner_id != context.user_id:
        member = await session.get(ProjectMember, (project_id, context.user_id))
        if member is None or not member.is_active:
            raise HTTPException(status_code=403, detail="Not a member of this project")

    return ProjectRead.model_validate(project)


@router.put("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: int,
    payload: ProjectUpdate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> ProjectRead:
    """Update a project (owner or admin only)."""
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.owner_id != context.user_id and context.role != "admin":
        raise HTTPException(status_code=403, detail="Only the project owner or admin can edit")

    if payload.name is not None:
        project.name = payload.name
    if payload.description is not None:
        project.description = payload.description
    if payload.type is not None:
        project.type = payload.type
    if payload.is_shared is not None:
        project.is_shared = payload.is_shared
    if payload.scoping_enabled is not None:
        project.scoping_enabled = payload.scoping_enabled

    await session.commit()
    await session.refresh(project)
    return ProjectRead.model_validate(project)


@router.delete("/{project_id}")
async def delete_project(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> Response:
    """Delete a project (owner or admin only)."""
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.owner_id != context.user_id and context.role != "admin":
        raise HTTPException(status_code=403, detail="Only the project owner or admin can delete")

    await session.delete(project)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

