"""Project datasource membership, column metadata and availability.

Split from ``projects.py``; see ``projects_shared.py`` for the helper cluster.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.database_data_source import DatabaseDataSource
from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project
from app.models.saas_object_data_source import SaasObjectDataSource
from app.models.tenant import Tenant
from app.models.user import User
from app.routes.projects_shared import _is_project_admin
from app.services.database_introspection_service import (
    map_to_teiid_type as _map_teiid_type,
)
from app.services.file_sources import display_source
from app.services.tenant_teiid_resolver import TenantTeiidResolver

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["projects"])


def _format_dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _owner_name(user: User | None) -> str:
    if user is None:
        return "—"
    return user.display_name or f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email.split("@")[0]


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

    # Resolve owners and SaaS identities once for all returned sources.
    user_ids = {owner_id}
    for m in meta_rows:
        user_ids.add(m.owner_id)

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
        if ds.created_by is not None:
            user_ids.add(ds.created_by)

    users = {
        u.id: u
        for u in (
            await session.scalars(select(User).where(User.id.in_(user_ids)))
        ).all()
    }

    db_ids = [ds.id for ds in db_sources]
    saas_rows = (
        await session.scalars(
            select(SaasObjectDataSource).where(
                SaasObjectDataSource.database_data_source_id.in_(db_ids)
            )
        )
    ).all()
    saas_by_db: dict[int, SaasObjectDataSource] = {
        s.database_data_source_id: s for s in saas_rows
    }

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
                owner = users.get(meta.owner_id if meta else owner_id)
                datasources.append({
                    "fileName": display_name,
                    "viewName": view_name,
                    "size": f.stat().st_size,
                    "sourceType": source_type,
                    "dbType": None,
                    "fileMetaId": meta.id if meta else None,
                    "projectId": meta.project_id if meta else None,
                    "id": meta.id if meta else None,
                    "ownerId": meta.owner_id if meta else owner_id,
                    "ownerName": _owner_name(owner),
                    "columnTypes": (meta.column_types or []) if meta else [],
                    "aiMetadata": (meta.ai_metadata or {}) if meta else {},
                    "archived": is_archived,
                    "archivedAt": _format_dt(meta.archived_at if meta else None),
                    "lifecycleKind": "file",
                    "lifecycleId": view_name,
                })

    # Append database-backed data sources registered against this project.
    for ds in db_sources:
        is_saas = ds.source_type == "saas_object"
        saas = saas_by_db.get(ds.id)
        lifecycle_kind = "saas" if is_saas and saas else "database"
        lifecycle_id = str(saas.id) if is_saas and saas else str(ds.id)
        cols = sorted(
            ds.columns, key=lambda c: (c.ordinal_position or 0, c.column_name)
        )
        owner = users.get(ds.created_by) if ds.created_by is not None else None
        datasources.append({
            "fileName": ds.display_name,
            "viewName": ds.teiid_view_name,
            "size": None,
            "sourceType": "saas_object" if is_saas else "database_table",
            "dbType": ds.db_type,
            "connectorType": ds.connector_type,
            "id": ds.id,
            "ownerId": ds.created_by,
            "ownerName": _owner_name(owner),
            "columnTypes": [
                {
                    "name": c.column_name,
                    "type": c.teiid_type_override
                    or _map_teiid_type(c.data_type or ""),
                }
                for c in cols
            ],
            "archived": ds.archived,
            "archivedAt": _format_dt(ds.archived_at),
            "lifecycleKind": lifecycle_kind,
            "lifecycleId": lifecycle_id,
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
                    c.get("field") or c["name"]
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

