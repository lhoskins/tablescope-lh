"""Project CRUD routes with tenant scoping.

Every project belongs to a tenant. The owner is the user who created it.
Private projects (is_shared=False) route queries to the owner's personal VDB.
Shared projects use the tenant-wide SharedVDB.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.project import Project, ProjectMember
from app.models.saved_query import SavedQuery
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.project import (
    ProjectCreate,
    ProjectMemberRead,
    ProjectRead,
    ProjectUpdate,
    SavedQueryCreate,
    SavedQueryRead,
    SavedQueryUpdate,
)
from app.services.customer_folders import CustomerFolderService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectRead])
async def list_projects(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[ProjectRead]:
    """List all projects in the caller's tenant."""
    query = (
        select(Project)
        .where(Project.tenant_id == context.tenant_id)
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
        is_shared=payload.is_shared,
    )
    session.add(project)
    await session.flush()

    # Add the creator as a project member with "owner" role
    member = ProjectMember(
        project_id=project.id,
        user_id=context.user_id,
        role="owner",
    )
    session.add(member)

    # Ensure project folders exist on disk
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
    """Get a project by ID (must belong to caller's tenant)."""
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")
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


# ── Project Members ──────────────────────────────────────────────────


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
            email=user.email if user else "",
            display_name=user.display_name if user else None,
        ))
    return result


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
    role = payload.get("role", "member")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")

    user = await session.get(User, user_id)
    if user is None or user.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="User not found in tenant")

    existing = await session.get(ProjectMember, (project_id, user_id))
    if existing:
        raise HTTPException(status_code=409, detail="User is already a member")

    member = ProjectMember(project_id=project_id, user_id=user_id, role=role)
    session.add(member)
    await session.commit()
    return ProjectMemberRead(
        project_id=project_id, user_id=user_id, role=role,
        email=user.email, display_name=user.display_name,
    )


@router.delete("/{project_id}/members/{user_id}")
async def remove_member(
    project_id: int,
    user_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> Response:
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.owner_id != context.user_id and context.role != "admin":
        raise HTTPException(status_code=403, detail="Only project owner or admin can remove members")

    member = await session.get(ProjectMember, (project_id, user_id))
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")

    await session.delete(member)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Saved Queries ────────────────────────────────────────────────────


@router.get("/{project_id}/queries", response_model=list[SavedQueryRead])
async def list_saved_queries(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[SavedQueryRead]:
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")
    rows = await session.scalars(
        select(SavedQuery).where(SavedQuery.project_id == project_id).order_by(SavedQuery.created_at.desc())
    )
    return [SavedQueryRead.model_validate(q) for q in rows]


@router.post("/{project_id}/queries", response_model=SavedQueryRead,
             status_code=status.HTTP_201_CREATED)
async def create_saved_query(
    project_id: int,
    payload: SavedQueryCreate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> SavedQueryRead:
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")
    query = SavedQuery(
        project_id=project_id,
        owner_id=context.user_id,
        name=payload.name,
        description=payload.description,
        left_datasource=payload.left_datasource,
        right_datasource=payload.right_datasource,
        join_type=payload.join_type,
        left_column=payload.left_column,
        right_column=payload.right_column,
        sql_text=payload.sql_text,
    )
    session.add(query)
    await session.commit()
    await session.refresh(query)
    return SavedQueryRead.model_validate(query)


@router.put("/{project_id}/queries/{query_id}", response_model=SavedQueryRead)
async def update_saved_query(
    project_id: int,
    query_id: int,
    payload: SavedQueryUpdate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> SavedQueryRead:
    query = await session.get(SavedQuery, query_id)
    if query is None or query.project_id != project_id:
        raise HTTPException(status_code=404, detail="Query not found")
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")

    if payload.name is not None:
        query.name = payload.name
    if payload.description is not None:
        query.description = payload.description
    if payload.left_datasource is not None:
        query.left_datasource = payload.left_datasource
    if payload.right_datasource is not None:
        query.right_datasource = payload.right_datasource
    if payload.join_type is not None:
        query.join_type = payload.join_type
    if payload.left_column is not None:
        query.left_column = payload.left_column
    if payload.right_column is not None:
        query.right_column = payload.right_column
    if payload.sql_text is not None:
        query.sql_text = payload.sql_text

    await session.commit()
    await session.refresh(query)
    return SavedQueryRead.model_validate(query)


@router.delete("/{project_id}/queries/{query_id}")
async def delete_saved_query(
    project_id: int,
    query_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> Response:
    query = await session.get(SavedQuery, query_id)
    if query is None or query.project_id != project_id:
        raise HTTPException(status_code=404, detail="Query not found")
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")
    await session.delete(query)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
