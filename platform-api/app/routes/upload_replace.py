"""In-place file data-source replacement (``/upload/datasources/{view}/replace``).

Split from ``upload.py``; siblings: ``upload_core.py``,
``upload_datasources.py`` and ``upload_versions.py``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.database import get_db
from app.models.file_source_meta import FileSourceMeta
from app.models.tenant import Tenant
from app.models.user import User
from app.routes.upload_versions import _locate_physical_file
from app.services.file_source_versions import (
    compare_schemas,
)
from app.services.file_sources import (
    compute_view_name,
    detect_column_types,
    display_source,
    physical_file_name,
    prepare_replacement_content,
    sanitize_filename,
)
from app.services.tenant_teiid_resolver import TenantTeiidResolver

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/upload", tags=["upload"])


@router.post("/datasources/{view_name}/replace")
async def replace_file_source(
    view_name: str,
    file: UploadFile = File(...),
    force: bool = Query(False, description="Overwrite even if the schema has changed (column renames)."),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    """Replace an uploaded file's data with a new file (item 5).

    The incoming file must have the **same name** as the existing source and
    must contain **all** of the existing columns. New columns are allowed and
    are added without affecting existing data.
    """
    if file.filename is None:
        raise HTTPException(status_code=400, detail="Filename is required")

    user = await session.get(User, context.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    tenant = await session.get(Tenant, context.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    settings = get_settings()
    endpoint = await TenantTeiidResolver(session).resolve_for_org(context.tenant_id)
    if endpoint.is_dedicated and endpoint.vdb_host_path:
        base_path = endpoint.vdb_host_path
    else:
        base_path = settings.customer_base_path
    uploads_dir = (
        Path(base_path)
        / str(context.tenant_id)
        / str(user.id)
        / "uploads"
    )

    # Locate the metadata row first so we know the original source format and
    # can map the display view_name back to the physical (possibly converted) file.
    meta = await session.scalar(
        select(FileSourceMeta).where(
            FileSourceMeta.tenant_id == context.tenant_id,
            FileSourceMeta.owner_id == user.id,
            FileSourceMeta.view_name == view_name,
        )
    )
    if meta is None:
        raise HTTPException(status_code=404, detail="Data source not found")

    # Resolve the existing physical file backing this view.
    existing_path, existing_name = _locate_physical_file(uploads_dir, meta, view_name)
    expected_name, _ = display_source(existing_name, meta.source_format)

    # 1) Same-name check. The user must supply the same original display name
    # (e.g. SalesJournal2025.xlsx) even if the on-disk file is flattened to .csv.
    if sanitize_filename(file.filename) != sanitize_filename(expected_name):
        raise HTTPException(
            status_code=409,
            detail=(
                f'File name mismatch: expected "{expected_name}", '
                f'got "{file.filename}". Replacement must use the same file name.'
            ),
        )
    if meta.file_name != expected_name:
        # Self-heal a stale stored name so future reads/checks agree with it.
        meta.file_name = expected_name

    incoming_content = await file.read()

    # Decide the on-disk filename for the replacement. It should have the
    # original upload extension (.xlsx, .csv, etc.) while JSON/XML/legacy .xls
    # are flattened to .csv for the Teiid servlet.
    new_original_format = (
        file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else None
    )
    target_name = physical_file_name(expected_name, new_original_format)
    target_path = uploads_dir / target_name

    # Convert/sanitize incoming content to the target physical format.
    target_content = prepare_replacement_content(
        file.filename, incoming_content, target_name
    )

    existing_raw = existing_path.read_bytes()
    existing_types = detect_column_types(existing_raw, existing_name)
    existing_cols = {c["field"] for c in existing_types}
    incoming_types = detect_column_types(target_content, target_name)
    incoming_cols = {c["field"] for c in incoming_types}
    diff = compare_schemas(existing_types, incoming_types)
    if diff["blockers"] and not force:
        raise HTTPException(status_code=409, detail=" ".join(diff["blockers"]))

    # 3) Re-import the new file through the Teiid servlet (overwrites the view).
    resolved_vdb_type = meta.vdb_type if meta else "user"
    servlet_url = f"{endpoint.servlet_url}/TeiidExcelImporterTest/upload"
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=10.0)
        ) as client:
            resp = await client.post(
                servlet_url,
                data={
                    "org_id": str(tenant.id),
                    "user_id": str(user.id),
                    "vdb_type": resolved_vdb_type,
                    "replace": "true",
                },
                files={
                    "file": (
                        target_name,
                        target_content,
                        file.content_type or "application/octet-stream",
                    )
                },
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to reach Teiid import servlet: {exc}",
        ) from exc
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"Teiid import failed: {resp.text}",
        )
    try:
        teiid_result = resp.json()
    except Exception:
        teiid_result = {"raw": resp.text}
    if isinstance(teiid_result, dict) and "error" in teiid_result:
        raise HTTPException(status_code=422, detail=teiid_result["error"])

    # 4) Update metadata, migrate the physical file if its extension changed,
    # and keep the view name in sync with the real on-disk filename.
    new_display_name, _ = display_source(target_name, new_original_format)
    new_view_name = compute_view_name(target_name)
    if existing_path != target_path:
        try:
            existing_path.unlink()
        except OSError as exc:
            logger.warning("Could not remove legacy physical file %s: %s", existing_path, exc)
    meta.view_name = new_view_name
    meta.file_name = new_display_name
    meta.source_format = new_original_format
    meta.column_types = incoming_types or None
    await session.commit()

    added = sorted(incoming_cols - existing_cols)
    return {
        "status": "replaced",
        "view_name": new_view_name,
        "fileName": new_display_name,
        "addedColumns": added,
        "columnTypes": incoming_types,
    }

