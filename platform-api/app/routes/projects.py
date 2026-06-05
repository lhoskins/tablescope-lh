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
from app.models.database_data_source import DatabaseDataSource
from app.models.file_source_meta import FileSourceMeta
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
from app.services.file_sources import display_source
from app.services.tenant_teiid_resolver import TenantTeiidResolver

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
    include_archived: bool = False,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[dict]:
    """List datasources for a project.

    For private projects: shows the owner's uploaded files.
    For shared projects: shows files in the shared folder.

    When ``include_archived`` is true, archived sources are also returned (each
    carrying an ``archived`` flag) so the UI can render a single unified
    "Archived" section for files, databases and SaaS sources alike.
    """
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")

    tenant = await session.get(Tenant, context.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Resolve the tenant's Teiid endpoint so dedicated-data-plane tenants read
    # their files from the dedicated VDB host path; unbound tenants fall back to
    # the shared customer_base_path (vdb_host_path == customer_base_path).
    endpoint = await TenantTeiidResolver(session).resolve_for_org(context.tenant_id)
    base = Path(endpoint.vdb_host_path)

    owner_id = project.owner_id or context.user_id
    uploads_dir = base / str(tenant.id) / str(owner_id) / "uploads"

    # File-source metadata governs project association + archive state.
    #   - no meta row        -> legacy file, shown in all the owner's projects
    #   - project_id == this -> scoped to this project (shown here)
    #   - project_id is None -> personal only (hidden from every project)
    #   - project_id == other-> scoped elsewhere (hidden here)
    meta_rows = (
        await session.scalars(
            select(FileSourceMeta).where(
                FileSourceMeta.tenant_id == context.tenant_id,
                FileSourceMeta.owner_id == owner_id,
            )
        )
    ).all()
    meta_by_view = {m.view_name: m for m in meta_rows}

    datasources: list[dict] = []
    if uploads_dir.is_dir():
        for f in sorted(uploads_dir.iterdir()):
            if f.is_file() and not f.name.startswith("."):
                base_name = f.stem.replace(" ", "_")
                extension = f.suffix.lstrip(".").upper()
                view_name = f"{base_name}_{extension}" if extension else base_name
                meta = meta_by_view.get(view_name)
                is_archived = bool(meta and meta.archived)
                if meta is not None and meta.project_id != project_id:
                    # Scoped to another project (or personal-only); never here.
                    continue
                if is_archived and not include_archived:
                    continue
                display_name, source_type = display_source(
                    f.name, meta.source_format if meta else None
                )
                datasources.append({
                    "fileName": display_name,
                    "viewName": view_name,
                    "size": f.stat().st_size,
                    "sourceType": source_type,
                    "dbType": None,
                    "fileMetaId": meta.id if meta else None,
                    "projectId": meta.project_id if meta else None,
                    "ownerId": owner_id,
                    "columnTypes": (meta.column_types or []) if meta else [],
                    "archived": is_archived,
                })

    # Append database-backed data sources registered against this project.
    db_stmt = select(DatabaseDataSource).where(
        DatabaseDataSource.tenant_id == context.tenant_id,
        DatabaseDataSource.project_id == project_id,
        DatabaseDataSource.status == "active",
    )
    if not include_archived:
        db_stmt = db_stmt.where(DatabaseDataSource.archived.is_(False))
    db_sources = (await session.scalars(db_stmt)).all()
    for ds in db_sources:
        is_saas = ds.source_type == "saas_object"
        datasources.append({
            "fileName": ds.display_name,
            "viewName": ds.teiid_view_name,
            "size": None,
            "sourceType": "saas_object" if is_saas else "database_table",
            "dbType": ds.db_type,
            "connectorType": ds.connector_type,
            "id": ds.id,
            "ownerId": ds.created_by,
            "archived": ds.archived,
        })

    return datasources


def _file_view_name(file_name: str) -> str:
    """Replicate the Teiid view-name convention for an uploaded file name."""
    stem = file_name.rsplit(".", 1)[0].replace(" ", "_")
    ext = file_name.rsplit(".", 1)[-1].upper() if "." in file_name else ""
    return f"{stem}_{ext}" if ext else stem


@router.get("/{project_id}/available-datasources")
async def list_available_datasources(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> list[dict]:
    """List the caller's datasources that are NOT yet in this project.

    Powers the "Add Datasource" modal: the user picks from their existing
    files / database tables / SaaS objects to associate them with the project
    (item 2).  Only the caller's own, non-archived sources are offered.
    """
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")

    tenant = await session.get(Tenant, context.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Read from the tenant's dedicated VDB host path when bound to a data plane;
    # falls back to the shared customer_base_path for unbound tenants.
    endpoint = await TenantTeiidResolver(session).resolve_for_org(context.tenant_id)
    uploads_dir = (
        Path(endpoint.vdb_host_path)
        / str(tenant.id)
        / str(context.user_id)
        / "uploads"
    )

    meta_rows = (
        await session.scalars(
            select(FileSourceMeta).where(
                FileSourceMeta.tenant_id == context.tenant_id,
                FileSourceMeta.owner_id == context.user_id,
            )
        )
    ).all()
    meta_by_view = {m.view_name: m for m in meta_rows}

    available: list[dict] = []
    if uploads_dir.is_dir():
        for f in sorted(uploads_dir.iterdir()):
            if not f.is_file() or f.name.startswith("."):
                continue
            view_name = _file_view_name(f.name)
            meta = meta_by_view.get(view_name)
            # Only files explicitly scoped elsewhere or personal-only can be
            # added here.  Files already in this project (or legacy files with
            # no meta, which already show in every project) are excluded.
            if meta is None or meta.archived or meta.project_id == project_id:
                continue
            display_name, source_type = display_source(f.name, meta.source_format)
            available.append({
                "kind": "file",
                "fileName": display_name,
                "viewName": view_name,
                "sourceType": source_type,
                "dbType": None,
                "connectorType": None,
            })

    db_sources = (
        await session.scalars(
            select(DatabaseDataSource).where(
                DatabaseDataSource.tenant_id == context.tenant_id,
                DatabaseDataSource.created_by == context.user_id,
                DatabaseDataSource.status == "active",
                DatabaseDataSource.archived.is_(False),
                or_(
                    DatabaseDataSource.project_id.is_(None),
                    DatabaseDataSource.project_id != project_id,
                ),
            )
        )
    ).all()
    for ds in db_sources:
        is_saas = ds.source_type == "saas_object"
        available.append({
            "kind": "db",
            "id": ds.id,
            "fileName": ds.display_name,
            "viewName": ds.teiid_view_name,
            "sourceType": "saas_object" if is_saas else "database_table",
            "dbType": ds.db_type,
            "connectorType": ds.connector_type,
        })

    return available


@router.post("/{project_id}/datasources/add")
async def add_datasources_to_project(
    project_id: int,
    body: dict,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    """Associate existing datasources with a project (item 2).

    Body: ``{"items": [{"kind": "file", "viewName": "..."},
                        {"kind": "db", "id": 123}]}``.
    """
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")

    items = body.get("items") or []
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="items must be a list")

    added = 0
    for item in items:
        kind = item.get("kind")
        if kind == "file":
            view_name = item.get("viewName")
            if not view_name:
                continue
            meta = await session.scalar(
                select(FileSourceMeta).where(
                    FileSourceMeta.tenant_id == context.tenant_id,
                    FileSourceMeta.owner_id == context.user_id,
                    FileSourceMeta.view_name == view_name,
                )
            )
            if meta is None:
                meta = FileSourceMeta(
                    tenant_id=context.tenant_id,
                    owner_id=context.user_id,
                    view_name=view_name,
                    file_name=view_name,
                )
                session.add(meta)
            meta.project_id = project_id
            added += 1
        elif kind == "db":
            ds_id = item.get("id")
            if ds_id is None:
                continue
            ds = await session.get(DatabaseDataSource, int(ds_id))
            if ds is None or ds.tenant_id != context.tenant_id:
                continue
            if ds.created_by != context.user_id and context.role != "admin":
                continue
            ds.project_id = project_id
            added += 1

    await session.commit()
    return {"status": "ok", "added": added}


async def _is_project_admin(
    session: AsyncSession, project: Project, context: RequestContext
) -> bool:
    """True if the caller is the project owner, a project-admin member, or a
    tenant admin — i.e. allowed to manage any datasource on the project."""
    if context.role == "admin":
        return True
    if project.owner_id == context.user_id:
        return True
    member = await session.get(ProjectMember, (project.id, context.user_id))
    return member is not None and member.role == "admin"


@router.post("/{project_id}/datasources/remove")
async def remove_datasource_from_project(
    project_id: int,
    body: dict,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    """Remove a datasource from a project (item 3).

    Works identically for file, database and SaaS sources: it only clears the
    project association (the source stays in the owner's personal datasources).
    Allowed only for a project admin/owner or the datasource's owner.

    Body: ``{"kind": "file"|"db", "viewName": "...", "id": 123}``.
    """
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")

    is_admin = await _is_project_admin(session, project, context)
    kind = body.get("kind")

    if kind == "file":
        view_name = body.get("viewName")
        if not view_name:
            raise HTTPException(status_code=400, detail="viewName is required")
        owner_id = project.owner_id or context.user_id
        meta = await session.scalar(
            select(FileSourceMeta).where(
                FileSourceMeta.tenant_id == context.tenant_id,
                FileSourceMeta.owner_id == owner_id,
                FileSourceMeta.view_name == view_name,
            )
        )
        # A file source's owner is the project owner whose folder it lives in.
        if not is_admin and owner_id != context.user_id:
            raise HTTPException(
                status_code=403,
                detail="Only a project admin or the datasource owner can remove it.",
            )
        if meta is None:
            meta = FileSourceMeta(
                tenant_id=context.tenant_id,
                owner_id=owner_id,
                view_name=view_name,
                file_name=view_name,
            )
            session.add(meta)
        meta.project_id = None
    else:
        ds_id = body.get("id")
        if ds_id is None:
            raise HTTPException(status_code=400, detail="id is required")
        ds = await session.get(DatabaseDataSource, int(ds_id))
        if ds is None or ds.tenant_id != context.tenant_id:
            raise HTTPException(status_code=404, detail="Datasource not found")
        if not is_admin and ds.created_by != context.user_id:
            raise HTTPException(
                status_code=403,
                detail="Only a project admin or the datasource owner can remove it.",
            )
        ds.project_id = None

    await session.commit()
    return {"status": "ok"}


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

    member.role = new_role
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
