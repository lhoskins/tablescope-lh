"""FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.auth.mfa_errors import MfaRequiredError, mfa_required_handler
from app.auth.middleware import SESSION_TOKEN_HEADER, AuthMiddleware
from app.config import get_settings
from app.logging_config import configure_logging
from app.observability import mount_metrics, setup_sentry
from app.routes import ai_asset_metadata as ai_asset_metadata_routes
from app.routes import ai_governance as ai_governance_routes
from app.routes import ai_proxy as ai_proxy_routes
from app.routes import ai_reference_catalog as ai_reference_catalog_routes
from app.routes import ai_speech as ai_speech_routes
from app.routes import analytical_methods as analytical_methods_routes
from app.routes import auth as auth_routes
from app.routes import auth_sso as auth_sso_routes
from app.routes import billing as billing_routes
from app.routes import billing_admin as billing_admin_routes
from app.routes import connected_sources as connected_sources_routes
from app.routes import connectors as connectors_routes
from app.routes import (
    conversational_analytics_conversations as conversational_analytics_conversations_routes,
)
from app.routes import conversational_analytics_turns as conversational_analytics_turns_routes
from app.routes import dashboards_crud as dashboards_crud_routes
from app.routes import dashboards_widget_query as dashboards_widget_query_routes
from app.routes import data_source_assignments as data_source_assignments_routes
from app.routes import data_source_catalog as data_source_catalog_routes
from app.routes import database_sources_connection as database_sources_connection_routes
from app.routes import database_sources_lifecycle as database_sources_lifecycle_routes
from app.routes import (
    database_sources_saved_connections as database_sources_saved_connections_routes,
)
from app.routes import document_families_curation as document_families_curation_routes
from app.routes import document_families_reads as document_families_reads_routes
from app.routes import document_families_summary as document_families_summary_routes
from app.routes import enterprise_auth_ldap as enterprise_auth_ldap_routes
from app.routes import enterprise_auth_settings as enterprise_auth_settings_routes
from app.routes import enterprise_auth_sso as enterprise_auth_sso_routes
from app.routes import file_analysis as file_analysis_routes
from app.routes import file_imports as file_imports_routes
from app.routes import grid_preferences as grid_preferences_routes
from app.routes import health as health_routes
from app.routes import (
    home_intelligence_dashboard_save as home_intelligence_dashboard_save_routes,
)
from app.routes import home_intelligence_snapshot as home_intelligence_snapshot_routes
from app.routes import home_intelligence_suggestions as home_intelligence_suggestions_routes
from app.routes import home_intelligence_suite as home_intelligence_suite_routes
from app.routes import home_pins as home_pins_routes
from app.routes import insight_chart_selection as insight_chart_selection_routes
from app.routes import insight_feedback_crud as insight_feedback_crud_routes
from app.routes import insight_feedback_review as insight_feedback_review_routes
from app.routes import internal_file_proxy as internal_file_proxy_routes
from app.routes import knowledge_graph as knowledge_graph_routes
from app.routes import llm_framework_artifacts as llm_framework_artifacts_routes
from app.routes import llm_framework_catalog as llm_framework_catalog_routes
from app.routes import llm_framework_deployments as llm_framework_deployments_routes
from app.routes import llm_framework_inventory as llm_framework_inventory_routes
from app.routes import mfa as mfa_routes
from app.routes import project_actions_comments as project_actions_comments_routes
from app.routes import project_actions_crud as project_actions_crud_routes
from app.routes import project_actions_lifecycle as project_actions_lifecycle_routes
from app.routes import project_assets as project_assets_routes
from app.routes import project_context as project_context_routes
from app.routes import project_graph as project_graph_routes
from app.routes import project_insight as project_insight_routes
from app.routes import projects_aggregates as projects_aggregates_routes
from app.routes import projects_crud as projects_crud_routes
from app.routes import projects_datasources as projects_datasources_routes
from app.routes import projects_members as projects_members_routes
from app.routes import projects_metadata as projects_metadata_routes
from app.routes import projects_queries as projects_queries_routes
from app.routes import provisioning as provisioning_routes
from app.routes import query as query_routes
from app.routes import query_scopes as query_scopes_routes
from app.routes import reference_library_bulk as reference_library_bulk_routes
from app.routes import reference_library_documents as reference_library_documents_routes
from app.routes import (
    reference_library_project_views as reference_library_project_views_routes,
)
from app.routes import reference_library_suggestions as reference_library_suggestions_routes
from app.routes import reports as reports_routes
from app.routes import repository_connectors as repository_connectors_routes
from app.routes import saas_sources as saas_sources_routes
from app.routes import scope_sets_builder as scope_sets_builder_routes
from app.routes import scope_sets_crud as scope_sets_crud_routes
from app.routes import scopes as scopes_routes
from app.routes import sharing as sharing_routes
from app.routes import storage as storage_routes
from app.routes import tenant_data_planes_crud as tenant_data_planes_crud_routes
from app.routes import tenant_data_planes_network as tenant_data_planes_network_routes
from app.routes import tenants_crud as tenants_crud_routes
from app.routes import tenants_security_policy as tenants_security_policy_routes
from app.routes import tenants_settings as tenants_settings_routes
from app.routes import tenants_users as tenants_users_routes
from app.routes import upload_core as upload_core_routes
from app.routes import upload_datasources as upload_datasources_routes
from app.routes import upload_replace as upload_replace_routes
from app.routes import upload_versions as upload_versions_routes
from app.routes import uploads as uploads_routes
from app.routes import user_preferences as user_preferences_routes
from app.routes import users as users_routes
from app.services.connection_pool import pool_manager
from app.services.llm_framework import ensure_primary_runtime_target_registered
from app.services.project_context import ProjectContextConcurrencyError
from app.services.vdb_warming import warm_vdb

logger = logging.getLogger(__name__)


def _reconcile_errors_are_permanent(result: dict) -> bool:
    """Return True if every reconcile failure is a non-retryable VDB state."""
    errors = result.get("errors", [])
    if not errors:
        return False
    permanent_markers = ("VDB file not found", "Invalid null Session")
    return all(
        any(marker in e.get("error", "") for marker in permanent_markers)
        for e in errors
    )


async def _reconcile_db_sources_on_startup() -> None:
    """Re-register DB-table sources in Teiid after a (re)start.

    Runtime JDBC datasources do not survive a Teiid container restart, so the
    persisted VDBs would otherwise reference missing datasources.  This runs in
    the background (with retries) so it never blocks or fails app startup if
    Teiid is not yet reachable.
    """
    from app.database import SessionLocal
    from app.services.teiid_registration_service import reconcile_database_sources

    for attempt in range(1, 7):
        await asyncio.sleep(min(10 * attempt, 30))
        try:
            async with SessionLocal() as session:
                result = await reconcile_database_sources(session)
            logger.info("Startup DB-source reconcile: %s", result)
            if result.get("failed", 0) == 0:
                return
            # A missing VDB file is not fixed by retrying; don't keep redeploying
            # the healthy VDBs just to fail on the same broken source.
            if _reconcile_errors_are_permanent(result):
                logger.warning(
                    "Startup DB-source reconcile has permanent failures; stopping retries: %s",
                    result,
                )
                return
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning(
                "Startup DB-source reconcile attempt %s failed: %s", attempt, exc
            )


async def _ensure_primary_llm_runtime_target() -> None:
    """Register the configured primary Ollama target if no target exists yet."""
    from app.database import SessionLocal

    await asyncio.sleep(3)
    try:
        async with SessionLocal() as session:
            await ensure_primary_runtime_target_registered(session)
        logger.info("Primary LLM runtime target ensured")
    except Exception as exc:
        logger.warning("Primary LLM runtime target registration failed: %s", exc)


async def _seed_reference_catalogs() -> None:
    """Seed AI reference catalogs on startup (idempotent)."""
    await asyncio.sleep(5)
    try:
        from scripts.seed_ai_reference_catalog import seed_catalogs
        stats = await seed_catalogs()
        logger.info("AI reference catalog seed: %s", stats)
    except Exception as exc:
        logger.warning("AI reference catalog seed failed: %s", exc)
    try:
        from scripts.seed_reference_library import seed_reference_library
        ref_stats = await seed_reference_library()
        logger.info("Reference library starter catalog seed: %s", ref_stats)
    except Exception as exc:
        logger.warning("Reference library seed failed: %s", exc)
    try:
        from scripts.seed_analytical_catalog import seed_analytical_catalog
        method_stats = await seed_analytical_catalog()
        logger.info("Analytical method catalog seed: %s", method_stats)
    except Exception as exc:
        # Loud, not silent: when this seed fails there is no approved+active
        # catalog version, so hybrid classification silently produces nothing.
        # Log at ERROR with the traceback so the failure is diagnosable.
        logger.error(
            "Analytical method catalog seed failed — hybrid analysis will be "
            "unavailable until an approved+active catalog version exists: %s",
            exc,
            exc_info=True,
        )


MAX_KG_PIPELINE_VERSION_CHECK_PROJECTS = 50


async def _warm_all_vdbs_on_startup() -> None:
    """Pre-warm asyncpg pools for every active VDB.

    This moves the first-connection cost (PG-wire handshake + pg_catalog
    materialization) out of the first user query and into startup.
    """
    from sqlalchemy import or_, select

    from app.database import SessionLocal
    from app.models.shared_vdb import SharedVDB
    from app.models.user_vdb import UserVDB

    try:
        async with SessionLocal() as session:
            result = await session.execute(
                select(UserVDB).where(
                    UserVDB.is_active.is_(True),
                    or_(
                        UserVDB.health_status.in_(["deployed", "active", "healthy"]),
                        UserVDB.health_status.is_(None),
                    ),
                )
            )
            user_vdbs = list(result.scalars().all())

            result = await session.execute(
                select(SharedVDB).where(SharedVDB.is_active.is_(True))
            )
            shared_vdbs = list(result.scalars().all())

        vdbs = [
            {
                "vdb_id": v.vdb_id,
                "host": v.vdb_host,
                "port": v.vdb_port,
                "username": v.vdb_username,
                "password": v.get_decrypted_password(),
            }
            for v in user_vdbs + shared_vdbs
        ]
        logger.info("Pre-warming %d active VDB pools", len(vdbs))

        # Cap concurrency so Teiid's PG transport is not overwhelmed by
        # simultaneous handshakes; background warm can be slower.
        semaphore = asyncio.Semaphore(3)

        async def _warm_one(v: dict) -> None:
            async with semaphore:
                await warm_vdb(
                    v["vdb_id"],
                    vdb_host=v["host"],
                    vdb_port=v["port"],
                    vdb_username=v["username"],
                    vdb_password=v["password"],
                    timeout=60.0,
                    warm_views=True,
                )

        await asyncio.gather(
            *[_warm_one(v) for v in vdbs],
            return_exceptions=True,
        )
        logger.info("VDB pool pre-warm complete")
    except Exception as exc:
        logger.warning("VDB pool pre-warm failed: %s", exc)


async def _check_kg_snapshot_pipeline_version_on_startup() -> None:
    """Proactively rebuild stale KG snapshots for recently-active projects.

    After a deploy that bumps ``SNAPSHOT_PIPELINE_VERSION``, any cached snapshot
    built under the previous version would only be rebuilt on the next user page
    load. This startup check finds the N most-recently-active projects and
    enqueues a full rebuild for any whose latest ``AIProjectGraphSnapshot``
    carries an older (or missing) ``pipeline_version``.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import AIProjectGraphSnapshot, IntelligenceSnapshot
    from app.models.knowledge_graph_snapshot import SNAPSHOT_KEY_FULL
    from app.services.knowledge_graph.constants import SNAPSHOT_PIPELINE_VERSION
    from app.services.knowledge_graph_lifecycle import KnowledgeGraphLifecycleManager
    from app.tasks.workflows import enqueue_rebuild_knowledge_graph

    await asyncio.sleep(15)
    settings = get_settings()
    days = getattr(settings, "business_insight_refresh_activity_days", 7)
    cutoff = datetime.now(UTC) - timedelta(days=days)
    enqueued = 0
    skipped = 0

    try:
        async with SessionLocal() as session:
            recent_rows = (
                await session.execute(
                    select(
                        IntelligenceSnapshot.payload,
                        IntelligenceSnapshot.updated_at,
                    )
                    .where(IntelligenceSnapshot.updated_at >= cutoff)
                    .order_by(IntelligenceSnapshot.updated_at.desc())
                )
            ).all()
            seen: set[int] = set()
            project_ids: list[int] = []
            for payload, _ in recent_rows:
                if not isinstance(payload, dict):
                    continue
                for p in (payload.get("projects") or []):
                    try:
                        project_id = int(p["id"])
                    except (TypeError, KeyError, ValueError):
                        continue
                    if project_id in seen:
                        continue
                    seen.add(project_id)
                    project_ids.append(project_id)
                    if len(project_ids) >= MAX_KG_PIPELINE_VERSION_CHECK_PROJECTS:
                        break
                if len(project_ids) >= MAX_KG_PIPELINE_VERSION_CHECK_PROJECTS:
                    break

            logger.info(
                "KG snapshot pipeline version check: running=%s active_projects=%s",
                SNAPSHOT_PIPELINE_VERSION,
                len(project_ids),
            )

            for project_id in project_ids:
                try:
                    snapshot = await session.scalar(
                        select(AIProjectGraphSnapshot)
                        .where(
                            AIProjectGraphSnapshot.project_id == project_id,
                            AIProjectGraphSnapshot.snapshot_key == SNAPSHOT_KEY_FULL,
                        )
                        .order_by(AIProjectGraphSnapshot.generated_at.desc())
                        .limit(1)
                    )
                    if snapshot is not None and (
                        snapshot.pipeline_version == SNAPSHOT_PIPELINE_VERSION
                    ):
                        skipped += 1
                        continue

                    manager = KnowledgeGraphLifecycleManager(session)
                    build, _ = await manager.request_full_rebuild(
                        project_id,
                        trigger="pipeline_version_mismatch",
                        requested_by=None,
                    )
                    await session.commit()
                    await enqueue_rebuild_knowledge_graph(build.id)
                    enqueued += 1
                except Exception as exc:
                    logger.warning(
                        "KG snapshot pipeline version check failed for project %s: %s",
                        project_id,
                        exc,
                    )
    except Exception as exc:
        logger.exception("KG snapshot pipeline version startup check failed: %s", exc)

    logger.info(
        "KG snapshot pipeline version check complete: enqueued=%s skipped=%s",
        enqueued,
        skipped,
    )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    setup_sentry()
    logger.info("Platform API starting (env=%s, version=%s)", settings.environment, __version__)
    from app.services.analytical_method_engine import get_engine_mode
    logger.info(
        "Analytical Method Engine mode resolved to '%s' "
        "(env ANALYTICAL_METHOD_ENGINE_MODE)",
        get_engine_mode().value,
    )
    reconcile_task = asyncio.create_task(_reconcile_db_sources_on_startup())

    async def _warm_after_reconcile() -> None:
        # Don't race the DB-source reconciler, which redeploys VDBs.
        try:
            await reconcile_task
        except Exception:
            pass
        await _warm_all_vdbs_on_startup()

    llm_target_task = asyncio.create_task(_ensure_primary_llm_runtime_target())
    seed_task = asyncio.create_task(_seed_reference_catalogs())
    kg_pipeline_check_task = asyncio.create_task(
        _check_kg_snapshot_pipeline_version_on_startup()
    )
    warm_vdbs_task = asyncio.create_task(_warm_after_reconcile())
    try:
        yield
    finally:
        reconcile_task.cancel()
        llm_target_task.cancel()
        seed_task.cancel()
        kg_pipeline_check_task.cancel()
        warm_vdbs_task.cancel()
        await pool_manager.close_all()
        logger.info("Platform API shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Tablescope Platform API",
        version=__version__,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        # Without this the browser drops the renewed-session header and every
        # session dies at the TTL regardless of activity.
        expose_headers=[SESSION_TOKEN_HEADER],
    )
    app.add_middleware(AuthMiddleware)

    app.add_exception_handler(MfaRequiredError, mfa_required_handler)

    async def _project_context_concurrency_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        error = exc if isinstance(exc, ProjectContextConcurrencyError) else None
        status_code = error.status_code if error else 409
        detail = error.detail if error else {"detail": "Conflict"}
        return JSONResponse(
            status_code=status_code,
            content=detail,
        )

    app.add_exception_handler(
        ProjectContextConcurrencyError, _project_context_concurrency_handler
    )

    @app.middleware("http")
    async def _add_request_id(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        context = getattr(request.state, "context", None)
        if context is not None:
            structlog.contextvars.bind_contextvars(
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    mount_metrics(app)

    app.include_router(health_routes.router)
    app.include_router(internal_file_proxy_routes.router)

    api_prefix = settings.api_prefix
    app.include_router(auth_routes.router, prefix=api_prefix)
    app.include_router(auth_sso_routes.router, prefix=api_prefix)
    app.include_router(tenants_crud_routes.router, prefix=api_prefix)
    app.include_router(tenants_settings_routes.router, prefix=api_prefix)
    app.include_router(tenants_security_policy_routes.router, prefix=api_prefix)
    app.include_router(enterprise_auth_settings_routes.router, prefix=api_prefix)
    app.include_router(enterprise_auth_ldap_routes.router, prefix=api_prefix)
    app.include_router(enterprise_auth_sso_routes.router, prefix=api_prefix)
    app.include_router(tenants_users_routes.router, prefix=api_prefix)
    # Network router first: its literal /firewall-script path must be matched
    # before the CRUD router's /{tenant_id}.
    app.include_router(tenant_data_planes_network_routes.router, prefix=api_prefix)
    app.include_router(tenant_data_planes_crud_routes.router, prefix=api_prefix)
    # Aggregate reads first: their literal paths (e.g. ``/summaries``) must be
    # matched before ``/{project_id}`` in projects_crud.
    app.include_router(projects_aggregates_routes.router, prefix=api_prefix)
    app.include_router(projects_crud_routes.router, prefix=api_prefix)
    app.include_router(projects_datasources_routes.router, prefix=api_prefix)
    app.include_router(projects_members_routes.router, prefix=api_prefix)
    app.include_router(projects_queries_routes.router, prefix=api_prefix)
    app.include_router(projects_metadata_routes.router, prefix=api_prefix)
    app.include_router(scopes_routes.router, prefix=api_prefix)
    app.include_router(query_routes.router, prefix=api_prefix)
    app.include_router(query_scopes_routes.router, prefix=api_prefix)
    app.include_router(scope_sets_crud_routes.router, prefix=api_prefix)
    app.include_router(scope_sets_builder_routes.router, prefix=api_prefix)
    app.include_router(sharing_routes.router, prefix=api_prefix)
    app.include_router(storage_routes.router, prefix=api_prefix)
    app.include_router(database_sources_connection_routes.router, prefix=api_prefix)
    app.include_router(
        database_sources_saved_connections_routes.router, prefix=api_prefix
    )
    app.include_router(database_sources_lifecycle_routes.router, prefix=api_prefix)
    app.include_router(
        data_source_assignments_routes.router, prefix=api_prefix
    )
    app.include_router(saas_sources_routes.router, prefix=api_prefix)
    app.include_router(connected_sources_routes.router, prefix=api_prefix)
    app.include_router(connectors_routes.router, prefix=api_prefix)
    app.include_router(data_source_catalog_routes.router, prefix=api_prefix)
    app.include_router(grid_preferences_routes.router, prefix=api_prefix)
    app.include_router(upload_core_routes.router, prefix=api_prefix)
    app.include_router(upload_datasources_routes.router, prefix=api_prefix)
    app.include_router(upload_replace_routes.router, prefix=api_prefix)
    app.include_router(upload_versions_routes.router, prefix=api_prefix)
    app.include_router(uploads_routes.router, prefix=api_prefix)
    app.include_router(file_analysis_routes.router, prefix=api_prefix)
    app.include_router(file_imports_routes.router, prefix=api_prefix)
    app.include_router(file_imports_routes.connections_router, prefix=api_prefix)
    app.include_router(file_imports_routes.hosts_router, prefix=api_prefix)
    app.include_router(dashboards_crud_routes.router, prefix=api_prefix)
    app.include_router(dashboards_widget_query_routes.router, prefix=api_prefix)
    app.include_router(ai_proxy_routes.router, prefix=api_prefix)
    app.include_router(ai_speech_routes.router, prefix=api_prefix)
    app.include_router(ai_governance_routes.router, prefix=api_prefix)
    app.include_router(ai_reference_catalog_routes.router, prefix=api_prefix)
    app.include_router(analytical_methods_routes.router, prefix=api_prefix)
    app.include_router(llm_framework_inventory_routes.router, prefix=api_prefix)
    app.include_router(llm_framework_catalog_routes.router, prefix=api_prefix)
    app.include_router(llm_framework_artifacts_routes.router, prefix=api_prefix)
    app.include_router(llm_framework_deployments_routes.router, prefix=api_prefix)
    app.include_router(ai_asset_metadata_routes.router, prefix=api_prefix)
    app.include_router(project_assets_routes.router, prefix=api_prefix)
    app.include_router(project_context_routes.router, prefix=api_prefix)
    app.include_router(project_graph_routes.router, prefix=api_prefix)
    app.include_router(project_actions_crud_routes.router, prefix=api_prefix)
    app.include_router(project_actions_lifecycle_routes.router, prefix=api_prefix)
    app.include_router(project_actions_comments_routes.router, prefix=api_prefix)
    app.include_router(project_insight_routes.router, prefix=api_prefix)
    app.include_router(knowledge_graph_routes.router, prefix=api_prefix)
    app.include_router(document_families_reads_routes.router, prefix=api_prefix)
    app.include_router(document_families_curation_routes.router, prefix=api_prefix)
    app.include_router(document_families_summary_routes.router, prefix=api_prefix)
    app.include_router(billing_routes.router, prefix=api_prefix)
    app.include_router(billing_admin_routes.router, prefix=api_prefix)
    app.include_router(provisioning_routes.router, prefix=api_prefix)
    app.include_router(home_intelligence_suite_routes.router, prefix=api_prefix)
    app.include_router(home_intelligence_snapshot_routes.router, prefix=api_prefix)
    app.include_router(home_intelligence_suggestions_routes.router, prefix=api_prefix)
    app.include_router(home_intelligence_dashboard_save_routes.router, prefix=api_prefix)
    app.include_router(home_pins_routes.router, prefix=api_prefix)
    app.include_router(insight_chart_selection_routes.router, prefix=api_prefix)
    app.include_router(conversational_analytics_conversations_routes.router, prefix=api_prefix)
    app.include_router(conversational_analytics_turns_routes.router, prefix=api_prefix)
    # Review router first: its literal /review paths must be matched before the
    # CRUD router's /{insight_id}.
    app.include_router(insight_feedback_review_routes.router, prefix=api_prefix)
    app.include_router(insight_feedback_crud_routes.router, prefix=api_prefix)
    app.include_router(reference_library_documents_routes.router, prefix=api_prefix)
    app.include_router(reference_library_project_views_routes.router, prefix=api_prefix)
    app.include_router(reference_library_suggestions_routes.router, prefix=api_prefix)
    app.include_router(reference_library_bulk_routes.router, prefix=api_prefix)
    app.include_router(repository_connectors_routes.router, prefix=api_prefix)
    app.include_router(reports_routes.router, prefix=api_prefix)
    app.include_router(user_preferences_routes.router, prefix=api_prefix)
    app.include_router(users_routes.router, prefix=api_prefix)
    app.include_router(mfa_routes.router, prefix=api_prefix)

    return app


app = create_app()
