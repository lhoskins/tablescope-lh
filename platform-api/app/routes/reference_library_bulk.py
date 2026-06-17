"""Bulk URL import API for the Industry-tier Reference Library."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
)
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy import select

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import SessionLocal, get_db
from app.models.audit_event import AuditEvent
from app.models.reference_library import (
    ReferenceLibraryImportBatch,
    ReferenceLibraryImportRow,
)
from app.services import reference_library_bulk as bulk
from app.services.reference_library_service import can_write_industry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reference-library/bulk-import", tags=["reference-library"])

MAX_CSV_BYTES = 5 * 1024 * 1024


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@router.post("/validate")
async def validate_csv(
    file: UploadFile = File(...),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
    session=Depends(get_db),
) -> dict:
    """Validate an uploaded CSV and create a batch with per-row status."""
    if not can_write_industry(context):
        raise HTTPException(status_code=403, detail="Industry import requires platform staff")

    content = await file.read()
    if len(content) > MAX_CSV_BYTES:
        raise HTTPException(status_code=400, detail="CSV exceeds 5MB limit")

    columns = bulk.csv_columns(content)
    missing = [c for c in bulk.REQUIRED_COLUMNS if c not in columns]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required columns: {', '.join(missing)}",
        )

    rows = bulk.parse_csv_rows(content)
    if not rows:
        raise HTTPException(status_code=400, detail="CSV has no data rows")

    validated = await bulk.validate_rows(session, rows)

    batch = ReferenceLibraryImportBatch(
        tier="industry",
        tenant_id=context.tenant_id,
        uploaded_by=context.user_id,
        status="ready",
        total_rows=len(validated),
    )
    session.add(batch)
    await session.flush()

    for r in validated:
        session.add(
            ReferenceLibraryImportRow(
                batch_id=batch.id,
                row_number=r["rowNumber"],
                title=r["title"] or "(untitled)",
                issuing_body=r["issuingBody"] or None,
                domain_tag=r["domainTag"],
                applicability_tag=r["applicabilityTag"] or None,
                source_url=r["sourceUrl"] or "",
                version_label=r["versionLabel"] or None,
                fetch_method_hint=r["fetchMethodHint"] or None,
                status=r["status"],
                failure_reason=r["failureReason"],
                warnings=r["warnings"],
                will_update_existing_id=r["willUpdateExistingId"],
            )
        )

    session.add(
        AuditEvent(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            event_type="reference_library_bulk_validate",
            scope="reference_library",
            title=f"batch {batch.id}",
        )
    )
    await session.commit()

    ready = sum(1 for r in validated if r["status"] == "ready")
    skipped = sum(1 for r in validated if r["status"] == "skipped")
    errors = sum(1 for r in validated if r["status"] == "error")
    warnings = sum(1 for r in validated if r["warnings"])

    return {
        "batchId": batch.id,
        "totalRows": len(validated),
        "readyCount": ready,
        "skippedCount": skipped,
        "errorCount": errors,
        "warningCount": warnings,
        "rows": validated,
    }


@router.post("/{batch_id}/run")
async def run_import(
    batch_id: int,
    background_tasks: BackgroundTasks,
    context: RequestContext = Depends(require_role(Role.VIEWER)),
    session=Depends(get_db),
) -> dict:
    if not can_write_industry(context):
        raise HTTPException(status_code=403, detail="Industry import requires platform staff")
    batch = await session.get(ReferenceLibraryImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch.status == "running":
        raise HTTPException(status_code=409, detail="Batch already running")

    session.add(
        AuditEvent(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            event_type="reference_library_bulk_started",
            scope="reference_library",
            title=f"batch {batch_id}",
        )
    )
    await session.commit()

    background_tasks.add_task(bulk.run_batch, batch_id, retry_only=False)
    return {"status": "running", "batchId": batch_id}


@router.post("/{batch_id}/retry")
async def retry_import(
    batch_id: int,
    background_tasks: BackgroundTasks,
    context: RequestContext = Depends(require_role(Role.VIEWER)),
    session=Depends(get_db),
) -> dict:
    if not can_write_industry(context):
        raise HTTPException(status_code=403, detail="Industry import requires platform staff")
    batch = await session.get(ReferenceLibraryImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch.status == "running":
        raise HTTPException(status_code=409, detail="Batch already running")
    background_tasks.add_task(bulk.run_batch, batch_id, retry_only=True)
    return {"status": "running", "batchId": batch_id, "retry": True}


@router.get("/{batch_id}")
async def get_batch(
    batch_id: int,
    context: RequestContext = Depends(require_role(Role.VIEWER)),
    session=Depends(get_db),
) -> dict:
    batch = await session.get(ReferenceLibraryImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch.tenant_id != context.tenant_id:
        raise HTTPException(status_code=403, detail="Not your batch")
    rows = (
        await session.scalars(
            select(ReferenceLibraryImportRow)
            .where(ReferenceLibraryImportRow.batch_id == batch_id)
            .order_by(ReferenceLibraryImportRow.row_number)
        )
    ).all()
    return {"batch": batch.to_dict(), "rows": [r.to_dict() for r in rows]}


@router.get("/{batch_id}/failures.csv")
async def download_failures(
    batch_id: int,
    context: RequestContext = Depends(require_role(Role.VIEWER)),
    session=Depends(get_db),
) -> PlainTextResponse:
    batch = await session.get(ReferenceLibraryImportBatch, batch_id)
    if batch is None or batch.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Batch not found")
    rows = (
        await session.scalars(
            select(ReferenceLibraryImportRow)
            .where(ReferenceLibraryImportRow.batch_id == batch_id)
            .order_by(ReferenceLibraryImportRow.row_number)
        )
    ).all()
    csv_text = bulk.failures_csv(rows)
    return PlainTextResponse(
        csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=batch-{batch_id}-failures.csv"
        },
    )


@router.get("/{batch_id}/stream")
async def stream_progress(
    batch_id: int,
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> StreamingResponse:
    """SSE stream of per-row progress by polling the DB until the batch completes."""

    async def event_stream() -> AsyncIterator[str]:
        async with SessionLocal() as session:
            batch = await session.get(ReferenceLibraryImportBatch, batch_id)
            if batch is None or batch.tenant_id != context.tenant_id:
                yield _sse({"type": "error", "message": "Batch not found"})
                return

        last_status: dict[int, str] = {}
        terminal = {"complete", "complete_with_errors"}
        for _ in range(3600):  # hard cap ~1hr at 1s poll
            async with SessionLocal() as session:
                batch = await session.get(ReferenceLibraryImportBatch, batch_id)
                rows = (
                    await session.scalars(
                        select(ReferenceLibraryImportRow)
                        .where(ReferenceLibraryImportRow.batch_id == batch_id)
                        .order_by(ReferenceLibraryImportRow.row_number)
                    )
                ).all()

            for r in rows:
                if last_status.get(r.id) != r.status:
                    last_status[r.id] = r.status
                    yield _sse(
                        {
                            "type": "row_update",
                            "rowId": r.id,
                            "rowNumber": r.row_number,
                            "title": r.title,
                            "status": r.status,
                            "failureReason": r.failure_reason,
                        }
                    )

            if batch is not None and batch.status in terminal:
                yield _sse(
                    {
                        "type": "batch_complete",
                        "status": batch.status,
                        "succeededCount": batch.succeeded_count,
                        "failedCount": batch.failed_count,
                        "skippedCount": batch.skipped_count,
                    }
                )
                return
            await asyncio.sleep(1.0)

        yield _sse({"type": "timeout"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
