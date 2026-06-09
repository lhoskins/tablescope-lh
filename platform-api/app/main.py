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

from app import __version__
from app.auth.middleware import AuthMiddleware
from app.config import get_settings
from app.logging_config import configure_logging
from app.observability import mount_metrics, setup_sentry
from app.routes import ai_proxy as ai_proxy_routes
from app.routes import auth as auth_routes
from app.routes import dashboards as dashboards_routes
from app.routes import database_sources as database_sources_routes
from app.routes import file_analysis as file_analysis_routes
from app.routes import grid_preferences as grid_preferences_routes
from app.routes import health as health_routes
from app.routes import projects as projects_routes
from app.routes import query as query_routes
from app.routes import query_scopes as query_scopes_routes
from app.routes import saas_sources as saas_sources_routes
from app.routes import scopes as scopes_routes
from app.routes import sharing as sharing_routes
from app.routes import storage as storage_routes
from app.routes import tenant_data_planes as tenant_data_planes_routes
from app.routes import tenants as tenants_routes
from app.routes import upload as upload_routes
from app.services.connection_pool import pool_manager

logger = logging.getLogger(__name__)


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
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning(
                "Startup DB-source reconcile attempt %s failed: %s", attempt, exc
            )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    setup_sentry()
    logger.info("Platform API starting (env=%s, version=%s)", settings.environment, __version__)
    reconcile_task = asyncio.create_task(_reconcile_db_sources_on_startup())
    try:
        yield
    finally:
        reconcile_task.cancel()
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
    )
    app.add_middleware(AuthMiddleware)

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

    api_prefix = settings.api_prefix
    app.include_router(auth_routes.router, prefix=api_prefix)
    app.include_router(tenants_routes.router, prefix=api_prefix)
    app.include_router(tenant_data_planes_routes.router, prefix=api_prefix)
    app.include_router(projects_routes.router, prefix=api_prefix)
    app.include_router(scopes_routes.router, prefix=api_prefix)
    app.include_router(query_routes.router, prefix=api_prefix)
    app.include_router(query_scopes_routes.router, prefix=api_prefix)
    app.include_router(sharing_routes.router, prefix=api_prefix)
    app.include_router(storage_routes.router, prefix=api_prefix)
    app.include_router(database_sources_routes.router, prefix=api_prefix)
    app.include_router(saas_sources_routes.router, prefix=api_prefix)
    app.include_router(grid_preferences_routes.router, prefix=api_prefix)
    app.include_router(upload_routes.router, prefix=api_prefix)
    app.include_router(file_analysis_routes.router, prefix=api_prefix)
    app.include_router(dashboards_routes.router, prefix=api_prefix)
    app.include_router(ai_proxy_routes.router, prefix=api_prefix)

    return app


app = create_app()
