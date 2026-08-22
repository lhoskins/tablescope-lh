"""Project Assets — upload, list, detail, delete unstructured documents.

Documents stored via project_assets are first-class project assets (PDFs, DOCX,
PPTX, TXT, Markdown).  On upload the file is persisted locally, a
``project_assets`` DB row is created, and an ``ai_documents`` row is linked for
downstream AI processing (extraction → chunking → embedding → profiling).
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, has_role, require_role
from app.database import get_db
from app.models.project import Project
from app.models.project_asset import ProjectAsset
from app.routes.ai_proxy_shared import _check_project_access
from app.services import document_preview
from app.services.presentation_engine import PresentationMode
from app.services.response_envelope import attach_envelope

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects/{project_id}/assets", tags=["project-assets"])

# Allowed extensions for POC
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".txt", ".md"}
REJECTED_EXTENSIONS = {".exe", ".bat", ".ps1", ".sh", ".zip", ".rar", ".7z", ".iso"}

EXTENSION_TO_ASSET_TYPE: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".txt": "txt",
    ".md": "markdown",
}

EXTENSION_TO_CONTENT_TYPE: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".txt": "text/plain",
    ".md": "text/markdown",
}

LOCAL_STORAGE_BASE = os.environ.get("ASSET_STORAGE_PATH", "/opt/wildfly/teiidfiles/customers")


# ── Schemas ──────────────────────────────────────────────────────────

class ProjectAssetRead(BaseModel):
    id: int
    tenant_id: int
    project_id: int
    owner_user_id: int | None
    asset_type: str
    source_type: str
    title: str
    description: str | None
    filename: str
    original_filename: str | None
    content_type: str | None
    file_extension: str | None
    storage_provider: str
    file_hash: str | None
    file_size_bytes: int | None
    visibility: str
    status: str
    ai_status: str
    ai_summary: str | None
    ai_metadata: dict
    ai_error_message: str | None
    created_by: int | None
    created_at: datetime
    updated_at: datetime


class ProjectAssetUploadResponse(BaseModel):
    asset_id: int
    ai_document_id: int | None = None
    filename: str
    asset_type: str
    status: str
    ai_status: str


# ── Helpers ──────────────────────────────────────────────────────────

def _sanitize_filename(name: str) -> str:
    """Remove unsafe characters, keep extension."""
    stem = Path(name).stem
    ext = Path(name).suffix.lower()
    safe_stem = re.sub(r"[^\w\-.]", "_", stem)[:200]
    return f"{safe_stem}{ext}"


async def _require_project_access(
    project_id: int,
    session: AsyncSession,
    context: RequestContext,
) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=403, detail="Not in this tenant")
    return project


def _compute_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _store_file_locally(
    tenant_id: int, user_id: int, project_id: int, filename: str, data: bytes,
) -> str:
    """Store a file on the local filesystem and return the absolute path."""
    dir_path = Path(LOCAL_STORAGE_BASE) / str(tenant_id) / str(user_id) / "project_assets" / str(project_id)
    dir_path.mkdir(parents=True, exist_ok=True)
    unique_name = f"{uuid.uuid4().hex[:8]}_{filename}"
    file_path = dir_path / unique_name
    file_path.write_bytes(data)
    return str(file_path)


def _check_asset_read_access(asset: ProjectAsset, context: RequestContext) -> None:
    """Private-document authorization, independent of general project
    access: a document with visibility="private" is readable only by its
    owner (or a tenant admin), even though the caller already passed
    _check_project_access for the project as a whole."""
    if asset.visibility == "private" and asset.owner_user_id != context.user_id:
        if not has_role(context.role, Role.TENANT_ADMIN):
            raise HTTPException(status_code=403, detail="This document is private")


def _resolve_asset_path(asset: ProjectAsset) -> Path:
    """Resolve the asset's on-disk path, rejecting anything outside the
    configured storage root -- defense in depth against a storage_location
    value that (however it got there) doesn't stay inside LOCAL_STORAGE_BASE."""
    if asset.storage_provider != "local" or not asset.storage_location:
        raise HTTPException(status_code=404, detail="Document content is not available")
    root = Path(LOCAL_STORAGE_BASE).resolve()
    try:
        resolved = Path(asset.storage_location).resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="Document content is not available") from None
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Document content is not available")
    return resolved


