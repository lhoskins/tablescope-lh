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

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.project import Project
from app.models.project_asset import ProjectAsset

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


# ── Background processing ────────────────────────────────────────────

async def _process_asset_background(asset_id: int, project_id: int, tenant_id: int, user_id: int) -> None:
    """Run extraction → chunking → profiling in background."""
    from app.database import SessionLocal
    from app.services.document_processing_service import process_document_asset

    try:
        async with SessionLocal() as session:
            asset = await session.get(ProjectAsset, asset_id)
            if not asset:
                return
            asset.ai_status = "extracting"
            await session.commit()

            await process_document_asset(session, asset, tenant_id, project_id, user_id)
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
        await session.execute(
            text("DELETE FROM ai_document_chunks WHERE document_id IN (SELECT id FROM ai_documents WHERE source_type='project_asset' AND source_id=:sid)"),
            {"sid": asset_id},
        )
        await session.execute(
            text("DELETE FROM ai_documents WHERE source_type='project_asset' AND source_id=:sid"),
            {"sid": asset_id},
        )
        # Remove graph nodes/edges for this asset
        await session.execute(
            text("DELETE FROM ai_project_graph_edges WHERE from_node_id IN (SELECT id FROM ai_project_graph_nodes WHERE source_type='project_asset' AND source_id=:sid) OR to_node_id IN (SELECT id FROM ai_project_graph_nodes WHERE source_type='project_asset' AND source_id=:sid)"),
            {"sid": asset_id},
        )
        await session.execute(
            text("DELETE FROM ai_project_graph_nodes WHERE source_type='project_asset' AND source_id=:sid"),
            {"sid": asset_id},
        )
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
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
):
    await _require_project_access(project_id, session, context)
    asset = await session.get(ProjectAsset, asset_id)
    if not asset or asset.project_id != project_id or asset.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Asset not found")

    asset.ai_status = "pending"
    asset.ai_error_message = None
    await session.commit()

    background_tasks.add_task(
        _process_asset_background, asset.id, project_id, context.tenant_id, context.user_id,
    )
    return {"status": "processing", "asset_id": asset_id}


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
    return {
        "asset_id": asset.id,
        "ai_status": asset.ai_status,
        "ai_summary": asset.ai_summary,
        "ai_metadata": asset.ai_metadata,
        "ai_error_message": asset.ai_error_message,
    }
