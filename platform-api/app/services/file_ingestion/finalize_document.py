
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.file_import_job import FileImportJob

from .staging import FileImportError, discard_quarantine, read_staged_bytes


async def finalize_document_import(
    session: AsyncSession,
    job: FileImportJob,
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
    title: str | None = None,
) -> dict[str, Any]:
    """Hand a staged document to the existing Project Asset pipeline.

    Documents never become Teiid views: they are stored as project assets and
    processed by the existing extraction / embedding / knowledge-graph flow.
    """
    from pathlib import Path as _Path

    from app.models.project import Project
    from app.models.project_asset import ProjectAsset
    from app.routes.project_assets import (
        EXTENSION_TO_ASSET_TYPE,
        EXTENSION_TO_CONTENT_TYPE,
        _store_file_locally,
    )

    if job.status == "completed" and job.result_json:
        return job.result_json
    if job.content_family != "document":
        raise FileImportError(
            "WRONG_CONTENT_FAMILY", "That file is not a document import."
        )

    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != tenant_id:
        raise FileImportError("PROJECT_NOT_FOUND", "Project not found")

    job.status = "finalizing"
    data = read_staged_bytes(job)
    filename = job.sanitized_file_name or "document"
    ext = _Path(filename).suffix.lower()
    storage_loc = _store_file_locally(tenant_id, user_id, project_id, filename, data)

    asset = ProjectAsset(
        tenant_id=tenant_id,
        project_id=project_id,
        owner_user_id=user_id,
        asset_type=EXTENSION_TO_ASSET_TYPE.get(ext, "other_document"),
        source_type="uploaded_file",
        title=title or _Path(filename).stem,
        filename=filename,
        original_filename=job.original_file_name or filename,
        content_type=EXTENSION_TO_CONTENT_TYPE.get(
            ext, job.detected_mime_type or "application/octet-stream"
        ),
        file_extension=ext,
        storage_provider="local",
        storage_location=storage_loc,
        file_hash=job.sha256,
        file_size_bytes=job.file_size_bytes or len(data),
        visibility="shared_project",
        status="uploaded",
        ai_status="pending",
        ai_metadata={},
        created_by=user_id,
    )
    session.add(asset)
    await session.flush()

    result = {
        "asset_id": asset.id,
        "import_job_id": job.id,
        "project_id": project_id,
        "file_name": filename,
        "content_family": "document",
        "acquisition_method": job.method,
        "status": "uploaded",
    }
    job.status = "completed"
    job.result_json = result
    discard_quarantine(job)
    return result
