"""Project CRUD routes with tenant scoping.

Every project belongs to a tenant. The owner is the user who created it.
Private projects (is_shared=False) are visible only to the owner and assigned
members. Shared projects are visible to all active members.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.database import get_db
from app.models.audit_event import AuditEvent
from app.models.dashboard import Dashboard
from app.models.data_source_ai_profile import (
    DataSourceAIProfile,
    DataSourceFieldProfile,
)
from app.models.database_data_source import DatabaseDataSource
from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project, ProjectMember
from app.models.project_asset import ProjectAsset
from app.models.query_scope import QueryScope
from app.models.saved_query import SavedQuery
from app.models.scope_set import ScopeSet
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.project import (
    AddableUserRead,
    ProjectCreate,
    ProjectMemberRead,
    ProjectRead,
    ProjectSummaryRead,
    ProjectUpdate,
    SavedQueryCreate,
    SavedQueryRead,
    SavedQueryUpdate,
)
from app.services.customer_folders import CustomerFolderService
from app.services.database_introspection_service import (
    map_to_teiid_type as _map_teiid_type,
)
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


def _derive_ai_status(
    *, doc_total: int, doc_indexing: int, doc_ready: int, has_activity: bool
) -> str:
    """Roll an AI status label up from a project's document indexing state."""
    if doc_indexing > 0:
        return "indexing"
    if doc_ready > 0:
        return "ready"
    if has_activity:
        return "active"
    return "idle"