async def _get_readable_asset(
    project_id: int,
    asset_id: int,
    session: AsyncSession,
    context: RequestContext,
) -> ProjectAsset:
    """Shared gate for the preview/content endpoints: real project
    membership (not just tenant match -- see _check_project_access, which
    also honors private, non-shared projects), then the asset's own
    visibility check."""
    await _check_project_access(session, context, project_id)
    asset = await session.get(ProjectAsset, asset_id)
    if not asset or asset.project_id != project_id or asset.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Asset not found")
    _check_asset_read_access(asset, context)
    return asset


# ── Background processing ────────────────────────────────────────────

async def _process_asset_background(
    asset_id: int,
    project_id: int,
    tenant_id: int,
    user_id: int,
    force: bool = False,
) -> None:
    """Run extraction → chunking → profiling in background."""
    from app.database import SessionLocal
    from app.services.document_processing_service import process_document_asset

    try:
        async with SessionLocal() as session:
            asset = await session.get(ProjectAsset, asset_id)
            if not asset:
                return
            # The pipeline owns status transitions: it leaves the asset
            # untouched when the file-hash gate skips an unchanged document.
            await process_document_asset(
                session, asset, tenant_id, project_id, user_id, force=force,
            )
    except Exception:
        logger.exception("Background processing failed for asset %d", asset_id)
        try:
            async with SessionLocal() as session:
                asset = await session.get(ProjectAsset, asset_id)
                if asset:
                    asset.ai_status = "failed"
                    asset.ai_error_message = "Background processing failed"
                    await session.commit()
        except Exception:
            logger.exception("Failed to mark asset %d as failed", asset_id)


# ── Endpoints ────────────────────────────────────────────────────────

@router.post("/upload", response_model=ProjectAssetUploadResponse)
async def upload_asset(
    project_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    asset_type: str | None = Form(None),
    visibility: str | None = Form("shared_project"),
    title: str | None = Form(None),
    description: str | None = Form(None),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
):
    await _require_project_access(project_id, session, context)

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = Path(file.filename).suffix.lower()
    if ext in REJECTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type {ext} is not allowed")
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}")

    data = await file.read()
    sanitized = _sanitize_filename(file.filename)
    file_hash = _compute_hash(data)

    resolved_type = asset_type or EXTENSION_TO_ASSET_TYPE.get(ext, "other_document")
    content_type = EXTENSION_TO_CONTENT_TYPE.get(ext, file.content_type or "application/octet-stream")

    storage_loc = _store_file_locally(
        context.tenant_id, context.user_id, project_id, sanitized, data,
    )

    asset = ProjectAsset(
        tenant_id=context.tenant_id,
        project_id=project_id,
        owner_user_id=context.user_id,
        asset_type=resolved_type,
        source_type="uploaded_file",
        title=title or Path(file.filename).stem,
        description=description,
        filename=sanitized,
        original_filename=file.filename,
        content_type=content_type,
        file_extension=ext,
        storage_provider="local",
        storage_location=storage_loc,
        file_hash=file_hash,
        file_size_bytes=len(data),
        visibility=visibility or "shared_project",
        status="uploaded",
        ai_status="pending",
        ai_metadata={},
        created_by=context.user_id,
    )
    session.add(asset)
    await session.flush()

    # Create ai_documents row
    ai_doc_id: int | None = None
    try:
        from sqlalchemy import text
        result = await session.execute(
            text("""
                INSERT INTO ai_documents
                    (tenant_id, project_id, owner_user_id, visibility, source_type,
                     source_id, filename, content_type, file_hash, status, created_by)
                VALUES
                    (:tenant_id, :project_id, :owner_user_id, :visibility, 'project_asset',
                     :source_id, :filename, :content_type, :file_hash, 'pending', :created_by)
                RETURNING id
            """),
            {
                "tenant_id": context.tenant_id,
                "project_id": project_id,
                "owner_user_id": context.user_id,
                "visibility": visibility or "shared_project",
                "source_id": asset.id,
                "filename": sanitized,
                "content_type": content_type,
                "file_hash": file_hash,
                "created_by": context.user_id,
            },
        )
        row = result.fetchone()
        if row:
            ai_doc_id = row[0]
    except Exception:
        logger.exception("Failed to create ai_documents row for asset %d", asset.id)

    await session.commit()

    # Trigger background processing
    background_tasks.add_task(
        _process_asset_background, asset.id, project_id, context.tenant_id, context.user_id,
    )

    return ProjectAssetUploadResponse(
        asset_id=asset.id,
        ai_document_id=ai_doc_id,
        filename=sanitized,
        asset_type=resolved_type,
        status="uploaded",
        ai_status="pending",
    )


