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
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

from arq import create_pool, cron
from arq.connections import RedisSettings
from arq.worker import Retry
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models.business_insight_result import BusinessInsightResult
from app.models.project_intelligence_snapshot import ProjectIntelligenceSnapshot
from app.models.shared_vdb import SharedVDB
from app.models.user_vdb import UserVDB
from app.services.vdb_management import VDBManagementService
from app.tasks.kpi_source_matching import match_kpi_data_source
from app.tasks.llm_framework import (
    convert_fp16_to_gguf,
    deploy_llm_artifact,
    reindex_embedding_model,
    stage_llm_artifact,
)

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
    """Enqueue a knowledge graph rebuild and return the job id.

    The deterministic job id makes enqueueing idempotent per build: event
    triggers that coalesce onto an already-queued build re-enqueue the same id
    and arq drops the duplicate instead of running the build twice.
    """
    pool = await create_pool(_redis_settings())
    try:
        job = await pool.enqueue_job(
            "rebuild_knowledge_graph", build_id, _job_id=f"kg-build:{build_id}"
        )
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

            # Downstream consumers: a successful (activated) build means the
            # project's data view changed, so warm the shared Business Insight
            # cache. Best-effort — the graph build result stands regardless.
            try:
                await session.refresh(build)
                if (
                    build.status == "succeeded"
                    and get_settings().business_insight_event_refresh_enabled
                ):
                    await enqueue_refresh_business_insight_result(
                        tenant_id=build.tenant_id, project_id=build.project_id
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to enqueue business insight refresh after build %s: %s",
                    build_id,
                    exc,
                )

            # Sibling consumer: Project Insight snapshots become stale whenever
            # the KG view changes, so mark them and queue a debounced rebuild.
            try:
                await session.refresh(build)
                if build.status == "succeeded":
                    from app.services.project_insight_service import (
                        mark_project_insight_stale,
                    )

                    await mark_project_insight_stale(
                        session,
                        tenant_id=build.tenant_id,
                        project_id=build.project_id,
                    )
                    await session.commit()
                    if get_settings().project_insight_event_rebuild_enabled:
                        await enqueue_rebuild_project_insight(
                            tenant_id=build.tenant_id,
                            project_id=build.project_id,
                        )
            except Exception as exc:
                logger.warning(
                    "Failed to enqueue project insight rebuild after build %s: %s",
                    build_id,
                    exc,
                )
            return {"status": "ok", "build_id": build_id}
        except Exception as exc:
            logger.exception("rebuild_knowledge_graph failed for build %s", build_id)
            await session.rollback()
            return {"status": "error", "error": str(exc)[:500]}


# Deterministic job id may be reused; don't keep results so re-enqueue works.
rebuild_knowledge_graph.keep_result = 0  # type: ignore[attr-defined]


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
    """Mark graphs whose source fingerprint drifted as stale, then rebuild them.

    Staleness detection alone leaves a graph stale until a user manually hits
    rebuild; queueing the rebuild here closes the loop so drifted graphs heal
    without user intervention. Each project is attributed to its owner so AI
    enrichment still runs in this userless context.
    """
    from app.services.knowledge_graph_lifecycle import KnowledgeGraphLifecycleManager

    async with SessionLocal() as session:
        lifecycle = KnowledgeGraphLifecycleManager(session)
        try:
            marked = await lifecycle.evaluate_stale_graphs()
            await session.commit()
        except Exception as exc:
            logger.exception("evaluate_stale_graphs failed")
            await session.rollback()
            return {"status": "error", "error": str(exc)[:500]}

        enqueued: list[int] = []
        for project_id in marked:
            try:
                requested_by = await lifecycle.resolve_representative_user(project_id)
                build, _ = await lifecycle.request_full_rebuild(
                    project_id, trigger="source_drift", requested_by=requested_by
                )
                await session.commit()
                await enqueue_rebuild_knowledge_graph(build.id)
                enqueued.append(build.id)
            except Exception as exc:
                # Fail-open per project: one broken project must not block the
                # rest of the fleet from healing.
                logger.warning(
                    "Auto-rebuild for stale graph project %s failed: %s",
                    project_id,
                    exc,
                )
                await session.rollback()
        return {
            "status": "ok",
            "marked_project_ids": marked,
            "enqueued_build_ids": enqueued,
        }


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
    from app.models.database_data_source import DatabaseDataSource
    from app.models.saas_object_data_source import SaasObjectDataSource
    from app.services.knowledge_graph_lifecycle import request_event_driven_rebuild
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

        # Synced data changed the project's sources; refresh its knowledge
        # graph. The staging rows are committed by run_sync, so the rebuild
        # observes them (producer-before-consumer ordering). Best-effort: the
        # helper never raises.
        try:
            saas = await session.get(SaasObjectDataSource, saas_source_id)
            data_source = (
                await session.get(DatabaseDataSource, saas.database_data_source_id)
                if saas
                else None
            )
        except Exception:
            data_source = None
        if data_source is not None and data_source.project_id is not None:
            await request_event_driven_rebuild(
                session,
                project_id=data_source.project_id,
                change_set=[
                    {
                        "entity_type": "data_source",
                        "entity_id": data_source.id,
                        "action": "synced",
                        "change_scope": "content",
                    }
                ],
                trigger="saas_sync",
            )
    return {"status": "ok", "saas_source_id": saas_source_id, **result}


