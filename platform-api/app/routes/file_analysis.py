"""File analysis API routes — AI-assisted upload analysis and metadata management."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.services import data_source_metadata_service as metadata_svc
from app.services import file_ingestion
from app.services.file_ingestion import FileImportError, FinalizeOptions

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/data-sources", tags=["file-analysis"])


def _http_error(exc: FileImportError) -> HTTPException:
    """Map a safe import error code onto an HTTP status."""
    status = {
        "FILE_TOO_LARGE": 413,
        "TEIID_UNREACHABLE": 502,
        "SCANNER_UNAVAILABLE": 503,
        "URL_IMPORT_DISABLED": 403,
        "NETWORK_IMPORT_DISABLED": 403,
        "SECURITY_BLOCKED": 422,
        "USER_NOT_FOUND": 404,
        "TENANT_NOT_FOUND": 404,
        "PROJECT_NOT_FOUND": 404,
        "CONNECTION_NOT_FOUND": 404,
        "STAGED_FILE_MISSING": 410,
    }.get(exc.code, 422)
    return HTTPException(status_code=status, detail=exc.message)


@router.post("/upload/analyze")
async def analyze_upload(
    file: UploadFile = File(...),
    project_id: int | None = Form(None),
    source_name: str | None = Form(None),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Upload a file, profile it, and run AI analysis.

    Returns the profile and AI analysis without finalizing the data source.
    The caller finalizes later with the returned ``import_job_id``
    (``upload_session_id`` remains as an alias for older clients).
    """
    if file.filename is None:
        raise HTTPException(status_code=400, detail="Filename is required")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="File is empty")

    try:
        job, staged = await file_ingestion.acquire_local_upload(
            session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            project_id=project_id,
            filename=file.filename,
            data=content,
            content_type=file.content_type,
        )
        payload = await file_ingestion.profile_staged_file(
            session,
            job,
            staged,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            project_id=project_id,
            source_name=source_name,
        )
    except FileImportError as exc:
        await session.rollback()
        raise _http_error(exc) from exc
    await session.commit()
    return payload


class FinalizeRequest(BaseModel):
    # Either identifier works; ``import_job_id`` is the canonical one.
    import_job_id: str | None = None
    upload_session_id: str | None = None
    project_id: int | None = None
    display_name: str | None = None
    accepted_tags: list[dict[str, Any]] | None = None
    accepted_tag_keys: list[str] | None = None
    rejected_tag_keys: list[str] | None = None
    accepted_kpi_keys: list[str] | None = None
    rejected_kpi_keys: list[str] | None = None
    recommendation_decisions: list[dict[str, Any]] | None = None
    user_notes: str | None = None
    user_nuances: str | None = None


@router.post("/upload/finalize")
async def finalize_upload(
    req: FinalizeRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Finalize an import — create the data source and persist AI metadata.

    Accepts any acquisition method: the staged bytes and profile already live
    on the import job, so local, URL, and network imports converge here.
    """
    job_id = req.import_job_id or req.upload_session_id
    if not job_id:
        raise HTTPException(status_code=400, detail="import_job_id is required")

    job = await file_ingestion.get_job_for_user(
        session, job_id, tenant_id=context.tenant_id, user_id=context.user_id
    )
    if job is None:
        raise HTTPException(
            status_code=404, detail="Import not found or expired"
        )

    options = FinalizeOptions(
        project_id=req.project_id,
        display_name=req.display_name,
        accepted_tags=req.accepted_tags,
        accepted_tag_keys=req.accepted_tag_keys,
        rejected_tag_keys=req.rejected_tag_keys,
        accepted_kpi_keys=req.accepted_kpi_keys,
        rejected_kpi_keys=req.rejected_kpi_keys,
        recommendation_decisions=req.recommendation_decisions,
        user_notes=req.user_notes,
        user_nuances=req.user_nuances,
    )
    try:
        result = await file_ingestion.finalize_tabular_import(
            session,
            job,
            options,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
    except FileImportError as exc:
        await session.rollback()
        job = await file_ingestion.get_job_for_user(
            session, job_id, tenant_id=context.tenant_id, user_id=context.user_id
        )
        if job is not None:
            job.status = "failed"
            job.error_code = exc.code
            job.error_message_safe = exc.message
            await session.commit()
        raise _http_error(exc) from exc

    await session.commit()
    return result


@router.get("/{data_source_id}/ai-profile")
async def get_ai_profile(
    data_source_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Get the AI profile for a data source."""
    result = await metadata_svc.get_ai_profile(session, data_source_id=data_source_id)
    if not result:
        raise HTTPException(status_code=404, detail="No AI profile found for this data source")
    return result


class TagsUpdateRequest(BaseModel):
    tags: list[dict[str, Any]]


@router.patch("/{data_source_id}/tags")
async def update_tags(
    data_source_id: int,
    req: TagsUpdateRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> list[dict[str, Any]]:
    """Update tags for a data source."""
    return await metadata_svc.update_tags(
        session,
        data_source_id=data_source_id,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        project_id=None,
        tags=req.tags,
    )


class RecommendationsUpdateRequest(BaseModel):
    recommendations: list[dict[str, Any]]


@router.patch("/{data_source_id}/recommendations")
async def update_recommendations(
    data_source_id: int,
    req: RecommendationsUpdateRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> list[dict[str, Any]]:
    """Update recommendation statuses."""
    return await metadata_svc.update_recommendations(
        session,
        data_source_id=data_source_id,
        recommendations=req.recommendations,
    )


class NotesUpdateRequest(BaseModel):
    user_notes: str | None = None
    user_nuances: str | None = None


@router.patch("/{data_source_id}/notes")
async def update_notes(
    data_source_id: int,
    req: NotesUpdateRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Update user notes/nuances."""
    result = await metadata_svc.update_user_notes(
        session,
        data_source_id=data_source_id,
        user_notes=req.user_notes,
        user_nuances=req.user_nuances,
    )
    if not result:
        raise HTTPException(status_code=404, detail="No AI profile found")
    return result