@router.get("/summaries", response_model=list[ProjectSummaryRead])
async def list_project_summaries(
    recent: bool = Query(default=False),
    limit: int | None = Query(default=None, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[ProjectSummaryRead]:
    """List visible projects with rollup counts and an AI status badge.

    Used by the Home and Projects screens to render project cards without N+1
    round-trips. Counts are computed with grouped aggregates over the set of
    projects the caller can see.
    """
    member_sub = select(ProjectMember.project_id).where(
        ProjectMember.user_id == context.user_id,
        ProjectMember.is_active.is_(True),
    )
    project_query = (
        select(Project)
        .where(
            Project.tenant_id == context.tenant_id,
            or_(
                Project.owner_id == context.user_id,
                Project.id.in_(member_sub),
            ),
        )
        .order_by(
            Project.updated_at.desc() if recent else Project.created_at.desc()
        )
    )
    if limit is not None:
        project_query = project_query.limit(limit)
    projects = list(await session.scalars(project_query))
    if not projects:
        return []

    ids = [p.id for p in projects]

    async def _grouped_counts(model) -> dict[int, int]:
        result = await session.execute(
            select(model.project_id, func.count())
            .where(model.project_id.in_(ids))
            .group_by(model.project_id)
        )
        return {pid: count for pid, count in result.all()}

    query_result = await session.execute(
        select(SavedQuery.project_id, func.count())
        .where(
            SavedQuery.project_id.in_(ids),
            SavedQuery.is_archived.is_(False),
        )
        .group_by(SavedQuery.project_id)
    )
    query_counts = {pid: count for pid, count in query_result.all()}
    dashboard_counts = await _grouped_counts(Dashboard)
    asset_counts = await _grouped_counts(ProjectAsset)
    member_counts = await _grouped_counts(ProjectMember)

    indexing_states = ("processing", "indexing", "pending")
    ready_states = ("ready", "completed", "indexed", "complete")

    async def _asset_status_counts(states: tuple[str, ...]) -> dict[int, int]:
        result = await session.execute(
            select(ProjectAsset.project_id, func.count())
            .where(
                ProjectAsset.project_id.in_(ids),
                ProjectAsset.ai_status.in_(states),
            )
            .group_by(ProjectAsset.project_id)
        )
        return {pid: count for pid, count in result.all()}

    indexing_counts = await _asset_status_counts(indexing_states)
    ready_counts = await _asset_status_counts(ready_states)

    summaries: list[ProjectSummaryRead] = []
    for p in projects:
        q_count = query_counts.get(p.id, 0)
        d_count = dashboard_counts.get(p.id, 0)
        doc_count = asset_counts.get(p.id, 0)
        ai_status = _derive_ai_status(
            doc_total=doc_count,
            doc_indexing=indexing_counts.get(p.id, 0),
            doc_ready=ready_counts.get(p.id, 0),
            has_activity=(q_count > 0 or d_count > 0),
        )
        summaries.append(
            ProjectSummaryRead(
                id=p.id,
                name=p.name,
                is_shared=p.is_shared,
                updated_at=p.updated_at,
                document_count=doc_count,
                query_count=q_count,
                dashboard_count=d_count,
                member_count=member_counts.get(p.id, 0),
                data_source_count=0,
                ai_status=ai_status,
            )
        )
    return summaries


def _visible_projects_subquery(context: RequestContext):
    """Select ids of projects the caller can see in the current tenant."""
    member_sub = select(ProjectMember.project_id).where(
        ProjectMember.user_id == context.user_id,
        ProjectMember.is_active.is_(True),
    )
    return select(Project.id, Project.name).where(
        Project.tenant_id == context.tenant_id,
        or_(
            Project.owner_id == context.user_id,
            Project.id.in_(member_sub),
        ),
    )


def _user_label(user: User) -> str:
    """A human-friendly name for a user (display name > full name > email)."""
    if user.display_name:
        return user.display_name
    full = " ".join(p for p in [user.first_name, user.last_name] if p)
    return full or user.email


class _ProjectMeta:
    __slots__ = ("name", "owner_id", "is_shared")

    def __init__(self, name: str, owner_id: int | None, is_shared: bool) -> None:
        self.name = name
        self.owner_id = owner_id
        self.is_shared = is_shared


async def _home_context(
    session: AsyncSession, context: RequestContext
) -> tuple[dict[int, _ProjectMeta], dict[int, str]]:
    """Visible-project metadata + a user-id→name map for "Shared by" labels."""
    member_sub = select(ProjectMember.project_id).where(
        ProjectMember.user_id == context.user_id,
        ProjectMember.is_active.is_(True),
    )
    rows = (
        await session.execute(
            select(
                Project.id,
                Project.name,
                Project.owner_id,
                Project.is_shared,
            ).where(
                Project.tenant_id == context.tenant_id,
                or_(
                    Project.owner_id == context.user_id,
                    Project.id.in_(member_sub),
                ),
            )
        )
    ).all()
    projects = {
        pid: _ProjectMeta(name, owner_id, is_shared)
        for pid, name, owner_id, is_shared in rows
    }
    users = list(
        await session.scalars(
            select(User).where(User.tenant_id == context.tenant_id)
        )
    )
    names = {u.id: _user_label(u) for u in users}
    return projects, names


def _shared_by(
    project: _ProjectMeta | None,
    item_owner_id: int | None,
    user_names: dict[int, str],
    *,
    item_shared: bool | None = None,
) -> str:
    """Resolve the "Shared by" label.

    - "Private" when the item (or its project) is not shared.
    - "Shared" when shared by the project owner.
    - the owner's name when shared by someone other than the project owner.
    """
    if project is None:
        return "Private"
    is_shared = project.is_shared if item_shared is None else item_shared
    if not is_shared:
        return "Private"
    if item_owner_id is None or item_owner_id == project.owner_id:
        return "Shared"
    return user_names.get(item_owner_id, "Shared")


def _owner(
    project: _ProjectMeta | None,
    item_owner_id: int | None,
    user_names: dict[int, str],
) -> tuple[int | None, str]:
    """Resolve the actual owner/creator (id, name) of an item.

    Falls back to the project owner when the item has no explicit owner.
    """
    owner_id = item_owner_id
    if owner_id is None and project is not None:
        owner_id = project.owner_id
    name = user_names.get(owner_id, "—") if owner_id is not None else "—"
    return owner_id, name


def _query_origin(query: SavedQuery) -> tuple[str, str]:
    """Normalize a saved query's origin into (key, human label)."""
    if query.ai_generated:
        return "ai_generated", "AI Generated"
    return "manual", "Manual"


@router.get("/dashboards-all")
async def list_all_dashboards(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[dict]:
    """All dashboards across the caller's visible projects (Home view)."""
    projects, user_names = await _home_context(session, context)
    if not projects:
        return []
    rows = list(
        await session.scalars(
            select(Dashboard)
            .where(Dashboard.project_id.in_(list(projects.keys())))
            .order_by(Dashboard.created_at.desc())
        )
    )
    return [
        {
            "id": d.id,
            "name": d.name,
            "projectId": d.project_id,
            "projectName": (
                projects[d.project_id].name if d.project_id in projects else "—"
            ),
            "status": d.status,
            "sharedBy": _shared_by(
                projects.get(d.project_id), d.owner_id, user_names
            ),
            "ownerId": _owner(
                projects.get(d.project_id), d.owner_id, user_names
            )[0],
            "ownerName": _owner(
                projects.get(d.project_id), d.owner_id, user_names
            )[1],
            "createdAt": d.created_at.isoformat() if d.created_at else None,
        }
        for d in rows
    ]


@router.get("/datasources-all")
async def list_all_datasources(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[dict]:
    """All data sources (file + database) across visible projects (Home view)."""
    projects, user_names = await _home_context(session, context)
    if not projects:
        return []
    pids = list(projects.keys())

    file_rows = list(
        await session.scalars(
            select(FileSourceMeta)
            .where(
                FileSourceMeta.project_id.in_(pids),
                FileSourceMeta.archived.is_(False),
            )
            .order_by(FileSourceMeta.created_at.desc())
        )
    )
    db_rows = list(
        await session.scalars(
            select(DatabaseDataSource)
            .where(
                DatabaseDataSource.project_id.in_(pids),
                DatabaseDataSource.archived.is_(False),
            )
            .order_by(DatabaseDataSource.created_at.desc())
        )
    )

    out: list[dict] = []
    for f in file_rows:
        out.append(
            {
                "id": f.id,
                "name": f.file_name,
                "viewName": f.view_name,
                "kind": "file",
                "projectId": f.project_id,
                "projectName": (
                    projects[f.project_id].name
                    if f.project_id in projects
                    else "—"
                ),
                "sharedBy": _shared_by(
                    projects.get(f.project_id) if f.project_id is not None else None,
                    f.owner_id,
                    user_names,
                ),
                "createdAt": f.created_at.isoformat() if f.created_at else None,
            }
        )
    for d in db_rows:
        out.append(
            {
                "id": d.id,
                "name": d.display_name,
                "viewName": d.teiid_view_name,
                "kind": "database",
                "projectId": d.project_id,
                "projectName": (
                    projects[d.project_id].name
                    if d.project_id in projects
                    else "—"
                ),
                "sharedBy": _shared_by(
                    projects.get(d.project_id) if d.project_id is not None else None,
                    d.created_by,
                    user_names,
                ),
                "createdAt": d.created_at.isoformat() if d.created_at else None,
            }
        )
    out.sort(key=lambda r: r["createdAt"] or "", reverse=True)
    return out


@router.get("/my-datasources")
async def list_my_datasources(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[dict]:
    """All data sources the caller has created, irrespective of project.

    Powers the Data Source Builder's "Active Data Sources" list so previously
    created sources (files + database tables) show up after a refresh and can
    be reviewed / reassigned. Scoped to the caller's own sources.
    """
    projects, _ = await _home_context(session, context)

    file_rows = list(
        await session.scalars(
            select(FileSourceMeta)
            .where(
                FileSourceMeta.tenant_id == context.tenant_id,
                FileSourceMeta.owner_id == context.user_id,
                FileSourceMeta.archived.is_(False),
            )
            .order_by(FileSourceMeta.created_at.desc())
        )
    )
    db_rows = list(
        await session.scalars(
            select(DatabaseDataSource)
            .where(
                DatabaseDataSource.tenant_id == context.tenant_id,
                DatabaseDataSource.created_by == context.user_id,
                DatabaseDataSource.status == "active",
                DatabaseDataSource.archived.is_(False),
            )
            .options(selectinload(DatabaseDataSource.columns))
            .order_by(DatabaseDataSource.created_at.desc())
        )
    )

    def _project_name(pid: int | None) -> str | None:
        if pid is None:
            return None
        meta = projects.get(pid)
        return meta.name if meta else None

    out: list[dict] = []
    for f in file_rows:
        out.append(
            {
                "id": f.id,
                "kind": "file",
                "name": f.file_name,
                "viewName": f.view_name,
                "projectId": f.project_id,
                "projectName": _project_name(f.project_id),
                "columns": len(f.column_types or []),
                "sourceFormat": f.source_format,
                "createdAt": f.created_at.isoformat() if f.created_at else None,
            }
        )
    for d in db_rows:
        out.append(
            {
                "id": d.id,
                "kind": "database",
                "name": d.display_name,
                "viewName": d.teiid_view_name,
                "projectId": d.project_id,
                "projectName": _project_name(d.project_id),
                "columns": len(d.columns or []),
                "dbType": d.db_type,
                "schemaName": d.schema_name,
                "tableName": d.table_name,
                "createdAt": d.created_at.isoformat() if d.created_at else None,
            }
        )
    out.sort(key=lambda r: r["createdAt"] or "", reverse=True)
    return out


@router.get("/documents-all")
async def list_all_documents(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[dict]:
    """All documents across the caller's visible projects (Home view)."""
    projects, user_names = await _home_context(session, context)
    names = {pid: meta.name for pid, meta in projects.items()}
    if not names:
        return []
    rows = list(
        await session.scalars(
            select(ProjectAsset)
            .where(ProjectAsset.project_id.in_(list(names.keys())))
            .order_by(ProjectAsset.created_at.desc())
        )
    )
    return [
        {
            "id": a.id,
            "name": a.title or a.original_filename or a.filename,
            "projectId": a.project_id,
            "projectName": names.get(a.project_id, "—"),
            "aiStatus": a.ai_status,
            "sharedBy": _shared_by(
                projects.get(a.project_id), a.owner_user_id, user_names
            ),
            "ownerId": _owner(
                projects.get(a.project_id), a.owner_user_id, user_names
            )[0],
            "ownerName": _owner(
                projects.get(a.project_id), a.owner_user_id, user_names
            )[1],
            "createdAt": a.created_at.isoformat() if a.created_at else None,
        }
        for a in rows
    ]


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
                    "aiMetadata": (meta.ai_metadata or {}) if meta else {},
                    "archived": is_archived,
                })

    # Append database-backed data sources registered against this project.
    db_stmt = (
        select(DatabaseDataSource)
        .where(
            DatabaseDataSource.tenant_id == context.tenant_id,
            DatabaseDataSource.project_id == project_id,
            DatabaseDataSource.status == "active",
        )
        .options(selectinload(DatabaseDataSource.columns))
    )
    if not include_archived:
        db_stmt = db_stmt.where(DatabaseDataSource.archived.is_(False))
    db_sources = (await session.scalars(db_stmt)).all()
    for ds in db_sources:
        is_saas = ds.source_type == "saas_object"
        cols = sorted(
            ds.columns, key=lambda c: (c.ordinal_position or 0, c.column_name)
        )
        datasources.append({
            "fileName": ds.display_name,
            "viewName": ds.teiid_view_name,
            "size": None,
            "sourceType": "saas_object" if is_saas else "database_table",
            "dbType": ds.db_type,
            "connectorType": ds.connector_type,
            "id": ds.id,
            "ownerId": ds.created_by,
            "columnTypes": [
                {
                    "name": c.column_name,
                    "type": c.teiid_type_override
                    or _map_teiid_type(c.data_type or ""),
                }
                for c in cols
            ],
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
            await session.flush()
            await _auto_create_query(
                session,
                project_id=project_id,
                owner_id=context.user_id,
                display_name=meta.file_name or view_name,
                view_name=view_name,
                columns=[
                    c["name"]
                    for c in (meta.column_types or [])
                    if isinstance(c, dict) and c.get("name")
                ],
            )
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
            await session.flush()
            await _auto_create_query(
                session,
                project_id=project_id,
                owner_id=context.user_id,
                display_name=ds.display_name or ds.teiid_view_name,
                view_name=ds.teiid_view_name,
                columns=None,
            )
            added += 1

    await session.commit()
    return {"status": "ok", "added": added}


async def _auto_create_query(
    session: AsyncSession,
    *,
    project_id: int,
    owner_id: int | None,
    display_name: str,
    view_name: str,
    columns: list[str] | None,
) -> None:
    """Best-effort auto-create of a saved query for a data source."""
    try:
        from app.services.auto_query import ensure_datasource_query

        await ensure_datasource_query(
            session,
            project_id=project_id,
            owner_id=owner_id,
            display_name=display_name,
            view_name=view_name,
            columns=columns,
        )
    except Exception as exc:  # non-fatal
        logger.warning(
            "Auto-create query for %s failed (non-fatal): %s", view_name, exc
        )


# Standard Teiid runtime types offered in the column-type editor (item 5).
STANDARD_TEIID_TYPES: tuple[str, ...] = (
    "string",
    "integer",
    "long",
    "short",
    "double",
    "float",
    "bigdecimal",
    "boolean",
    "date",
    "time",
    "timestamp",
    "varbinary",
)


@router.get("/{project_id}/datasources/column-types")
async def list_standard_column_types(
    project_id: int,
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> list[str]:
    """Standard Teiid runtime types selectable in the column-type editor."""
    return list(STANDARD_TEIID_TYPES)


@router.put("/{project_id}/datasources/columns")
async def update_datasource_columns(
    project_id: int,
    body: dict,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    """Update a datasource's column types and redeploy its VDB (item 5).

    Body for a database table::

        {"kind": "db", "id": 123,
         "columns": [{"name": "Amount", "type": "double"}]}

    Body for an uploaded file::

        {"kind": "file", "viewName": "Sales_CSV",
         "columns": [{"name": "Amount", "type": "double"}]}
    """
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")

    columns = body.get("columns") or []
    if not isinstance(columns, list) or not columns:
        raise HTTPException(status_code=400, detail="columns must be a non-empty list")

    type_by_name: dict[str, str] = {}
    for col in columns:
        name = (col or {}).get("name")
        ctype = (col or {}).get("type")
        if not name or not ctype:
            continue
        if ctype not in STANDARD_TEIID_TYPES:
            raise HTTPException(
                status_code=400, detail=f"Unsupported column type: {ctype}"
            )
        type_by_name[str(name)] = str(ctype)

    if not type_by_name:
        raise HTTPException(status_code=400, detail="No valid columns provided")

    kind = body.get("kind")

    if kind == "db":
        from app.models.database_data_source import DataSourceColumn
        from app.services.teiid_registration_service import (
            reconcile_database_sources,
        )

        ds_id = body.get("id")
        if ds_id is None:
            raise HTTPException(status_code=400, detail="id is required for db sources")
        ds = await session.get(DatabaseDataSource, int(ds_id))
        if ds is None or ds.tenant_id != context.tenant_id:
            raise HTTPException(status_code=404, detail="Datasource not found")
        if (
            ds.created_by != context.user_id
            and not await _is_project_admin(session, project, context)
        ):
            raise HTTPException(status_code=403, detail="Not allowed")

        cols = (
            await session.scalars(
                select(DataSourceColumn).where(
                    DataSourceColumn.data_source_id == ds.id
                )
            )
        ).all()
        for c in cols:
            if c.column_name in type_by_name:
                c.teiid_type_override = type_by_name[c.column_name]
        await session.commit()

        result = await reconcile_database_sources(session, only_id=ds.id)
        if result.get("failed"):
            raise HTTPException(
                status_code=502,
                detail="Column types saved but VDB redeploy failed. Try again.",
            )
        return {"status": "ok", "redeployed": True, "kind": "db"}

    if kind == "file":
        from app.models.user_vdb import UserVDB
        from app.services.vdb_management import VDBManagementService

        view_name = body.get("viewName")
        if not view_name:
            raise HTTPException(
                status_code=400, detail="viewName is required for file sources"
            )
        meta = await session.scalar(
            select(FileSourceMeta).where(
                FileSourceMeta.tenant_id == context.tenant_id,
                FileSourceMeta.owner_id == context.user_id,
                FileSourceMeta.view_name == view_name,
            )
        )
        if meta is None:
            raise HTTPException(status_code=404, detail="Datasource not found")

        existing = {
            (c or {}).get("name"): dict(c)
            for c in (meta.column_types or [])
            if isinstance(c, dict)
        }
        for name, ctype in type_by_name.items():
            entry = existing.get(name, {"name": name})
            entry["type"] = ctype
            existing[name] = entry
        meta.column_types = list(existing.values())
        await session.commit()

        user_vdb = await session.scalar(
            select(UserVDB).where(
                UserVDB.tenant_id == context.tenant_id,
                UserVDB.user_id == meta.owner_id,
            )
        )
        if user_vdb is not None:
            svc = VDBManagementService()
            try:
                await svc.redeploy_vdb(user_vdb.vdb_id)
            except Exception as exc:  # pragma: no cover - servlet failure
                logger.warning("File VDB redeploy failed for %s: %s", view_name, exc)
            finally:
                aclose = getattr(svc, "aclose", None)
                if aclose is not None:
                    await aclose()
        return {"status": "ok", "redeployed": user_vdb is not None, "kind": "file"}

    raise HTTPException(status_code=400, detail="kind must be 'db' or 'file'")


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
    include_archived: bool = Query(default=False),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[SavedQueryRead]:
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")
    stmt = select(SavedQuery).where(SavedQuery.project_id == project_id)
    if not include_archived:
        stmt = stmt.where(SavedQuery.is_archived.is_(False))
    rows = list(
        await session.scalars(stmt.order_by(SavedQuery.created_at.desc()))
    )

    # Owner names for the "Owner" column.
    users = list(
        await session.scalars(
            select(User).where(User.tenant_id == context.tenant_id)
        )
    )
    user_names = {u.id: _user_label(u) for u in users}

    # Active-scope participation: an enabled scope whose parent set is enabled
    # (or has no parent set) AND that has a target table. Only the *source* of
    # such a scope gets the scope icon (outgoing); a table that is only a
    # target has an incoming scope but no icon.
    scope_rows = (
        await session.execute(
            select(QueryScope.query_id, QueryScope.target_query_id)
            .outerjoin(ScopeSet, QueryScope.scope_set_id == ScopeSet.id)
            .where(
                QueryScope.project_id == project_id,
                QueryScope.enabled.is_(True),
                QueryScope.target_query_id.is_not(None),
                or_(
                    QueryScope.scope_set_id.is_(None),
                    ScopeSet.enabled.is_(True),
                ),
            )
        )
    ).all()
    outgoing_counts: dict[int, int] = {}
    incoming_counts: dict[int, int] = {}
    for source_id, target_id in scope_rows:
        if source_id is not None:
            outgoing_counts[source_id] = outgoing_counts.get(source_id, 0) + 1
        if target_id is not None:
            incoming_counts[target_id] = incoming_counts.get(target_id, 0) + 1

    results: list[SavedQueryRead] = []
    for q in rows:
        read = SavedQueryRead.model_validate(q)
        read.owner_name = (
            user_names.get(q.owner_id) if q.owner_id is not None else None
        )
        read.origin, read.origin_label = _query_origin(q)
        read.source_name = q.left_datasource or (
            "AI Generated" if q.ai_generated else None
        )
        outgoing = outgoing_counts.get(q.id, 0)
        incoming = incoming_counts.get(q.id, 0)
        read.outgoing_scope_count = outgoing
        read.has_outgoing_scope = outgoing > 0
        read.incoming_scope_count = incoming
        read.has_incoming_scope = incoming > 0
        # Backward-compat aggregate.
        read.active_scope_count = outgoing + incoming
        read.has_active_scope = read.active_scope_count > 0
        results.append(read)
    return results


async def _maybe_autoscope_on_save(
    session: AsyncSession,
    *,
    query: SavedQuery,
    context: RequestContext,
) -> None:
    """Refresh AI drill-down scopes after a query is saved.

    Only runs when the project already has an *enabled* "AI Generated Scopes"
    set — i.e. the user has opted into autoscoping via the Scopes page toggle.
    This keeps that set fresh as new queries are added without forcing AI
    scopes onto projects that never enabled them. Fail-soft: a scoping error
    must never break saving the query.
    """
    try:
        ai_set = await session.scalar(
            select(ScopeSet).where(
                ScopeSet.tenant_id == context.tenant_id,
                ScopeSet.project_id == query.project_id,
                ScopeSet.type == "ai_generated",
                ScopeSet.enabled.is_(True),
            )
        )
        if ai_set is None:
            return
        from app.services.auto_scope import auto_create_scopes_for_query

        created = await auto_create_scopes_for_query(
            session,
            query=query,
            tenant_id=context.tenant_id,
            user_id=context.user_id or ai_set.created_by or 0,
        )
        if created:
            await session.commit()
    except Exception as exc:  # never break the save on a scoping error
        logger.warning(
            "Auto-scope on save failed for query %s: %s", query.id, exc
        )


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
        ai_generated=payload.ai_generated,
        is_shared=payload.is_shared,
    )
    session.add(query)
    await session.commit()
    await session.refresh(query)
    await _maybe_autoscope_on_save(session, query=query, context=context)
    read = SavedQueryRead.model_validate(query)
    read.origin, read.origin_label = _query_origin(query)
    return read


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
    if payload.ai_generated is not None:
        query.ai_generated = payload.ai_generated
    if payload.is_shared is not None:
        query.is_shared = payload.is_shared

    await session.commit()
    await session.refresh(query)
    await _maybe_autoscope_on_save(session, query=query, context=context)
    read = SavedQueryRead.model_validate(query)
    read.origin, read.origin_label = _query_origin(query)
    return read


@router.post(
    "/{project_id}/queries/{query_id}/archive",
    response_model=SavedQueryRead,
)
async def archive_saved_query(
    project_id: int,
    query_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> SavedQueryRead:
    """Archive a query. It stays executable but is hidden from normal lists."""
    query = await session.get(SavedQuery, query_id)
    if query is None or query.project_id != project_id:
        raise HTTPException(status_code=404, detail="Query not found")
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")
    query.is_archived = True
    query.archived_at = datetime.now(UTC)
    query.archived_by = context.user_id
    await session.commit()
    await session.refresh(query)
    read = SavedQueryRead.model_validate(query)
    read.origin, read.origin_label = _query_origin(query)
    return read


@router.post(
    "/{project_id}/queries/{query_id}/restore",
    response_model=SavedQueryRead,
)
async def restore_saved_query(
    project_id: int,
    query_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> SavedQueryRead:
    """Restore an archived query back to the active list."""
    query = await session.get(SavedQuery, query_id)
    if query is None or query.project_id != project_id:
        raise HTTPException(status_code=404, detail="Query not found")
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")
    query.is_archived = False
    query.archived_at = None
    query.archived_by = None
    await session.commit()
    await session.refresh(query)
    read = SavedQueryRead.model_validate(query)
    read.origin, read.origin_label = _query_origin(query)
    return read


async def _query_dependencies(
    session: AsyncSession, query: SavedQuery
) -> dict[str, Any]:
    """Blocking dependencies for a saved query.

    Delete is refused while any exist. Returns per-kind counts plus an
    ``items`` list of ``{"type", "name"}`` descriptors so the caller can render
    a specific dependency warning (e.g. "Dashboard: Executive KPI Dashboard").
    """
    items: list[dict[str, str]] = []

    # Scopes: this query feeds another (source) or is fed by another (target).
    # Name each by the counterpart table on the scope so the warning is concrete.
    source_scopes = list(
        await session.scalars(
            select(QueryScope).where(QueryScope.query_id == query.id)
        )
    )
    target_scopes = list(
        await session.scalars(
            select(QueryScope).where(QueryScope.target_query_id == query.id)
        )
    )
    for sc in source_scopes:
        items.append({
            "type": "Scope",
            "name": f"→ {sc.target_table or 'linked table'}",
        })
    for sc in target_scopes:
        items.append({
            "type": "Scope",
            "name": f"{sc.source_table or 'linked table'} →",
        })

    # Dashboards whose widget config references this query id.
    dashboards = list(
        await session.scalars(
            select(Dashboard).where(Dashboard.project_id == query.project_id)
        )
    )
    dashboard_refs = 0
    for dash in dashboards:
        config = dash.config if isinstance(dash.config, dict) else {}
        widgets = config.get("widgets")
        if not isinstance(widgets, list):
            continue
        for widget in widgets:
            if not isinstance(widget, dict):
                continue
            source = widget.get("dataSource")
            if (
                isinstance(source, dict)
                and source.get("kind") == "query"
                and source.get("queryId") == query.id
            ):
                dashboard_refs += 1
                items.append({"type": "Dashboard", "name": dash.name})
                break

    return {
        "dashboards": dashboard_refs,
        "scopes_source": len(source_scopes),
        "scopes_target": len(target_scopes),
        "items": items,
    }


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

    # A query can only be permanently deleted once archived.
    if not query.is_archived:
        raise HTTPException(
            status_code=409,
            detail="Query must be archived before it can be deleted.",
        )

    # And only when it has no remaining dependencies.
    deps = await _query_dependencies(session, query)
    items: list[dict[str, str]] = deps["items"]
    if items:
        named = "; ".join(f"{d['type']}: {d['name']}" for d in items)
        raise HTTPException(
            status_code=409,
            detail=(
                "Cannot delete this query — remove these dependencies first: "
                + named
            ),
        )

    await session.delete(query)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _ai_metadata_count(meta: dict, keys: list[str]) -> int:
    for key in keys:
        value = meta.get(key) if isinstance(meta, dict) else None
        if isinstance(value, int):
            return value
        if isinstance(value, list):
            return len(value)
    return 0


@router.get("/{project_id}/metadata-catalog")
async def get_metadata_catalog(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict:
    """AI-profiled schema catalog for a project: tables (with field profiles)
    and documents. Powers the Metadata Catalog (Intelligence) screen."""
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")

    profiles = (
        await session.scalars(
            select(DataSourceAIProfile)
            .where(
                DataSourceAIProfile.tenant_id == context.tenant_id,
                DataSourceAIProfile.project_id == project_id,
            )
            .order_by(DataSourceAIProfile.file_name)
        )
    ).all()

    tables: list[dict] = []
    for p in profiles:
        fields = (
            await session.scalars(
                select(DataSourceFieldProfile)
                .where(DataSourceFieldProfile.data_source_id == p.data_source_id)
                .order_by(DataSourceFieldProfile.id)
            )
        ).all()
        tables.append({
            "data_source_id": p.data_source_id,
            "name": p.file_name or f"source-{p.data_source_id}",
            "source": p.file_type,
            "row_count": p.row_count,
            "field_count": p.column_count or len(fields),
            "ai_summary": p.ai_summary,
            "ai_quality_summary": p.ai_quality_summary,
            "status": p.status,
            "last_synced": p.updated_at.isoformat() if p.updated_at else None,
            "fields": [
                {
                    "name": f.field_name,
                    "type": f.recommended_type or f.detected_type,
                    "ai_description": f.ai_description,
                    "null_percent": (
                        float(f.null_percent) if f.null_percent is not None else None
                    ),
                    "distinct_count": f.distinct_count,
                    "sample_values": f.sample_values or [],
                    "include_in_ai": f.include_in_ai,
                }
                for f in fields
            ],
        })

    assets = (
        await session.scalars(
            select(ProjectAsset)
            .where(ProjectAsset.project_id == project_id)
            .order_by(ProjectAsset.created_at.desc())
        )
    ).all()
    documents = [
        {
            "id": a.id,
            "title": a.title,
            "type": (a.file_extension or "").replace(".", "").upper() or "FILE",
            "status": a.ai_status,
            "clauses": _ai_metadata_count(
                a.ai_metadata, ["extraction_count", "clauses", "kpis"]
            ),
            "relationships": _ai_metadata_count(
                a.ai_metadata, ["relationship_count", "relationships", "links"]
            ),
        }
        for a in assets
    ]

    return {"tables": tables, "documents": documents}


@router.get("/{project_id}/activity")
async def get_project_activity(
    project_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict:
    """Real activity/audit feed for a project, derived from saved queries,
    dashboards and document assets. Powers the Audit Log (Intelligence) screen."""
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")

    queries = (
        await session.scalars(
            select(SavedQuery).where(SavedQuery.project_id == project_id)
        )
    ).all()
    dashboards = (
        await session.scalars(
            select(Dashboard).where(Dashboard.project_id == project_id)
        )
    ).all()
    assets = (
        await session.scalars(
            select(ProjectAsset).where(ProjectAsset.project_id == project_id)
        )
    ).all()

    # Resolve actor display names in one batch.
    user_ids = {
        uid
        for uid in (
            [q.owner_id for q in queries]
            + [d.owner_id for d in dashboards]
            + [a.created_by for a in assets]
        )
        if uid is not None
    }
    actors: dict[int, str] = {}
    if user_ids:
        users = await session.scalars(select(User).where(User.id.in_(user_ids)))
        for u in users:
            actors[u.id] = u.display_name or u.email or f"User #{u.id}"

    def actor_name(uid: int | None) -> str:
        return actors.get(uid, "System") if uid is not None else "System"

    events: list[dict] = []

    for q in queries:
        ai = bool(q.ai_generated)
        events.append({
            "id": f"query-{q.id}-saved",
            "ts": q.created_at.isoformat() if q.created_at else None,
            "category": "ai" if ai else "query",
            "label": "AI Action" if ai else "Query",
            "title": f"Query saved: {q.name}",
            "detail": q.left_datasource,
            "actor": actor_name(q.owner_id),
        })
        if q.last_run_at and q.run_count:
            events.append({
                "id": f"query-{q.id}-run",
                "ts": q.last_run_at.isoformat(),
                "category": "query",
                "label": "Query",
                "title": f"Query executed: {q.name}",
                "detail": (
                    f"{q.run_count} runs"
                    + (f" · {q.avg_runtime_ms}ms avg" if q.avg_runtime_ms else "")
                ),
                "actor": actor_name(q.owner_id),
            })

    for d in dashboards:
        ai = bool(d.ai_generated)
        events.append({
            "id": f"dashboard-{d.id}-created",
            "ts": d.created_at.isoformat() if d.created_at else None,
            "category": "ai" if ai else "dashboard",
            "label": "AI Action" if ai else "Dashboard",
            "title": f"Dashboard created: {d.name}",
            "detail": f"{d.view_count} views" if d.view_count else None,
            "actor": actor_name(d.owner_id),
        })

    for a in assets:
        events.append({
            "id": f"asset-{a.id}-uploaded",
            "ts": a.created_at.isoformat() if a.created_at else None,
            "category": "upload",
            "label": "Upload",
            "title": f"Document uploaded: {a.title}",
            "detail": a.ai_status,
            "actor": actor_name(a.created_by),
        })
        if a.ai_status.lower() in {"ready", "indexed", "completed", "complete"}:
            events.append({
                "id": f"asset-{a.id}-indexed",
                "ts": a.updated_at.isoformat() if a.updated_at else None,
                "category": "ai",
                "label": "AI Action",
                "title": f"Document indexed: {a.title}",
                "detail": "AI indexing complete",
                "actor": "System",
            })

    audit_events = (
        await session.scalars(
            select(AuditEvent)
            .where(AuditEvent.project_id == project_id)
            .order_by(AuditEvent.created_at.desc())
            .limit(limit)
        )
    ).all()
    for ev in audit_events:
        src_bits: list[str] = []
        if ev.tables_queried:
            src_bits.append(", ".join(str(t) for t in ev.tables_queried))
        if ev.documents_read:
            src_bits.append(", ".join(str(d) for d in ev.documents_read))
        detail = " · ".join(src_bits) if src_bits else None
        if ev.duration_ms is not None:
            detail = f"{detail} · {ev.duration_ms}ms" if detail else f"{ev.duration_ms}ms"
        events.append({
            "id": f"audit-{ev.id}",
            "ts": ev.created_at.isoformat() if ev.created_at else None,
            "category": "ai",
            "label": "AI Action",
            "title": ev.title or f"AI intelligence: {ev.prompt_type or ev.event_type}",
            "detail": detail,
            "actor": actor_name(ev.user_id),
        })

    events = [e for e in events if e["ts"] is not None]
    events.sort(key=lambda e: e["ts"], reverse=True)
    events = events[:limit]

    actor_set = {e["actor"] for e in events if e["actor"] != "System"}
    return {
        "events": events,
        "stats": {
            "total_events": len(events),
            "ai_actions": sum(1 for e in events if e["category"] == "ai"),
            "active_users": len(actor_set),
            "isolation_violations": 0,
        },
    }
