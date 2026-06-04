"""Health check endpoints.

`/health/live` is a cheap liveness probe.
`/health/ready` runs end-to-end checks against the database, Redis and the
Teiid servlet so a load balancer can take a hot replica out of rotation when
its dependencies are degraded.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from redis.asyncio import Redis
from sqlalchemy import text

from app import __version__
from app.config import get_settings
from app.database import engine
from app.schemas.health import ComponentHealth, HealthStatus
from app.services.vdb_management import VDBManagementService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=HealthStatus)
async def live() -> HealthStatus:
    return HealthStatus(status="ok", version=__version__)


@router.get("/ready", response_model=HealthStatus)
async def ready() -> HealthStatus:
    settings = get_settings()
    components: list[ComponentHealth] = []
    overall_ok = True

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        components.append(ComponentHealth(name="database", status="ok"))
    except Exception as exc:
        overall_ok = False
        components.append(ComponentHealth(name="database", status="error", detail=str(exc)))

    try:
        redis = Redis.from_url(settings.redis_url)
        try:
            await redis.ping()
            components.append(ComponentHealth(name="redis", status="ok"))
        finally:
            await redis.aclose()
    except Exception as exc:
        overall_ok = False
        components.append(ComponentHealth(name="redis", status="error", detail=str(exc)))

    teiid = VDBManagementService()
    try:
        if await teiid.health():
            components.append(ComponentHealth(name="teiid_servlet", status="ok"))
        else:
            overall_ok = False
            components.append(
                ComponentHealth(name="teiid_servlet", status="degraded", detail="non-2xx response")
            )
    finally:
        await teiid.aclose()

    return HealthStatus(
        status="ok" if overall_ok else "degraded",
        version=__version__,
        components=components,
    )