@router.get("", response_model=list[ProjectAssetRead])
async def list_assets(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
):
    await _require_project_access(project_id, session, context)
    result = await session.execute(
        select(ProjectAsset)
        .where(ProjectAsset.project_id == project_id, ProjectAsset.tenant_id == context.tenant_id)
        .order_by(ProjectAsset.created_at.desc())
    )
    assets = result.scalars().all()
    return [ProjectAssetRead.model_validate(a, from_attributes=True) for a in assets]


@router.get("/{asset_id}", response_model=ProjectAssetRead)
async def get_asset(
    project_id: int,
    asset_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
):
    await _require_project_access(project_id, session, context)
    asset = await session.get(ProjectAsset, asset_id)
    if not asset or asset.project_id != project_id or asset.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Asset not found")
    return ProjectAssetRead.model_validate(asset, from_attributes=True)


@router.delete("/{asset_id}")
async def delete_asset(
    project_id: int,
    asset_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
):
    await _require_project_access(project_id, session, context)
    asset = await session.get(ProjectAsset, asset_id)
    if not asset or asset.project_id != project_id or asset.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Remove file from disk
    try:
        if asset.storage_provider == "local" and asset.storage_location:
            p = Path(asset.storage_location)
            if p.exists():
                p.unlink()
    except Exception:
        logger.warning("Could not delete file for asset %d", asset_id)

    # Remove ai_documents + chunks
    try:
        from sqlalchemy import text

        from app.services.project_graph_service import archive_empty_family

        await session.execute(
            text("DELETE FROM ai_document_chunks WHERE document_id IN (SELECT id FROM ai_documents WHERE source_type='project_asset' AND source_id=:sid)"),
            {"sid": asset_id},
        )
        await session.execute(
            text("DELETE FROM ai_documents WHERE source_type='project_asset' AND source_id=:sid"),
            {"sid": asset_id},
        )
        # Capture families this document belonged to before its edges are removed,
        # so we can archive any that become empty.
        fam_rows = await session.execute(
            text(
                """
                SELECT DISTINCT e.to_node_id
                FROM ai_project_graph_edges e
                JOIN ai_project_graph_nodes n ON n.id = e.from_node_id
                WHERE n.source_type='project_asset' AND n.source_id=:sid
                  AND e.relationship_type='belongs_to_family'
                """
            ),
            {"sid": asset_id},
        )
        family_ids = [r[0] for r in fam_rows.fetchall()]
        # Remove graph nodes/edges for this asset
        await session.execute(
            text("DELETE FROM ai_project_graph_edges WHERE from_node_id IN (SELECT id FROM ai_project_graph_nodes WHERE source_type='project_asset' AND source_id=:sid) OR to_node_id IN (SELECT id FROM ai_project_graph_nodes WHERE source_type='project_asset' AND source_id=:sid)"),
            {"sid": asset_id},
        )
        await session.execute(
            text("DELETE FROM ai_project_graph_nodes WHERE source_type='project_asset' AND source_id=:sid"),
            {"sid": asset_id},
        )
        for fid in family_ids:
            await archive_empty_family(session, context.tenant_id, project_id, fid)
    except Exception:
        logger.exception("Error cleaning up AI data for asset %d", asset_id)

    await session.delete(asset)
    await session.commit()
    return {"status": "deleted", "asset_id": asset_id}


