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
import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar

from arq import create_pool, cron
from arq.connections import RedisSettings
from arq.worker import Retry
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


async def enqueue_scan_repository_connection(
    *,
    tenant_id: int,
    connection_id: int,
    scan_id: int,
) -> str:
    """Enqueue a repository scan and return the job id."""
    pool = await create_pool(_redis_settings())
    try:
        job = await pool.enqueue_job(
            "scan_repository_connection",
            tenant_id=tenant_id,
            connection_id=connection_id,
            scan_id=scan_id,
        )
        return job.job_id if job else ""
    finally:
        await pool.close()


async def scan_repository_connection(
    ctx: dict[str, Any],
    *,
    tenant_id: int,
    connection_id: int,
    scan_id: int,
) -> dict[str, Any]:
    """Run a repository scan through the connector abstraction."""
    from app.services.repository_scanner import RepositoryScanner

    async with SessionLocal() as session:
        scanner = RepositoryScanner(session)
        try:
            await scanner.scan(tenant_id, connection_id, scan_id)
            return {
                "status": "ok",
                "tenant_id": tenant_id,
                "connection_id": connection_id,
                "scan_id": scan_id,
            }
        except Exception as exc:
            logger.warning(
                "scan_repository_connection failed for scan %s: %s", scan_id, exc
            )
            return {
                "status": "error",
                "tenant_id": tenant_id,
                "connection_id": connection_id,
                "scan_id": scan_id,
                "error": str(exc)[:500],
            }


async def enqueue_rebuild_knowledge_graph(build_id: int) -> str:
    """Enqueue a knowledge graph rebuild and return the job id."""
    pool = await create_pool(_redis_settings())
    try:
        job = await pool.enqueue_job("rebuild_knowledge_graph", build_id)
        return job.job_id if job else ""
    finally:
        await pool.close()


async def enqueue_run_knowledge_graph_health_check(project_id: int) -> str:
    """Enqueue a knowledge graph health check and return the job id."""
    pool = await create_pool(_redis_settings())
    try:
        job = await pool.enqueue_job(
            "run_knowledge_graph_health_check", project_id
        )
        return job.job_id if job else ""
    finally:
        await pool.close()


async def rebuild_knowledge_graph(ctx: dict[str, Any], build_id: int) -> dict[str, Any]:
    """Execute a knowledge graph build (full or incremental) in the worker."""
    from app.models import KnowledgeGraphBuild
    from app.services.knowledge_graph_lifecycle import KnowledgeGraphLifecycleManager

    async with SessionLocal() as session:
        lifecycle = KnowledgeGraphLifecycleManager(session)
        try:
            build = await session.get(KnowledgeGraphBuild, build_id)
            if build is None:
                return {"status": "error", "error": "build_not_found"}

            worker_id = ctx.get("job_id") or str(uuid.uuid4())
            build.worker_id = worker_id
            await session.flush()

            if build.build_type == "incremental":
                await lifecycle.run_incremental_rebuild(build_id)
            else:
                await lifecycle.run_full_rebuild(build_id)
            await session.commit()
            return {"status": "ok", "build_id": build_id}
        except Exception as exc:
            logger.exception("rebuild_knowledge_graph failed for build %s", build_id)
            await session.rollback()
            return {"status": "error", "error": str(exc)[:500]}


async def run_knowledge_graph_health_check(
    ctx: dict[str, Any], project_id: int
) -> dict[str, Any]:
    """Run a knowledge graph health check for one project."""
    from app.services.knowledge_graph_health import KnowledgeGraphHealthService

    async with SessionLocal() as session:
        health = KnowledgeGraphHealthService(session)
        try:
            hc = await health.run_health_check(project_id, check_type="scheduled")
            await session.commit()
            return {
                "status": "ok",
                "project_id": project_id,
                "health_status": hc.status,
            }
        except Exception as exc:
            logger.exception(
                "run_knowledge_graph_health_check failed for project %s", project_id
            )
            await session.rollback()
            return {"status": "error", "project_id": project_id, "error": str(exc)[:500]}


async def recover_stale_graph_builds(ctx: dict[str, Any]) -> dict[str, Any]:
    """Recover knowledge graph builds with expired heartbeats."""
    from app.services.knowledge_graph_lifecycle import KnowledgeGraphLifecycleManager

    async with SessionLocal() as session:
        lifecycle = KnowledgeGraphLifecycleManager(session)
        try:
            recovered = await lifecycle.recover_stale_builds()
            await session.commit()
            return {"status": "ok", "recovered_build_ids": recovered}
        except Exception as exc:
            logger.exception("recover_stale_graph_builds failed")
            await session.rollback()
            return {"status": "error", "error": str(exc)[:500]}


async def evaluate_stale_graphs(ctx: dict[str, Any]) -> dict[str, Any]:
    """Mark graphs whose source fingerprint drifted as stale."""
    from app.services.knowledge_graph_lifecycle import KnowledgeGraphLifecycleManager

    async with SessionLocal() as session:
        lifecycle = KnowledgeGraphLifecycleManager(session)
        try:
            marked = await lifecycle.evaluate_stale_graphs()
            await session.commit()
            return {"status": "ok", "marked_project_ids": marked}
        except Exception as exc:
            logger.exception("evaluate_stale_graphs failed")
            await session.rollback()
            return {"status": "error", "error": str(exc)[:500]}


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
            return await _record_and_finalize(
                {
                    "projectId": str(project_id),
                    "projectName": project.name if project else "",
                    "error": "capacity",
                }
            )

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
                return await _record_and_finalize(
                    {
                        "projectId": str(project_id),
                        "projectName": project.name,
                        "error": "analysis timed out",
                    }
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
                    # Retries exhausted — record terminal so the run can
                    # complete instead of hanging forever.
                    logger.warning(
                        "home-intel project %s exhausted retries: %s",
                        project_id,
                        exc,
                    )
                    return await _record_and_finalize(
                        {
                            "projectId": str(project_id),
                            "projectName": project.name,
                            "error": str(exc),
                        }
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
                return await _record_and_finalize(
                    {
                        "projectId": str(project_id),
                        "projectName": project.name,
                        "error": str(exc),
                    }
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
        scan_repository_connection,
        rebuild_knowledge_graph,
        run_knowledge_graph_health_check,
        recover_stale_graph_builds,
        evaluate_stale_graphs,
    ]
    cron_jobs: ClassVar[list] = [
        # Detect source drift every 15 minutes and mark affected graphs stale.
        cron(evaluate_stale_graphs, minute=0, second=30),
        cron(evaluate_stale_graphs, minute=15, second=30),
        cron(evaluate_stale_graphs, minute=30, second=30),
        cron(evaluate_stale_graphs, minute=45, second=30),
        # Recover builds stuck without a heartbeat.
        cron(recover_stale_graph_builds, minute=5, second=0),
    ]
    # Must exceed home_intelligence_project_analysis_timeout_seconds: a job
    # killed by arq writes no result and permanently stalls its run, so the
    # in-job self-timeout must always fire first.
    job_timeout: ClassVar[int] = get_settings().home_intelligence_job_timeout_seconds
    # Retry AI-capacity contention generously so a project defers rather than
    # drops; genuine errors are recorded terminally and never reach this.
    max_tries: ClassVar[int] = get_settings().home_intelligence_job_max_tries
