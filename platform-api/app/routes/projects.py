"""Project CRUD routes with tenant scoping.

Every project belongs to a tenant. The owner is the user who created it.
Private projects (is_shared=False) are visible only to the owner and assigned
members. Shared projects are visible to all active members.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.config import get_settings
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


# ── Project Datasources ─────────────────────────────────────────────


@router.get("/{project_id}/datasources")
async def list_project_datasources(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[dict]:
    """List datasources for a project.

    For private projects: shows the owner's uploaded files.
    For shared projects: shows files in the shared folder.
    """
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")

    tenant = await session.get(Tenant, context.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    settings = get_settings()
    base = Path(settings.customer_base_path)

    owner_id = project.owner_id or context.user_id
    uploads_dir = base / str(tenant.id) / str(owner_id) / "uploads"

    datasources: list[dict] = []
    if uploads_dir.is_dir():
        for f in sorted(uploads_dir.iterdir()):
            if f.is_file() and not f.name.startswith("."):
                base_name = f.stem.replace(" ", "_")
                extension = f.suffix.lstrip(".").upper()
                view_name = f"{base_name}_{extension}" if extension else base_name
                datasources.append({
                    "fileName": f.name,
                    "viewName": view_name,
                    "size": f.stat().st_size,
                })

    return datasources


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
            is_active=m.is_active,
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
        if not existing.is_active:
            existing.is_active = True
            existing.role = role
            await session.commit()
            return ProjectMemberRead(
                project_id=project_id, user_id=user_id, role=role,
                is_active=True,
                email=user.email, display_name=user.display_name,
            )
        raise HTTPException(status_code=409, detail="User is already a member")

    member = ProjectMember(
        project_id=project_id, user_id=user_id, role=role, is_active=True,
    )
    session.add(member)
    await session.commit()
    return ProjectMemberRead(
        project_id=project_id, user_id=user_id, role=role,
        is_active=True,
        email=user.email, display_name=user.display_name,
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