async def enqueue_reprocess_project(
    *,
    tenant_id: int,
    project_id: int,
    user_id: int,
    force: bool = False,
) -> str:
    """Enqueue a project-wide document reprocess + graph rebuild cascade.

    The deterministic per-project job id coalesces rapid repeat triggers: while
    one cascade is queued/running for a project, further enqueues are dropped
    by arq instead of stacking duplicate full-project reprocesses.
    """
    pool = await create_pool(_redis_settings())
    try:
        job = await pool.enqueue_job(
            "reprocess_project",
            tenant_id=tenant_id,
            project_id=project_id,
            user_id=user_id,
            force=force,
            _job_id=f"reprocess:{tenant_id}:{project_id}",
        )
        return job.job_id if job else ""
    finally:
        await pool.close()


REPROCESS_DOCUMENT_CONCURRENCY = 2


async def reprocess_project(
    ctx: dict[str, Any],
    *,
    tenant_id: int,
    project_id: int,
    user_id: int,
    force: bool = False,
) -> dict[str, Any]:
    """Reprocess every project document, then rebuild the knowledge graph last.

    Stage order is the correctness constraint: documents (and the relationship/
    family edges their profiles produce) are the graph's upstream producers, so
    the snapshot rebuild must run as the terminal stage or it re-caches stale
    rows. Each document honors the file-hash gate — unchanged files are skipped
    unless ``force`` — and the graph rebuild only runs when something actually
    changed (or on ``force``). Every stage is fail-open: one bad document never
    blocks the rest, and a graph failure never fails the reprocess.
    """
    from app.models.project_asset import ProjectAsset
    from app.services.document_processing_service import process_document_asset
    from app.services.knowledge_graph_lifecycle import request_event_driven_rebuild

    async with SessionLocal() as session:
        asset_ids = (
            await session.scalars(
                select(ProjectAsset.id).where(
                    ProjectAsset.tenant_id == tenant_id,
                    ProjectAsset.project_id == project_id,
                )
            )
        ).all()

    statuses: dict[int, str] = {}
    # Document profiling fans out to the AI server, so bound how many documents
    # run at once. Each document gets its own session: the pipeline commits at
    # every stage and AsyncSession is not safe for concurrent use.
    semaphore = asyncio.Semaphore(REPROCESS_DOCUMENT_CONCURRENCY)

    async def _one(asset_id: int) -> None:
        async with semaphore:
            try:
                async with SessionLocal() as session:
                    asset = await session.get(ProjectAsset, asset_id)
                    if asset is None:
                        statuses[asset_id] = "missing"
                        return
                    statuses[asset_id] = await process_document_asset(
                        session,
                        asset,
                        tenant_id,
                        project_id,
                        user_id,
                        force=force,
                        trigger_graph_rebuild=False,
                    )
            except Exception:
                logger.exception(
                    "reprocess_project: document %s failed for project %s",
                    asset_id,
                    project_id,
                )
                statuses[asset_id] = "error"

    await asyncio.gather(*(_one(aid) for aid in asset_ids))

    changed = [aid for aid, s in statuses.items() if s == "processed"]
    build_id: int | None = None
    if changed or force:
        async with SessionLocal() as session:
            build = await request_event_driven_rebuild(
                session,
                project_id=project_id,
                change_set=[
                    {
                        "entity_type": "document",
                        "entity_id": aid,
                        "action": "reprocessed",
                        "change_scope": "content",
                    }
                    for aid in (changed or asset_ids)
                ],
                trigger="project_reprocess",
                requested_by=user_id,
            )
            build_id = build.id if build else None

    return {
        "status": "ok",
        "tenant_id": tenant_id,
        "project_id": project_id,
        "documents": statuses,
        "changed_count": len(changed),
        "graph_build_id": build_id,
    }


