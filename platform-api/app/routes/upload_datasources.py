"""File data-source inventory and management routes under ``/upload``.

Split from ``upload.py``; siblings: ``upload_core.py``, ``upload_replace.py``
and ``upload_versions.py``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.database import get_db
from app.models.database_data_source import DatabaseDataSource
from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project
from app.models.user import User
from app.routes.database_sources_lifecycle import find_query_dependencies
from app.schemas.archive_source import ArchiveSourceRequest
from app.services.file_sources import (
    candidate_physical_names,
    compute_view_name,
    display_source,
)
from app.services.tenant_teiid_resolver import TenantTeiidResolver

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/upload", tags=["upload"])


@router.get("/datasources")
async def list_datasources(
    include_archived: bool = False,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> list[dict]:
    """List uploaded datasources for the current user by scanning their uploads directory."""
    user = await session.get(User, context.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    settings = get_settings()
    endpoint = await TenantTeiidResolver(session).resolve_for_org(context.tenant_id)
    if endpoint.is_dedicated and endpoint.vdb_host_path:
        base_path = endpoint.vdb_host_path
    else:
        base_path = settings.customer_base_path
    uploads_dir = Path(base_path) / str(context.tenant_id) / str(user.id) / "uploads"

    # Metadata (archive flag, project association, column types). Because the
    # physical filename on disk may differ from the display name (e.g. a JSON
    # file is flattened to .csv while the UI shows .json), we match files to
    # meta rows by the candidate physical names derived from the stored
    # file_name + source_format. This also self-heals rows whose view_name or
    # file_name drifted stale from older code.
    meta_rows = (
        await session.scalars(
            select(FileSourceMeta).where(
                FileSourceMeta.tenant_id == context.tenant_id,
                FileSourceMeta.owner_id == user.id,
            )
        )
    ).all()
    candidate_to_metas: dict[str, list[tuple[int, FileSourceMeta]]] = {}
    for m in meta_rows:
        for priority, candidate in enumerate(
            candidate_physical_names(m.file_name, m.source_format)
        ):
            candidate_to_metas.setdefault(candidate, []).append((priority, m))

    files = [
        f
        for f in sorted(uploads_dir.iterdir())
        if f.is_file() and not f.name.startswith(".") and f.name not in {".staging", ".versions"}
    ]

    # Assign each file to the best matching meta (exact primary candidate first).
    assigned_meta: dict[int, Path] = {}
    meta_for_file: dict[Path, FileSourceMeta] = {}
    for f in files:
        candidates = candidate_to_metas.get(f.name, [])
        candidates.sort(key=lambda x: x[0])
        for _priority, matched in candidates:
            if matched.id not in assigned_meta:
                view_name = compute_view_name(f.name)
                if matched.view_name != view_name:
                    matched.view_name = view_name
                display_name, _ = display_source(f.name, matched.source_format)
                if matched.file_name != display_name:
                    matched.file_name = display_name
                assigned_meta[matched.id] = f
                meta_for_file[f] = matched
                break

    # Any meta without a matching file still appears (orphaned metadata).
    unassigned_metas = [m for m in meta_rows if m.id not in assigned_meta]

    datasources: list[dict] = []
    for f in files:
        file_meta = meta_for_file.get(f)
        is_archived = bool(file_meta and file_meta.archived)
        if is_archived and not include_archived:
            continue
        view_name = compute_view_name(f.name)
        display_name, source_type = display_source(
            f.name, file_meta.source_format if file_meta else None
        )
        datasources.append({
            "fileName": display_name,
            "viewName": view_name,
            "size": f.stat().st_size,
            "sourceType": source_type,
            "dbType": None,
            "fileMetaId": file_meta.id if file_meta else None,
            "projectId": file_meta.project_id if file_meta else None,
            "columnTypes": (file_meta.column_types or []) if file_meta else [],
            "archived": is_archived,
        })
    for orphan in unassigned_metas:
        if orphan.archived and not include_archived:
            continue
        datasources.append({
            "fileName": orphan.file_name,
            "viewName": orphan.view_name,
            "size": None,
            "sourceType": orphan.source_format or "file",
            "dbType": None,
            "fileMetaId": orphan.id,
            "projectId": orphan.project_id,
            "columnTypes": orphan.column_types or [],
            "archived": orphan.archived,
        })

    await session.commit()

    # Append the user's database-backed data sources (not tied to a project).
    db_sources = (
        await session.scalars(
            select(DatabaseDataSource).where(
                DatabaseDataSource.tenant_id == context.tenant_id,
                DatabaseDataSource.created_by == user.id,
                DatabaseDataSource.project_id.is_(None),
                DatabaseDataSource.status == "active",
                DatabaseDataSource.archived.is_(False),
            )
        )
    ).all()
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
        })

    return datasources


async def _get_or_create_file_meta(
    session: AsyncSession, *, tenant_id: int, owner_id: int, view_name: str
) -> FileSourceMeta:
    meta = await session.scalar(
        select(FileSourceMeta).where(
            FileSourceMeta.tenant_id == tenant_id,
            FileSourceMeta.owner_id == owner_id,
            FileSourceMeta.view_name == view_name,
        )
    )
    if meta is None:
        meta = FileSourceMeta(
            tenant_id=tenant_id,
            owner_id=owner_id,
            view_name=view_name,
            file_name=view_name,
        )
        session.add(meta)
        await session.flush()
    return meta


@router.patch("/datasources/{view_name}/archive")
async def archive_file_source(
    view_name: str,
    body: ArchiveSourceRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    """Archive (hide) or unarchive an uploaded-file data source (item 1)."""

    meta = await _get_or_create_file_meta(
        session,
        tenant_id=context.tenant_id,
        owner_id=context.user_id,
        view_name=view_name,
    )
    meta.archived = body.archived
    meta.archived_at = datetime.now(UTC) if body.archived else None
    await session.commit()
    await session.refresh(meta)
    return meta.to_dict()


@router.patch("/datasources/{view_name}/project")
async def set_file_source_project(
    view_name: str,
    project_id: int | None = None,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    """Associate/de-associate a file data source with a project (item 3).

    Only the data source owner (uploader) may change its project association.
    Pass no ``project_id`` to remove it from its project.
    """
    meta = await _get_or_create_file_meta(
        session,
        tenant_id=context.tenant_id,
        owner_id=context.user_id,
        view_name=view_name,
    )
    if project_id is not None:
        project = await session.get(Project, project_id)
        if project is None or project.tenant_id != context.tenant_id:
            raise HTTPException(status_code=404, detail="Project not found")
    meta.project_id = project_id
    await session.commit()
    await session.refresh(meta)
    return meta.to_dict()


@router.get("/datasources/{view_name}/preflight-delete")
async def preflight_delete_file_source(
    view_name: str,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    """Return whether a file data source can be permanently deleted."""
    meta = await session.scalar(
        select(FileSourceMeta).where(
            FileSourceMeta.tenant_id == context.tenant_id,
            FileSourceMeta.owner_id == context.user_id,
            FileSourceMeta.view_name == view_name,
        )
    )
    if meta is None:
        raise HTTPException(status_code=404, detail="Data source not found")

    blockers: list[dict[str, str]] = []
    if not meta.archived:
        blockers.append({
            "category": "not_archived",
            "message": "Archive the data source before deleting it.",
        })

    deps = await find_query_dependencies(
        session, tenant_id=context.tenant_id, view_name=view_name
    )
    if deps:
        blockers.append({
            "category": "active_dependencies",
            "message": f"{len(deps)} active saved quer{'y' if len(deps) == 1 else 'ies'} depend on this source.",
        })

    from app.models.data_source_ai_profile import DataSourceAIProfile

    ai_profile = await session.scalar(
        select(DataSourceAIProfile).where(DataSourceAIProfile.data_source_id == meta.id)
    )
    ai_profile_count = 1 if ai_profile else 0

    return {
        "view_name": view_name,
        "safe": len(blockers) == 0 and meta.archived,
        "archived": meta.archived,
        "blockers": blockers,
        "active_query_dependencies": deps,
        "ai_profile_count": ai_profile_count,
    }


@router.delete("/datasources/{view_name}")
async def delete_file_source(
    view_name: str,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    """Delete an uploaded-file data source (item 1).

    Mirrors database-source delete rules: the source must be archived first,
    and may not be deleted while an active saved query depends on it.
    """
    user = await session.get(User, context.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    meta = await session.scalar(
        select(FileSourceMeta).where(
            FileSourceMeta.tenant_id == context.tenant_id,
            FileSourceMeta.owner_id == context.user_id,
            FileSourceMeta.view_name == view_name,
        )
    )
    if meta is None or not meta.archived:
        raise HTTPException(
            status_code=409,
            detail="Archive the data source before deleting it.",
        )

    deps = await find_query_dependencies(
        session, tenant_id=context.tenant_id, view_name=view_name
    )
    if deps:
        names = ", ".join(d["name"] for d in deps)
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete: {len(deps)} active query(ies) depend on this source ({names}).",
        )

    # Remove the physical file (best-effort) and the metadata row. Bound
    # tenants store uploads under their dedicated data plane's VDB path.
    settings = get_settings()
    endpoint = await TenantTeiidResolver(session).resolve_for_org(context.tenant_id)
    if endpoint.is_dedicated and endpoint.vdb_host_path:
        base_path = endpoint.vdb_host_path
    else:
        base_path = settings.customer_base_path
    uploads_dir = (
        Path(base_path)
        / str(context.tenant_id)
        / str(context.user_id)
        / "uploads"
    )
    # Remove all file variants (original + converted CSV).
    # XLSX files are converted to CSV on upload, so both may exist.
    candidates = [
        uploads_dir / meta.file_name,
    ]
    # If the stored name ends with .xlsx/.xls, also try the .csv variant
    stem = meta.file_name.rsplit(".", 1)[0] if "." in meta.file_name else meta.file_name
    for ext in (".csv", ".xlsx", ".xls", ".txt", ".tsv"):
        candidates.append(uploads_dir / f"{stem}{ext}")
    # Also try matching by view_name stem (e.g., ManagmentReport from ManagmentReport_CSV)
    view_stem = view_name.rsplit("_", 1)[0] if "_" in view_name else view_name
    for ext in (".csv", ".xlsx", ".xls", ".txt", ".tsv"):
        candidates.append(uploads_dir / f"{view_stem}{ext}")

    removed_any = False
    for candidate in candidates:
        try:
            if candidate.is_file():
                candidate.unlink()
                removed_any = True
                logger.info("Removed file: %s", candidate)
        except OSError as exc:
            logger.warning("Failed to remove file %s: %s", candidate, exc)

    if not removed_any:
        logger.warning("No physical file found for %s in %s", view_name, uploads_dir)

    # Remove Teiid view and foreign table (best-effort)
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0)
        ) as teiid_client:
            teiid_resp = await teiid_client.post(
                f"{endpoint.servlet_url}/TeiidExcelImporterTest/deleteDataSource",
                data={"dataSourceName": view_name},
            )
            if teiid_resp.status_code == 200:
                logger.info("Teiid view/foreign-table removed for %s", view_name)
            else:
                logger.warning(
                    "Teiid deleteDataSource returned %s for %s: %s",
                    teiid_resp.status_code, view_name, teiid_resp.text,
                )
    except httpx.RequestError as exc:
        logger.warning("Failed to contact Teiid servlet to delete %s: %s", view_name, exc)

    # Also clean up any orphaned AI profile data
    from app.models.data_source_ai_profile import (
        DataSourceAIProfile,
        DataSourceAIRecommendation,
        DataSourceFieldProfile,
        DataSourceTag,
    )

    for model in (DataSourceAIRecommendation, DataSourceTag, DataSourceFieldProfile, DataSourceAIProfile):
        orphans = (
            await session.scalars(
                select(model).where(model.data_source_id == meta.id)
            )
        ).all()
        for o in orphans:
            await session.delete(o)

    await session.delete(meta)
    await session.commit()
    return {"status": "deleted", "view_name": view_name}

