"""Catalog of all tenant data sources accessible to the caller.

Powers the Data Source Builder's "All Data Sources" view: a tenant-scoped,
paginated, searchable list of file, database-table, and SaaS-object sources that
the user is allowed to discover and assign.
"""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.database_data_source import DatabaseDataSource
from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project, ProjectMember
from app.models.user import User

router = APIRouter(prefix="/projects", tags=["projects"])


class _BulkValidationRequest(BaseModel):
    project_id: int
    source_ids: list[str]


class _BulkValidationResult(BaseModel):
    valid: list[str]
    invalid: dict[str, str]


def _is_tenant_admin(context: RequestContext) -> bool:
    return context.role in {
        Role.ADMIN,
        Role.DB_ADMIN,
        Role.TENANT_ADMIN,
        Role.ROOT_ADMIN,
    }


async def _visible_project_ids(
    session: AsyncSession,
    context: RequestContext,
) -> set[int]:
    """Return the set of project ids the caller can see in the current tenant."""
    member_sub = select(ProjectMember.project_id).where(
        ProjectMember.user_id == context.user_id,
        ProjectMember.is_active.is_(True),
    )
    result = await session.execute(
        select(Project.id).where(
            Project.tenant_id == context.tenant_id,
            or_(
                Project.owner_id == context.user_id,
                Project.id.in_(member_sub),
            ),
        )
    )
    return {row[0] for row in result.all()}


@router.get("/datasources/all")
async def list_all_datasources(
    project_id: int | None = Query(default=None),
    search: str = Query(default=""),
    source_type: str | None = Query(default=None),
    assignment: str | None = Query(default=None),
    owner_id: int | None = Query(default=None),
    created_after: datetime | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict:
    """List all data sources the caller is authorized to access.

    Filters:
      * ``project_id`` - restrict to a specific project.
      * ``search`` - free-text match on name, view name, source/connector type.
      * ``source_type`` - ``file``, ``database_table`` or ``saas_object``.
      * ``assignment`` - ``assigned`` (has project), ``unassigned`` (no project),
        or ``all``.
      * ``owner_id`` - sources created by this user.
      * ``created_after`` - sources created at or after this ISO timestamp.
      * ``limit`` / ``cursor`` - pagination (cursor is a base64-encoded offset).
    """
    offset = 0
    if cursor:
        try:
            offset = int(base64.b64decode(cursor.encode()).decode())
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail="Invalid cursor"
            ) from exc

    visible_ids = await _visible_project_ids(session, context)
    is_admin = _is_tenant_admin(context)

    file_rows = list(
        await session.scalars(
            select(FileSourceMeta).where(
                FileSourceMeta.tenant_id == context.tenant_id,
                FileSourceMeta.archived.is_(False),
            )
        )
    )

    db_rows = list(
        await session.scalars(
            select(DatabaseDataSource)
            .where(
                DatabaseDataSource.tenant_id == context.tenant_id,
                DatabaseDataSource.archived.is_(False),
                DatabaseDataSource.status == "active",
            )
            .options(selectinload(DatabaseDataSource.columns))
        )
    )

    user_ids = {f.owner_id for f in file_rows} | {d.created_by for d in db_rows if d.created_by}
    user_map: dict[int, str] = {}
    if user_ids:
        users = list(
            await session.scalars(select(User).where(User.id.in_(user_ids)))
        )
        user_map = {u.id: u.display_name or u.email for u in users}

    project_map: dict[int, dict[str, Any]] = {
        pid: {"id": pid, "name": "—"} for pid in visible_ids
    }
    if visible_ids:
        projects = list(
            await session.scalars(select(Project).where(Project.id.in_(visible_ids)))
        )
        project_map = {p.id: {"id": p.id, "name": p.name} for p in projects}

    def _project_name(pid: int | None) -> str | None:
        if pid is None:
            return None
        return project_map.get(pid, {}).get("name")

    def _user_name(uid: int | None) -> str | None:
        if uid is None:
            return None
        return user_map.get(uid)

    items: list[dict] = []
    for f in file_rows:
        pid = f.project_id
        if pid is not None:
            if pid not in visible_ids:
                continue
        elif f.owner_id != context.user_id and not is_admin:
            continue

        if project_id is not None and pid != project_id:
            continue
        if owner_id is not None and f.owner_id != owner_id:
            continue
        if created_after is not None:
            if f.created_at is None or f.created_at < created_after:
                continue

        source_format = (f.source_format or "csv").lower()
        kind = "file"
        stype = "file"
        db_type = None
        connector_type = None
        if source_format in ("xlsx", "xls", "excel"):
            connector_type = "excel"
        elif source_format == "csv":
            connector_type = "csv"
        else:
            connector_type = source_format

        assigned = pid is not None
        if assignment == "assigned" and not assigned:
            continue
        if assignment == "unassigned" and assigned:
            continue
        if source_type is not None and source_type != stype:
            continue

        name = f.file_name or f.view_name
        if search:
            hay = " ".join(
                str(p)
                for p in [name, f.view_name, stype, connector_type, _project_name(pid)]
                if p
            ).lower()
            if search.lower() not in hay:
                continue

        column_count = len(f.column_types or [])
        items.append({
            "id": f"file:{f.id}",
            "backendId": f.id,
            "kind": kind,
            "name": name,
            "viewName": f.view_name,
            "sourceType": stype,
            "connectorType": connector_type,
            "dbType": db_type,
            "columns": column_count,
            "projectId": pid,
            "projectName": _project_name(pid),
            "ownerId": f.owner_id,
            "ownerName": _user_name(f.owner_id),
            "createdAt": f.created_at.isoformat() if f.created_at else None,
        })

    for d in db_rows:
        pid = d.project_id
        if pid is not None:
            if pid not in visible_ids:
                continue
        elif d.created_by != context.user_id and not is_admin:
            continue

        if project_id is not None and pid != project_id:
            continue
        if owner_id is not None and d.created_by != owner_id:
            continue
        if created_after is not None:
            if d.created_at is None or d.created_at < created_after:
                continue

        is_saas = d.source_type == "saas_object"
        stype = "saas_object" if is_saas else "database_table"
        assigned = pid is not None
        if assignment == "assigned" and not assigned:
            continue
        if assignment == "unassigned" and assigned:
            continue
        if source_type is not None and source_type != stype:
            continue

        name = d.display_name or d.teiid_view_name
        if search:
            hay = " ".join(
                str(p)
                for p in [
                    name,
                    d.teiid_view_name,
                    stype,
                    d.connector_type,
                    d.db_type,
                    _project_name(pid),
                ]
                if p
            ).lower()
            if search.lower() not in hay:
                continue

        column_count = len(d.columns or [])
        items.append({
            "id": f"db:{d.id}",
            "backendId": d.id,
            "kind": stype,
            "name": name,
            "viewName": d.teiid_view_name,
            "sourceType": stype,
            "connectorType": d.connector_type,
            "dbType": d.db_type,
            "schemaName": d.schema_name,
            "tableName": d.table_name,
            "columns": column_count,
            "projectId": pid,
            "projectName": _project_name(pid),
            "ownerId": d.created_by,
            "ownerName": _user_name(d.created_by),
            "createdAt": d.created_at.isoformat() if d.created_at else None,
        })

    items.sort(key=lambda r: (r["createdAt"] or "", r["id"]), reverse=True)

    total = len(items)
    page = items[offset : offset + limit]
    next_cursor: str | None = None
    if offset + limit < total:
        next_cursor = base64.b64encode(str(offset + limit).encode()).decode()

    return {
        "items": page,
        "total": total,
        "next_cursor": next_cursor,
    }