# Deterministic per-project job id is reused across reprocess triggers.
reprocess_project.keep_result = 0  # type: ignore[attr-defined]


# Granularity the event-driven background refresh analyses at — the Home
# stream's default, so warmed results serve the common case.
BUSINESS_INSIGHT_REFRESH_GRANULARITY = 3


async def enqueue_refresh_business_insight_result(
    *, tenant_id: int, project_id: int
) -> str:
    """Enqueue a debounced background refresh of one project's shared cards.

    The deterministic per-project job id plus the defer window coalesce bursts
    (e.g. several KG builds from a multi-file upload) into one analysis.
    """
    pool = await create_pool(_redis_settings())
    try:
        job = await pool.enqueue_job(
            "refresh_business_insight_result",
            tenant_id=tenant_id,
            project_id=project_id,
            _job_id=f"bi-result:{tenant_id}:{project_id}",
            _defer_by=120,
        )
        return job.job_id if job else ""
    finally:
        await pool.close()


async def refresh_business_insight_result(
    ctx: dict[str, Any],
    *,
    tenant_id: int,
    project_id: int,
) -> dict[str, Any]:
    """Re-analyse one project into the shared Business Insight cache.

    Runs after a successful Knowledge Graph build so every user's next Home
    open assembles from warm, current results. Attributed to the project owner
    (the SQL runs as them), gated on recent tenant Home activity so idle
    tenants consume zero AI capacity, and bounded by the same per-tenant
    capacity slots as interactive runs — background refresh can never outspend
    user-facing load.
    """
    from app.models.intelligence_snapshot import IntelligenceSnapshot
    from app.models.project import Project
    from app.routes import home_intelligence as hir
    from app.services import business_insight_cache as bi_cache
    from app.services import home_intel_queue as q
    from app.services import home_intelligence as hi
    from app.services.ai_intelligence_client import AIUnavailableError
    from app.services.knowledge_graph_lifecycle import KnowledgeGraphLifecycleManager

    settings = get_settings()
    if not settings.business_insight_event_refresh_enabled:
        return {"status": "disabled", "project_id": project_id}

    async with SessionLocal() as session:
        # Activity gate: only spend AI on tenants where someone actually uses
        # Home. Snapshot rows are written on every completed run, so their
        # recency is a faithful usage signal.
        cutoff = datetime.now(UTC) - timedelta(
            days=max(0, settings.business_insight_refresh_activity_days)
        )
        recent = await session.scalar(
            select(IntelligenceSnapshot.id)
            .where(
                IntelligenceSnapshot.tenant_id == tenant_id,
                IntelligenceSnapshot.updated_at >= cutoff,
            )
            .limit(1)
        )
        if recent is None:
            return {
                "status": "skipped",
                "reason": "no_recent_activity",
                "project_id": project_id,
            }

        project = await session.get(Project, project_id)
        if project is None or project.tenant_id != tenant_id:
            return {
                "status": "skipped",
                "reason": "project_not_found",
                "project_id": project_id,
            }
        owner_id = await KnowledgeGraphLifecycleManager(
            session
        ).resolve_representative_user(project_id)
        if owner_id is None:
            return {"status": "skipped", "reason": "no_owner", "project_id": project_id}

    job_try = int(ctx.get("job_try", 1) or 1)
    max_tries = max(1, settings.home_intelligence_job_max_tries)
    cap = max(1, settings.home_intelligence_max_concurrent_projects_per_tenant)
    if not await q.acquire_tenant_slot(tenant_id, cap=cap):
        if job_try < max_tries:
            raise Retry(defer=settings.home_intelligence_tenant_slot_retry_seconds)
        return {"status": "skipped", "reason": "capacity", "project_id": project_id}

    try:
        async with SessionLocal() as session:
            project = await session.get(Project, project_id)
            if project is None:
                return {
                    "status": "skipped",
                    "reason": "project_not_found",
                    "project_id": project_id,
                }
            context = _worker_context(tenant_id, owner_id)
            try:
                cards = await asyncio.wait_for(
                    hir._run_for_project(
                        session,
                        context,
                        project,
                        hi.ALL_PROMPT_TYPES,
                        # Audit rows describe user-initiated analysis; a
                        # background cache warm would only add noise.
                        write_audit=False,
                        granularity=BUSINESS_INSIGHT_REFRESH_GRANULARITY,
                    ),
                    timeout=settings.home_intelligence_project_analysis_timeout_seconds,
                )
            except AIUnavailableError as exc:
                if exc.retryable and job_try < max_tries:
                    defer = (
                        exc.retry_after
                        if exc.retry_after is not None
                        else settings.home_intelligence_busy_retry_seconds
                    )
                    raise Retry(defer=defer) from exc
                return {
                    "status": "error",
                    "project_id": project_id,
                    "error": str(exc)[:500],
                }
            except Exception as exc:
                logger.warning(
                    "business insight refresh failed for project %s: %s",
                    project_id,
                    exc,
                )
                return {
                    "status": "error",
                    "project_id": project_id,
                    "error": str(exc)[:500],
                }

            await bi_cache.store_result(
                session,
                tenant_id=tenant_id,
                project_id=project_id,
                granularity=BUSINESS_INSIGHT_REFRESH_GRANULARITY,
                cards=cards,
                built_by=owner_id,
            )
            return {
                "status": "ok",
                "project_id": project_id,
                "card_count": len(cards),
            }
    finally:
        await q.release_tenant_slot(tenant_id)


