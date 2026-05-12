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
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models.shared_vdb import SharedVDB
from app.models.user_vdb import UserVDB
from app.services.vdb_management import VDBManagementService

logger = logging.getLogger(__name__)


def _redis_settings() -> RedisSettings:
    settings = get_settings()
    return RedisSettings.from_dsn(settings.redis_url)


async def enqueue_process_upload(
    *,
    tenant_id: int,
    user_id: int,
    path: str,
    is_shared: bool = False,
) -> str:
    """Enqueue `process_upload` and return the job id."""
    pool = await create_pool(_redis_settings())
    try:
        job = await pool.enqueue_job(
            "process_upload",
            tenant_id=tenant_id,
            user_id=user_id,
            path=path,
            is_shared=is_shared,
        )
        return job.job_id if job else ""
    finally:
        await pool.close()


async def _resolve_vdb_id(*, tenant_id: int, user_id: int, is_shared: bool) -> str | None:
    """Look up the appropriate VDB id for the upload target."""
    async with SessionLocal() as session:
        if is_shared:
            shared_stmt = select(SharedVDB).where(SharedVDB.tenant_id == tenant_id)
            shared = (await session.execute(shared_stmt)).scalar_one_or_none()
            return shared.vdb_id if shared else None
        user_stmt = select(UserVDB).where(
            UserVDB.tenant_id == tenant_id,
            UserVDB.user_id == user_id,
        )
        user_vdb = (await session.execute(user_stmt)).scalar_one_or_none()
        return user_vdb.vdb_id if user_vdb else None


async def process_upload(
    ctx: dict[str, Any],
    *,
    tenant_id: int,
    user_id: int,
    path: str,
    is_shared: bool = False,
) -> dict[str, Any]:
    """Parse upload → request VDB redeploy from servlet → schedule indexing.

    The Java Teiid servlet owns DDL generation and VDB XML updates because it
    has direct access to the WildFly admin API and the filesystem layout used
    by Teiid's "file" translator. The platform API contribution is:

      * locating the correct VDB for the (tenant, user, is_shared) tuple,
      * asking the servlet to redeploy that VDB so the new file is picked up,
      * scheduling a follow-up indexing job for AI/search.
    """
    logger.info(
        "process_upload tenant=%s user=%s path=%s is_shared=%s",
        tenant_id,
        user_id,
        path,
        is_shared,
    )

    vdb_id = await _resolve_vdb_id(
        tenant_id=tenant_id, user_id=user_id, is_shared=is_shared
    )
    if vdb_id is None:
        logger.warning(
            "process_upload: no VDB found for tenant=%s user=%s is_shared=%s",
            tenant_id,
            user_id,
            is_shared,
        )
        return {
            "status": "skipped",
            "reason": "no_vdb",
            "path": path,
            "tenant_id": tenant_id,
            "user_id": user_id,
        }

    teiid = VDBManagementService()
    try:
        await teiid.redeploy_vdb(vdb_id=vdb_id)
        pool = await create_pool(_redis_settings())
        try:
            await pool.enqueue_job(
                "index_for_search",
                tenant_id=tenant_id,
                vdb_id=vdb_id,
                path=path,
            )
        finally:
            await pool.close()
        return {
            "status": "redeployed",
            "vdb_id": vdb_id,
            "path": path,
            "tenant_id": tenant_id,
            "user_id": user_id,
        }
    finally:
        await teiid.aclose()


async def index_for_search(
    ctx: dict[str, Any],
    *,
    tenant_id: int,
    vdb_id: str,
    path: str,
) -> dict[str, Any]:
    """Generate embeddings for the uploaded file (stub).

    Wire this to your embedding provider — the heavy lifting belongs in a
    dedicated worker pool, not the request path.
    """
    logger.info(
        "index_for_search tenant=%s vdb=%s path=%s", tenant_id, vdb_id, path
    )
    return {"status": "ok", "tenant_id": tenant_id, "vdb_id": vdb_id, "path": path}


class WorkerSettings:
    """arq worker entrypoint."""

    redis_settings: ClassVar[RedisSettings] = _redis_settings()
    functions: ClassVar[list] = [process_upload, index_for_search]
    job_timeout: ClassVar[int] = 600