@router.post("/{asset_id}/ai/process")
async def trigger_ai_processing(
    project_id: int,
    asset_id: int,
    background_tasks: BackgroundTasks,
    force: bool = True,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
):
    """Reprocess one document.

    A user-initiated Reprocess forces the full pipeline by default; pass
    ``force=false`` to honor the file-hash gate (skip when the stored bytes are
    unchanged and the asset is already profiled), which is what automated
    cascades use.
    """
    await _require_project_access(project_id, session, context)
    asset = await session.get(ProjectAsset, asset_id)
    if not asset or asset.project_id != project_id or asset.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Asset not found")

    if force:
        # Only reset status when we know the pipeline will run; a gated skip
        # must leave a profiled asset's status untouched.
        asset.ai_status = "pending"
        asset.ai_error_message = None
        await session.commit()

    background_tasks.add_task(
        _process_asset_background,
        asset.id, project_id, context.tenant_id, context.user_id, force,
    )
    return {"status": "processing", "asset_id": asset_id, "force": force}


@router.post("/reprocess")
async def trigger_project_reprocess(
    project_id: int,
    force: bool = False,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
):
    """Reprocess every document in the project, then rebuild its knowledge graph.

    Enqueues the worker-side cascade: each document is re-run through
    extraction → profiling → graph rows (skipping files whose bytes are
    unchanged unless ``force=true``), and the knowledge-graph snapshot is
    rebuilt as the terminal stage only if something actually changed. Repeat
    triggers coalesce onto the in-flight job for this project.
    """
    await _require_project_access(project_id, session, context)
    from app.tasks.workflows import enqueue_reprocess_project

    try:
        job_id = await enqueue_reprocess_project(
            tenant_id=context.tenant_id,
            project_id=project_id,
            user_id=context.user_id,
            force=force,
        )
    except Exception:
        logger.exception(
            "Failed to enqueue project reprocess for project %d", project_id
        )
        raise HTTPException(
            status_code=503,
            detail="Background worker is unavailable; try again shortly.",
        ) from None

    # An empty job id means an identical cascade is already queued or running.
    return {
        "status": "queued" if job_id else "already_running",
        "project_id": project_id,
        "job_id": job_id or None,
        "force": force,
    }


@router.get("/{asset_id}/ai/profile")
async def get_asset_ai_profile(
    project_id: int,
    asset_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
):
    await _require_project_access(project_id, session, context)
    asset = await session.get(ProjectAsset, asset_id)
    if not asset or asset.project_id != project_id or asset.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Asset not found")
    profile: dict = {
        "asset_id": asset.id,
        "ai_status": asset.ai_status,
        "ai_summary": asset.ai_summary,
        "ai_metadata": asset.ai_metadata,
        "ai_error_message": asset.ai_error_message,
    }
    # M4 fast-follow (contract-only): stamp the shared ResponseEnvelope so the
    # document profile also emits the unified contract. The profile drawer keeps
    # its bespoke renderer; this is additive metadata (fail-closed) it ignores.
    attach_envelope(
        profile,
        PresentationMode.DOCUMENT,
        summary=asset.ai_summary or None,
        status=asset.ai_status or None,
    )
    return profile


@router.get("/{asset_id}/content")
async def get_asset_content(
    project_id: int,
    asset_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> FileResponse:
    """Stream a document's original bytes for native viewing (PDF/image) or
    download. Never returns the on-disk path -- only the bytes themselves,
    with headers that keep the browser from caching or sniffing them."""
    asset = await _get_readable_asset(project_id, asset_id, session, context)
    path = _resolve_asset_path(asset)
    return FileResponse(
        path,
        media_type=asset.content_type or "application/octet-stream",
        filename=asset.original_filename or asset.filename,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/{asset_id}/preview")
async def get_asset_preview(
    project_id: int,
    asset_id: int,
    response: Response,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict:
    """Bounded, structured preview of a document's content -- see
    app.services.document_preview for the per-format size limits and the
    "kind" values the frontend viewer switches on. Never proxies the file to
    an external preview service; everything is parsed locally."""
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    asset = await _get_readable_asset(project_id, asset_id, session, context)

    def _read_bytes() -> bytes:
        return _resolve_asset_path(asset).read_bytes()

    result = document_preview.build_preview(
        file_extension=asset.file_extension,
        file_size_bytes=asset.file_size_bytes,
        read_bytes=_read_bytes,
    )
    return {
        "assetId": asset.id,
        "filename": asset.original_filename or asset.filename,
        "contentType": asset.content_type,
        "fileSizeBytes": asset.file_size_bytes,
        **result,
    }