# Deterministic per-project job id is reused across downstream KG triggers.
refresh_business_insight_result.keep_result = 0  # type: ignore[attr-defined]


# Granularity the event-driven Project Insight rebuild analyses at.
PROJECT_INSIGHT_REBUILD_GRANULARITY = 3


async def enqueue_rebuild_project_insight(
    *, tenant_id: int, project_id: int
) -> str:
    """Enqueue a debounced background rebuild of Project Insight snapshots.

    The deterministic per-project job id plus the defer window coalesce bursts
    (e.g. several KG builds from a multi-file upload) into one rebuild after
    the dust settles.
    """
    pool = await create_pool(_redis_settings())
    try:
        job = await pool.enqueue_job(
            "rebuild_project_insight",
            tenant_id=tenant_id,
            project_id=project_id,
            _job_id=f"project-insight:{tenant_id}:{project_id}",
            _defer_by=60,
        )
        return job.job_id if job else ""
    finally:
        await pool.close()


async def rebuild_project_insight(
    ctx: dict[str, Any], *, tenant_id: int, project_id: int
) -> dict[str, Any]:
    """Rebuild stale Project Insight snapshots for a project.

    Runs after a data change (document, reference-library update, or successful
    Knowledge Graph build). Rebuilds only for users who already have a snapshot
    row, most recently updated first, capped by ``project_insight_max_rebuild_users``.
    Each build runs as the snapshot-owning user so acknowledgement state is
    preserved. Per-user failures are logged and skipped.
    """
    from app.models.project import Project
    from app.models.project_intelligence_snapshot import ProjectIntelligenceSnapshot
    from app.routes import home_intelligence as hir
    from app.services import home_intel_queue as q
    from app.services import project_insight_service as pi
    from app.services.ai_intelligence_client import AIUnavailableError

    settings = get_settings()
    if not settings.project_insight_event_rebuild_enabled:
        return {"status": "disabled", "project_id": project_id}

    job_try = int(ctx.get("job_try", 1) or 1)
    max_tries = max(1, settings.home_intelligence_job_max_tries)
    cap = max(1, settings.home_intelligence_max_concurrent_projects_per_tenant)

    if not await q.acquire_tenant_slot(tenant_id, cap=cap):
        if job_try < max_tries:
            raise Retry(defer=settings.home_intelligence_tenant_slot_retry_seconds)
        return {
            "status": "skipped",
            "reason": "capacity",
            "project_id": project_id,
        }

    try:
        async with SessionLocal() as session:
            # Stale gate: nothing to do if a fresher run already handled it.
            stale_rows = (
                await session.scalars(
                    select(ProjectIntelligenceSnapshot)
                    .where(
                        ProjectIntelligenceSnapshot.tenant_id == tenant_id,
                        ProjectIntelligenceSnapshot.project_id == project_id,
                        ProjectIntelligenceSnapshot.is_stale.is_(True),
                        ProjectIntelligenceSnapshot.suite == "project_insight",
                    )
                    .order_by(ProjectIntelligenceSnapshot.updated_at.desc())
                    .limit(settings.project_insight_max_rebuild_users)
                )
            ).all()
            if not stale_rows:
                return {
                    "status": "skipped",
                    "reason": "not_stale",
                    "project_id": project_id,
                }

            project = await session.get(Project, project_id)
            if project is None or project.tenant_id != tenant_id:
                return {
                    "status": "skipped",
                    "reason": "project_not_found",
                    "project_id": project_id,
                }

            audience = [snap.user_id for snap in stale_rows]
            refreshed = 0
            failed = 0

            for user_id in audience:
                # The project instance can be expired by a previous rollback,
                # so refresh it before each per-user build.
                await session.refresh(project)
                try:
                    context = _worker_context(tenant_id, user_id)
                    runner = hir._make_runner(session, context, project.id)
                    report = await pi.build_project_insight(
                        session,
                        project=project,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        runner=runner,
                    )
                    payload = report.model_dump(mode="json")
                    snap = await session.scalar(
                        select(ProjectIntelligenceSnapshot).where(
                            ProjectIntelligenceSnapshot.tenant_id == tenant_id,
                            ProjectIntelligenceSnapshot.user_id == user_id,
                            ProjectIntelligenceSnapshot.project_id == project_id,
                            ProjectIntelligenceSnapshot.suite == "project_insight",
                        )
                    )
                    if snap is None:
                        snap = ProjectIntelligenceSnapshot(
                            tenant_id=tenant_id,
                            user_id=user_id,
                            project_id=project_id,
                            suite="project_insight",
                        )
                        session.add(snap)
                    snap.payload = payload
                    snap.is_stale = False
                    await session.commit()
                    refreshed += 1
                except AIUnavailableError as exc:
                    await session.rollback()
                    if exc.retryable and job_try < max_tries:
                        defer = (
                            exc.retry_after
                            if exc.retry_after is not None
                            else settings.home_intelligence_busy_retry_seconds
                        )
                        raise Retry(defer=defer) from exc
                    logger.warning(
                        "project insight rebuild failed for project %s user %s: %s",
                        project_id,
                        user_id,
                        exc,
                    )
                    failed += 1
                except Exception as exc:
                    await session.rollback()
                    logger.warning(
                        "project insight rebuild failed for project %s user %s: %s",
                        project_id,
                        user_id,
                        exc,
                    )
                    failed += 1

            return {
                "status": "ok",
                "project_id": project_id,
                "refreshed": refreshed,
                "failed": failed,
            }
    finally:
        await q.release_tenant_slot(tenant_id)


