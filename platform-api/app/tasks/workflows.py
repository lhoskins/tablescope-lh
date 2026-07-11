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

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar

from arq import create_pool
from arq.connections import RedisSettings
from arq.worker import Retry
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models.shared_vdb import SharedVDB
from app.models.user_vdb import UserVDB
from app.services.vdb_management import VDBManagementService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.project import Project
    from app.security.context import RequestContext

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


async def enqueue_sync_saas_object(
    *, saas_source_id: int, limit: int | None = None
) -> str:
    """Enqueue a SaaS object sync and return the job id."""
    pool = await create_pool(_redis_settings())
    try:
        job = await pool.enqueue_job(
            "sync_saas_object", saas_source_id=saas_source_id, limit=limit
        )
        return job.job_id if job else ""
    finally:
        await pool.close()


async def sync_saas_object(
    ctx: dict[str, Any],
    *,
    saas_source_id: int,
    limit: int | None = None,
) -> dict[str, Any]:
    """Sync a SaaS object (HubSpot/Salesforce) into its Postgres staging table."""
    from app.services.saas_source_service import run_sync

    async with SessionLocal() as session:
        try:
            result = await run_sync(
                session, saas_source_id=saas_source_id, limit=limit
            )
        except Exception as exc:
            logger.warning(
                "sync_saas_object failed for source %s: %s", saas_source_id, exc
            )
            return {"status": "error", "saas_source_id": saas_source_id}
    return {"status": "ok", "saas_source_id": saas_source_id, **result}


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


# ─────────────────────────────────────────────────────────────────────────────
# Home / Business Insight — durable per-project analysis
# ─────────────────────────────────────────────────────────────────────────────

async def enqueue_analyze_project_intelligence(
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
    granularity: int,
    run_id: str,
) -> str:
    """Enqueue one project's Home-intelligence analysis; return the job id."""
    pool = await create_pool(_redis_settings())
    try:
        job = await pool.enqueue_job(
            "analyze_project_intelligence",
            tenant_id=tenant_id,
            user_id=user_id,
            project_id=project_id,
            granularity=granularity,
            run_id=run_id,
        )
        return job.job_id if job else ""
    finally:
        await pool.close()


def _worker_context(tenant_id: int, user_id: int):
    """A minimal authenticated context for worker-side project analysis."""
    from app.auth.context import RequestContext
    from app.auth.jwt import TokenClaims

    return RequestContext(
        claims=TokenClaims(
            sub=str(user_id),
            tenant_id=tenant_id,
            user_id=user_id,
            role="admin",
        )
    )


async def _finalize_run_if_complete(run_id: str) -> None:
    """When every project has reported, run synthesis + persist the snapshot.

    Exactly-once across workers via a Redis set-once marker, so the snapshot is
    written even if the client's SSE connection dropped — coverage is bounded
    by drain time, not by the stream staying open.
    """
    from app.routes import home_intelligence as hir
    from app.services import home_intel_queue as q
    from app.services import home_intelligence as hi

    if not await q.is_complete(run_id):
        return
    if not await q.try_claim_finalize(run_id):
        return  # another worker is finalizing this run

    meta = await q.get_meta(run_id)
    if meta is None:  # pragma: no cover - run metadata expired
        return
    results = await q.get_results(run_id)

    successful = [r for r in results.values() if "insights" in r]
    failed = [r for r in results.values() if "insights" not in r]
    summaries = [
        {
            "projectId": r["projectId"],
            "projectName": r.get("projectName", ""),
            "insightSummaries": [
                c.get("summary", "") for c in r.get("insights", [])
            ],
        }
        for r in successful
    ]
    synthesis = (
        hi.synthesise_cross_project(summaries) if meta["cross_project"] else None
    )

    context = _worker_context(meta["tenant_id"], meta["user_id"])
    payload = {
        "projects": meta["projects"],
        "results": successful,
        "synthesis": synthesis,
        "generatedAt": datetime.now(UTC).isoformat(),
    }
    try:
        await hir._save_snapshot(
            context,
            meta["granularity"],
            payload,
            failed_project_count=len(failed),
        )
    except Exception as exc:  # pragma: no cover - snapshot best-effort
        logger.warning("home-intel snapshot persist failed for run %s: %s", run_id, exc)

    # Publish the synthesis last: it is the SSE consumer's completion signal.
    await q.store_synthesis(run_id, synthesis)


