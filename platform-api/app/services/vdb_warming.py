"""Background warming for Teiid VDBs.

The first asyncpg connection to a freshly deployed VDB pays several one-time
costs: pool creation, Teiid PG-wire handshake, and internal pg_catalog
materialization. Warming creates the pool and runs a trivial query so the
next real user query reuses a ready connection.

Optionally, the warmer can also touch every view in the MyCompany virtual
schema. That forces Teiid to load source metadata and any result-set caches
for each translator in the background, so the first real table query is fast.
"""

from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.services.connection_pool import pool_manager

logger = logging.getLogger(__name__)


async def warm_vdb(
    vdb_id: str,
    *,
    vdb_host: str | None = None,
    vdb_port: int | None = None,
    vdb_username: str = "test",
    vdb_password: str = "test",
    timeout: float = 60.0,
    warm_views: bool = False,
    max_concurrent_views: int = 5,
) -> None:
    """Open a connection to a VDB and run a trivial SELECT to warm caches.

    Any failure is logged but not raised; warming must not break the caller's
    primary flow.
    """
    settings = get_settings()
    host = vdb_host or settings.teiid_pg_host
    port = vdb_port or settings.teiid_pg_port
    database = f"{vdb_id}.1"

    logger.info("Warming VDB %s at %s:%s/%s", vdb_id, host, port, database)
    try:
        pool = await asyncio.wait_for(
            pool_manager.get_pool(
                host=host,
                port=port,
                database=database,
                username=vdb_username,
                password=vdb_password,
            ),
            timeout=timeout,
        )
        await asyncio.wait_for(pool.fetch("SELECT 1"), timeout=timeout)
        logger.info("Warmed VDB %s pool at %s:%s/%s", vdb_id, host, port, database)

        if warm_views:
            await _warm_mycompany_views(
                pool,
                vdb_id=vdb_id,
                timeout=timeout,
                max_concurrent=max_concurrent_views,
            )
    except Exception as exc:
        logger.warning("VDB warm failed for %s: %s", vdb_id, exc)


async def _warm_mycompany_views(
    pool,
    *,
    vdb_id: str,
    timeout: float,
    max_concurrent: int,
) -> None:
    """Load every MyCompany view once so source metadata is cached."""
    try:
        rows = await asyncio.wait_for(
            pool.fetch(
                "SELECT Name FROM SYS.Tables "
                "WHERE SchemaName = 'MyCompany' AND IsSystem = false"
            ),
            timeout=timeout,
        )
    except Exception as exc:
        logger.warning("VDB %s could not list MyCompany views: %s", vdb_id, exc)
        return

    view_names = [r["Name"] for r in rows]
    if not view_names:
        return

    logger.info("Warming %d MyCompany views for VDB %s", len(view_names), vdb_id)
    semaphore = asyncio.Semaphore(max_concurrent)
    warmed = 0
    failed = 0

    async def _warm_one(name: str) -> None:
        nonlocal warmed, failed
        safe_name = name.replace('"', '""')
        async with semaphore:
            try:
                await asyncio.wait_for(
                    pool.fetch(
                        f'SELECT 1 FROM "MyCompany"."{safe_name}" LIMIT 1'
                    ),
                    timeout=timeout,
                )
                warmed += 1
            except Exception as exc:
                failed += 1
                logger.debug(
                    "View warm failed for %s.%s: %s", vdb_id, name, exc
                )

    await asyncio.gather(*[_warm_one(name) for name in view_names])
    logger.info(
        "Warmed MyCompany views for VDB %s: ok=%d failed=%d",
        vdb_id,
        warmed,
        failed,
    )
