"""FastAPI application entrypoint."""

from __future__ import annotations

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
from app.routes import auth as auth_routes
from app.routes import database_sources as database_sources_routes
from app.routes import health as health_routes
from app.routes import projects as projects_routes
from app.routes import query as query_routes
from app.routes import scopes as scopes_routes
from app.routes import sharing as sharing_routes
from app.routes import tenants as tenants_routes
from app.routes import storage as storage_routes
from app.routes import upload as upload_routes
from app.services.connection_pool import pool_manager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    setup_sentry()
    logger.info("Platform API starting (env=%s, version=%s)", settings.environment, __version__)
    try:
        yield
    finally:
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
    app.include_router(projects_routes.router, prefix=api_prefix)
    app.include_router(scopes_routes.router, prefix=api_prefix)
    app.include_router(query_routes.router, prefix=api_prefix)
    app.include_router(sharing_routes.router, prefix=api_prefix)
    app.include_router(storage_routes.router, prefix=api_prefix)
    app.include_router(database_sources_routes.router, prefix=api_prefix)
    app.include_router(upload_routes.router, prefix=api_prefix)

    return app


app = create_app()