@router.post("/datasources/validate")
async def validate_datasource_selection(
    body: _BulkValidationRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> _BulkValidationResult:
    """Validate a bulk selection before Step 2 assignment.

    Checks tenant/project access, source existence, active status, and whether
    the source is already assigned to the target project (which is allowed but
    flagged as a no-op).  Returns the subset of ``source_ids`` that are valid
    and a map of invalid ids to a short reason.
    """
    project = await session.get(Project, body.project_id)
    if project is None or project.tenant_id != context.tenant_id:
        return _BulkValidationResult(
            valid=[], invalid={sid: "Project not found" for sid in body.source_ids}
        )

    member_sub = select(ProjectMember.project_id).where(
        ProjectMember.user_id == context.user_id,
        ProjectMember.is_active.is_(True),
    )
    project_visible = (
        project.owner_id == context.user_id
        or project.id
        in {
            row[0]
            for row in (
                await session.execute(member_sub)
            ).all()
        }
    )
    if not project_visible and not _is_tenant_admin(context):
        return _BulkValidationResult(
            valid=[], invalid={sid: "Not a project member" for sid in body.source_ids}
        )

    valid: list[str] = []
    invalid: dict[str, str] = {}

    file_ids: set[int] = set()
    db_ids: set[int] = set()
    for sid in body.source_ids:
        if sid.startswith("file:"):
            try:
                file_ids.add(int(sid.split(":", 1)[1]))
            except ValueError:
                invalid[sid] = "Invalid file source id"
        elif sid.startswith("db:"):
            try:
                db_ids.add(int(sid.split(":", 1)[1]))
            except ValueError:
                invalid[sid] = "Invalid database source id"
        else:
            invalid[sid] = "Unrecognized source kind"

    file_rows = {
        f.id: f
        for f in await session.scalars(
            select(FileSourceMeta).where(
                FileSourceMeta.id.in_(file_ids),
                FileSourceMeta.tenant_id == context.tenant_id,
                FileSourceMeta.archived.is_(False),
            )
        )
    }
    db_rows = {
        d.id: d
        for d in await session.scalars(
            select(DatabaseDataSource).where(
                DatabaseDataSource.id.in_(db_ids),
                DatabaseDataSource.tenant_id == context.tenant_id,
                DatabaseDataSource.archived.is_(False),
                DatabaseDataSource.status == "active",
            )
        )
    }

    is_admin = _is_tenant_admin(context)
    for sid in body.source_ids:
        if sid in invalid:
            continue
        if sid.startswith("file:"):
            fid = int(sid.split(":", 1)[1])
            f = file_rows.get(fid)
            if f is None:
                invalid[sid] = "Source not found or archived"
                continue
            if f.project_id is not None and f.project_id != project.id:
                if f.owner_id != context.user_id and not is_admin:
                    invalid[sid] = "Source belongs to another project"
                    continue
            elif f.owner_id != context.user_id and not is_admin:
                invalid[sid] = "Source is private"
                continue
            if f.project_id == project.id:
                valid.append(sid)
                continue
            valid.append(sid)
        else:
            did = int(sid.split(":", 1)[1])
            d = db_rows.get(did)
            if d is None:
                invalid[sid] = "Source not found or archived"
                continue
            if d.project_id is not None and d.project_id != project.id:
                if d.created_by != context.user_id and not is_admin:
                    invalid[sid] = "Source belongs to another project"
                    continue
            elif d.created_by != context.user_id and not is_admin:
                invalid[sid] = "Source is private"
                continue
            valid.append(sid)

    return _BulkValidationResult(valid=valid, invalid=invalid)
