
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.file_import_job import FileImportJob
from app.models.file_source_meta import FileSourceMeta

from .staging import discard_quarantine

# ── Job lookup and lifecycle ─────────────────────────────────────────────


async def get_job_for_user(
    session: AsyncSession, job_id: str, *, tenant_id: int, user_id: int
) -> FileImportJob | None:
    """Tenant- and requester-scoped lookup. Every route must use this."""
    return await session.scalar(
        select(FileImportJob).where(
            FileImportJob.id == job_id,
            FileImportJob.tenant_id == tenant_id,
            FileImportJob.requested_by == user_id,
        )
    )


def apply_provenance(meta: FileSourceMeta, job: FileImportJob) -> None:
    """Copy a job's safe provenance onto the finalized data-source record."""
    meta.acquisition_method = job.method
    meta.import_job_id = job.id
    meta.source_host = job.source_host
    meta.source_locator_redacted = job.source_locator_redacted
    meta.network_connection_id = job.network_connection_id
    meta.content_sha256 = job.sha256
    meta.remote_etag = job.remote_etag
    meta.remote_last_modified = job.remote_last_modified
    meta.retrieved_at = job.retrieved_at


async def cleanup_expired_jobs(session: AsyncSession, *, limit: int = 200) -> int:
    """Expire abandoned jobs and delete their quarantined bytes."""
    now = datetime.now(UTC)
    stale = (
        await session.scalars(
            select(FileImportJob)
            .where(
                FileImportJob.expires_at.is_not(None),
                FileImportJob.expires_at < now,
                FileImportJob.status.not_in(
                    ("completed", "failed", "cancelled", "expired")
                ),
            )
            .limit(limit)
        )
    ).all()
    for job in stale:
        discard_quarantine(job)
        job.status = "expired"
    if stale:
        await session.commit()
    return len(stale)
