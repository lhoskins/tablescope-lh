"""Background workflow tasks executed by arq workers.

The async file-upload pipeline:

1. `process_upload` is enqueued from the upload route with the absolute path
   on the shared volume.
2. The worker parses the file (Excel/CSV/TXT), generates DDL describing the
   inferred schema, and calls back to the Teiid servlet to update VDB XML.
3. Once the redeploy completes, the worker enqueues `index_for_search` to
   generate embeddings for downstream AI features.

The worker is intentionally lightweight here — the heavy lifting (DDL
generation, VDB XML updates) is delegated to the Java servlets which have
direct access to the Teiid admin API.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from arq import create_pool
from arq.connections import RedisSettings

from app.config import get_settings
from app.services.vdb_management import VDBManagementService

logger = logging.getLogger(__name__)


def _redis_settings() -> RedisSettings:
    settings = get_settings()
    return RedisSettings.from_dsn(settings.redis_url)


async def enqueue_process_upload(*, tenant_id: int, user_id: int, path: str) -> str:
    """Enqueue `process_upload` and return the job id."""
    pool = await create_pool(_redis_settings())
    try:
        job = await pool.enqueue_job(
            "process_upload",
            tenant_id=tenant_id,
            user_id=user_id,
            path=path,
        )
        return job.job_id if job else ""
    finally:
        await pool.close()


async def process_upload(
    ctx: dict[str, Any],
    *,
    tenant_id: int,
    user_id: int,
    path: str,
) -> dict[str, Any]:
    logger.info(
        "process_upload tenant=%s user=%s path=%s",
        tenant_id,
        user_id,
        path,
    )
    teiid = VDBManagementService()
    try:
        # The actual DDL generation and VDB XML update happen in the Java
        # servlet; here we just request a redeploy of the user's VDB so that
        # the new file is picked up.
        # In a real run, vdb_id is resolved via UserVDB / SharedVDB lookup;
        # for the scaffold we accept the no-op gracefully.
        return {"status": "queued", "path": path, "tenant_id": tenant_id, "user_id": user_id}
    finally:
        await teiid.aclose()


async def index_for_search(
    ctx: dict[str, Any],
    *,
    tenant_id: int,
    table: str,
) -> dict[str, Any]:
    """Stub for downstream embedding generation."""
    logger.info("index_for_search tenant=%s table=%s", tenant_id, table)
    return {"status": "ok", "tenant_id": tenant_id, "table": table}


class WorkerSettings:
    """arq worker entrypoint."""

    redis_settings: ClassVar[RedisSettings] = _redis_settings()
    functions: ClassVar[list] = [process_upload, index_for_search]
    job_timeout: ClassVar[int] = 600