# Deterministic per-project job id is reused across downstream KG triggers.
rebuild_project_insight.keep_result = 0  # type: ignore[attr-defined]


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

            # Shared per-project cache: cards are identical for every user who
            # can open the project (membership is the visibility boundary), so
            # serve them when still keyed to the active KG version. Access was
            # verified above — the cache never widens visibility.
            if settings.business_insight_shared_cache_enabled:
                from app.services import business_insight_cache as bi_cache

                cached_cards = await bi_cache.get_fresh_result(
                    session,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    granularity=granularity,
                )
                if cached_cards is not None:
                    return await _record_and_finalize(
                        {
                            "projectId": str(project.id),
                            "projectName": project.name,
                            "projectColor": hi.project_color(project.id),
                            "insights": cached_cards,
                            "fromCache": True,
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

            if settings.business_insight_shared_cache_enabled:
                from app.services import business_insight_cache as bi_cache

                await bi_cache.store_result(
                    session,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    granularity=granularity,
                    cards=cards,
                    built_by=user_id,
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


async def enqueue_reindex_embedding_model(migration_id: int, requested_by_user_id: int) -> str:
    """Enqueue an embedding re-index migration."""
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    pool = await create_pool(redis_settings)
    try:
        job = await pool.enqueue_job(
            "reindex_embedding_model",
            migration_id=migration_id,
            requested_by_user_id=requested_by_user_id,
        )
        return job.job_id if job else ""
    finally:
        await pool.close()


async def enqueue_convert_fp16_to_gguf(conversion_id: int, requested_by_user_id: int) -> str:
    """Enqueue an FP16 -> GGUF conversion."""
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    pool = await create_pool(redis_settings)
    try:
        job = await pool.enqueue_job(
            "convert_fp16_to_gguf",
            conversion_id=conversion_id,
            requested_by_user_id=requested_by_user_id,
        )
        return job.job_id if job else ""
    finally:
        await pool.close()


async def _configure_worker_logging(ctx: dict[str, Any]) -> None:
    """Configure structured logging for the arq worker."""
    from app.logging_config import configure_logging

    configure_logging(get_settings().log_level)


async def schedule_stale_insight_refresh(ctx: dict[str, Any]) -> dict[str, Any]:
    """Cron entrypoint: enqueue rebuilds/refresh for stale insight snapshots.

    Runs every hour. Project-insight snapshots are rebuilt when they are marked
    stale. Business-insight cache entries are refreshed when older than their TTL
    so the shared cache stays warm for active tenants.
    """
    settings = get_settings()
    cutoff = datetime.now(UTC) - timedelta(
        seconds=settings.business_insight_result_ttl_seconds
    )
    enqueued: dict[str, int] = {"project_insight": 0, "business_insight": 0}

    async with SessionLocal() as session:
        stale_pi_rows = (
            await session.execute(
                select(
                    ProjectIntelligenceSnapshot.tenant_id,
                    ProjectIntelligenceSnapshot.project_id,
                )
                .where(
                    ProjectIntelligenceSnapshot.is_stale.is_(True),
                    ProjectIntelligenceSnapshot.suite == "project_insight",
                )
                .distinct()
            )
        ).all()
        for tenant_id, project_id in stale_pi_rows:
            await enqueue_rebuild_project_insight(
                tenant_id=tenant_id, project_id=project_id
            )
            enqueued["project_insight"] += 1

        stale_bi_rows = (
            await session.execute(
                select(BusinessInsightResult.tenant_id, BusinessInsightResult.project_id)
                .where(BusinessInsightResult.updated_at < cutoff)
                .distinct()
            )
        ).all()
        for tenant_id, project_id in stale_bi_rows:
            await enqueue_refresh_business_insight_result(
                tenant_id=tenant_id, project_id=project_id
            )
            enqueued["business_insight"] += 1

    return {"status": "ok", "enqueued": enqueued}


# Deterministic job id may be reused; don't keep results so re-enqueue works.
schedule_stale_insight_refresh.keep_result = 0  # type: ignore[attr-defined]


class WorkerSettings:
    """arq worker entrypoint."""

    on_startup: ClassVar = _configure_worker_logging
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
        reprocess_project,
        refresh_business_insight_result,
        rebuild_project_insight,
        schedule_stale_insight_refresh,
        match_kpi_data_source,
        stage_llm_artifact,
        deploy_llm_artifact,
        reindex_embedding_model,
        convert_fp16_to_gguf,
    ]
    cron_jobs: ClassVar[list] = [
        # Detect source drift every 15 minutes and mark affected graphs stale.
        cron(evaluate_stale_graphs, minute=0, second=30),
        cron(evaluate_stale_graphs, minute=15, second=30),
        cron(evaluate_stale_graphs, minute=30, second=30),
        cron(evaluate_stale_graphs, minute=45, second=30),
        # Recover builds stuck without a heartbeat.
        cron(recover_stale_graph_builds, minute=5, second=0),
        # Refresh stale insight snapshots every hour.
        cron(schedule_stale_insight_refresh, minute=0, second=0),
    ]
    # Must exceed home_intelligence_project_analysis_timeout_seconds: a job
    # killed by arq writes no result and permanently stalls its run, so the
    # in-job self-timeout must always fire first.
    job_timeout: ClassVar[int] = get_settings().home_intelligence_job_timeout_seconds
    # Retry AI-capacity contention generously so a project defers rather than
    # drops; genuine errors are recorded terminally and never reach this.
    max_tries: ClassVar[int] = get_settings().home_intelligence_job_max_tries
