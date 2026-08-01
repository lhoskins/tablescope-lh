"""Unified upload intake endpoints.

``GET /uploads/capabilities`` is the single source of truth for the formats and
size limit the UI may offer; ``POST /uploads/classify`` runs the governed
classifier so the client can show the detected family and destination before
any processor is invoked.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.services.file_source_versions import checksum
from app.services.upload_intake import (
    MAX_UPLOAD_BYTES,
    UploadRejected,
    capabilities,
    classify_upload,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.get("/capabilities")
async def get_capabilities(
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict:
    """Accepted formats, families and size limit enforced by the intake."""
    return capabilities()


@router.post("/classify")
async def classify(
    file: UploadFile = File(...),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    """Classify a single file without ingesting it."""
    if file.filename is None:
        raise HTTPException(status_code=400, detail="Filename is required")
    content = await file.read()
    try:
        result = classify_upload(
            file.filename, content, file.content_type, max_bytes=MAX_UPLOAD_BYTES
        )
    except UploadRejected as exc:
        # Filenames are echoed back to their own uploader only; no file content
        # or storage path is ever included in the response or the log line.
        logger.info("Upload rejected (%s) for tenant=%s", exc.code, context.tenant_id)
        raise HTTPException(
            status_code=422, detail={"code": exc.code, "message": exc.message}
        ) from exc
    return {
        **result.to_dict(),
        "fileName": file.filename,
        "sizeBytes": len(content),
        "checksum": checksum(content),
    }