async def analyze_project_intelligence(
    ctx: dict[str, Any],
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
    granularity: int,
    run_id: str,
) -> dict[str, Any]:
    """Analyse one project for a Home-intelligence run (durable, retryable).

    Runs the exact same ``_run_for_project`` call the reliable single-project
    path uses. AI-capacity contention (gate 503 / timeout) is mapped onto arq's
    ``Retry`` so the project is deferred and re-enqueued rather than dropped;
    genuine errors write a terminal ``project_error`` result and are not
    retried. A per-tenant token bounds how many of one tenant's projects run at
    once so a busy tenant cannot starve others.
    """
    from app.models.project import Project
    from app.routes import home_intelligence as hir
    from app.services import home_intel_queue as q
    from app.services import home_intelligence as hi
    from app.services.ai_intelligence_client import AIUnavailableError

    settings = get_settings()
    cap = max(1, settings.home_intelligence_max_concurrent_projects_per_tenant)
    job_try = int(ctx.get("job_try", 1) or 1)
    max_tries = max(1, settings.home_intelligence_job_max_tries)

    async def _record_and_finalize(result: dict[str, Any]) -> dict[str, Any]:
        await q.write_result(run_id, project_id, result)
        await _finalize_run_if_complete(run_id)
        return result

    async def _floor_or_error(
        session: AsyncSession,
        context: RequestContext,
        project: Project,
        error: str,
    ) -> dict[str, Any]:
        """Deterministic floor before a terminal error result.

        The suite needs no AI server, so a saturated/down AI still yields
        grounded cards (marked ``degraded``) instead of 0 insights. Only when
        even the floor is empty do we record the bare error.
        """
        floor = await hir.run_deterministic_for_project(session, context, project)
        if floor:
            return await _record_and_finalize(
                {
                    "projectId": str(project.id),
                    "projectName": project.name,
                    "projectColor": hi.project_color(project.id),
                    "insights": floor,
                    "degraded": "ai_unavailable",
                }
            )
        return await _record_and_finalize(
            {
                "projectId": str(project.id),
                "projectName": project.name,
                "error": error,
            }
        )

    # A newer run for the same user (e.g. a page reload) supersedes this one:
    # exit immediately without taking a slot or retrying so abandoned runs
    # cannot pile up and starve the tenant's live run. No result is written —
    # the stale run's Redis keys simply TTL out.
    if not await q.is_current_run(tenant_id, user_id, run_id):
        logger.info(
            "home-intel skipping superseded run %s project %s", run_id, project_id
        )
        return {"superseded": True}

    # Per-tenant fairness: if the tenant is at its cap, defer so another
    # tenant's work can proceed (round-robin-ish). This is retried until the
    # tenant frees a slot; only if the (generous) try budget is exhausted do we
    # write a terminal result so the run can still finalize instead of hanging.
    if not await q.acquire_tenant_slot(tenant_id, cap=cap):
        if job_try < max_tries:
            raise Retry(defer=settings.home_intelligence_tenant_slot_retry_seconds)
        logger.warning(
            "home-intel project %s never acquired a tenant slot within %s tries",
            project_id,
            max_tries,
        )
        async with hir.SessionLocal() as session:
            project = await session.get(Project, project_id)
            if project is None:
                return await _record_and_finalize(
                    {
                        "projectId": str(project_id),
                        "projectName": "",
                        "error": "capacity",
                    }
                )
            context = _worker_context(tenant_id, user_id)
            return await _floor_or_error(session, context, project, "capacity")

    try:
        async with hir.SessionLocal() as session:
            project = await session.get(Project, project_id)
            context = _worker_context(tenant_id, user_id)
            if (
                project is None
                or project.tenant_id != tenant_id
                or not await hir._has_access(session, context, project)
            ):
                # Terminal: no access / gone. Report once, do not retry.
                return await _record_and_finalize(
                    {
                        "projectId": str(project_id),
                        "projectName": project.name if project else "",
                        "error": "no_access",
                    }
                )
            try:
                cards = await asyncio.wait_for(
                    hir._run_for_project(
                        session,
                        context,
                        project,
                        hi.ALL_PROMPT_TYPES,
                        granularity=granularity,
                    ),
                    timeout=settings.home_intelligence_project_analysis_timeout_seconds,
                )
            except TimeoutError:
                # Deliberate self-timeout: record a terminal result so the run
                # finalizes and the UI clears "Analyzing", rather than letting
                # arq's job_timeout cancel the job with no result written.
                logger.warning(
                    "home-intel project %s exceeded analysis deadline (%ss)",
                    project_id,
                    settings.home_intelligence_project_analysis_timeout_seconds,
                )
                return await _floor_or_error(
                    session, context, project, "analysis timed out"
                )
            except AIUnavailableError as exc:
                if exc.retryable and job_try < max_tries:
                    defer = (
                        exc.retry_after
                        if exc.retry_after is not None
                        else settings.home_intelligence_busy_retry_seconds
                    )
                    raise Retry(defer=defer) from exc
                if exc.retryable:
                    # Retries exhausted — try the deterministic floor (no AI
                    # server needed) before recording a terminal error so the
                    # run completes with grounded cards instead of 0 insights.
                    logger.warning(
                        "home-intel project %s exhausted retries: %s",
                        project_id,
                        exc,
                    )
                    return await _floor_or_error(
                        session, context, project, str(exc)
                    )
                # Non-retryable AI failure — terminal.
                return await _record_and_finalize(
                    {
                        "projectId": str(project_id),
                        "projectName": project.name,
                        "error": str(exc),
                    }
                )
            except Exception as exc:
                logger.warning(
                    "home-intel project %s failed terminally: %s", project_id, exc
                )
                return await _floor_or_error(
                    session, context, project, str(exc)
                )

            return await _record_and_finalize(
                {
                    "projectId": str(project.id),
                    "projectName": project.name,
                    "projectColor": hi.project_color(project.id),
                    "insights": cards,
                }
            )
    finally:
        await q.release_tenant_slot(tenant_id)


class WorkerSettings:
    """arq worker entrypoint."""

    redis_settings: ClassVar[RedisSettings] = _redis_settings()
    functions: ClassVar[list] = [
        process_upload,
        index_for_search,
        sync_saas_object,
        analyze_project_intelligence,
    ]
    # Must exceed home_intelligence_project_analysis_timeout_seconds: a job
    # killed by arq writes no result and permanently stalls its run, so the
    # in-job self-timeout must always fire first.
    job_timeout: ClassVar[int] = get_settings().home_intelligence_job_timeout_seconds
    # Retry AI-capacity contention generously so a project defers rather than
    # drops; genuine errors are recorded terminally and never reach this.
    max_tries: ClassVar[int] = get_settings().home_intelligence_job_max_tries
