"""Background warming for Teiid VDBs.

The first asyncpg connection to a freshly deployed VDB pays several one-time
costs: pool creation, Teiid PG-wire handshake, and internal pg_catalog
materialization. Warming opens a standalone connection, runs a trivial SELECT
so asyncpg's type introspection triggers that pg_catalog load, and optionally
touches every MyCompany view so source translator metadata and result-set
caches are loaded in the background.
"""

from __future__ import annotations

import asyncio
import logging

import asyncpg

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
    max_attempts: int = 3,
    retry_delay: float = 5.0,
) -> None:
    """Open a connection to a VDB and run queries to warm caches.

    Any failure is logged but not raised; warming must not break the caller's
    primary flow. Retries are used because a VDB may still be completing a
    redeploy when the warm is triggered.
    """
    settings = get_settings()
    host = vdb_host or settings.teiid_pg_host
    port = vdb_port or settings.teiid_pg_port
    database = f"{vdb_id}.1"

    logger.info("Warming VDB %s at %s:%s/%s", vdb_id, host, port, database)

    # Drop any cached pool for this VDB first. A redeploy invalidates the
    # PG sessions it contains, and a stuck pool can block subsequent attempts.
    try:
        await asyncio.wait_for(pool_manager.evict_by_vdb_id(vdb_id), timeout=5.0)
    except Exception as exc:
        logger.debug("Could not evict stale pool for %s: %s", vdb_id, exc)

    conn: asyncpg.Connection | None = None
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            conn = await asyncio.wait_for(
                asyncpg.connect(
                    host=host,
                    port=port,
                    database=database,
                    user=vdb_username,
                    password=vdb_password,
                    command_timeout=60,
                    server_settings={"application_name": "tablescope-vdb-warm"},
                ),
                timeout=timeout,
            )
            await asyncio.wait_for(conn.fetch("SELECT 1"), timeout=timeout)
            logger.info(
                "Warmed VDB %s connection at %s:%s/%s (attempt %d/%d)",
                vdb_id,
                host,
                port,
                database,
                attempt,
                max_attempts,
            )
            break
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "VDB %s connection warm attempt %d/%d failed: %s (%s)",
                vdb_id,
                attempt,
                max_attempts,
                exc,
                exc.__class__.__name__,
            )
            if conn is not None:
                try:
                    await conn.close()
                except Exception:
                    pass
                conn = None
            if attempt < max_attempts:
                await asyncio.sleep(retry_delay)
        else:
            break
    else:
        logger.warning(
            "VDB warm failed for %s after %d attempts: %s",
            vdb_id,
            max_attempts,
            last_exc,
        )
        return

    if conn is None:
        return

    try:
        if warm_views:
            await _warm_mycompany_views(
                conn,
                vdb_id=vdb_id,
                timeout=timeout,
                max_concurrent=max_concurrent_views,
                max_attempts=max_attempts,
                retry_delay=retry_delay,
            )
    finally:
        try:
            await conn.close()
        except Exception:
            pass


async def _warm_mycompany_views(
    conn: asyncpg.Connection,
    *,
    vdb_id: str,
    timeout: float,
    max_concurrent: int,
    max_attempts: int,
    retry_delay: float,
) -> None:
    """Load every MyCompany view once so source metadata is cached."""
    rows = None
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            rows = await asyncio.wait_for(
                conn.fetch(
                    "SELECT Name FROM SYS.Tables "
                    "WHERE SchemaName = 'MyCompany' AND IsSystem = false"
                ),
                timeout=timeout,
            )
            break
        except Exception as exc:
            last_exc = exc
            if attempt < max_attempts:
                await asyncio.sleep(retry_delay)
    if rows is None:
        logger.warning(
            "VDB %s could not list MyCompany views after %d attempts: %s",
            vdb_id,
            max_attempts,
            last_exc,
        )
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
            for attempt in range(1, max_attempts + 1):
                try:
                    await asyncio.wait_for(
                        conn.fetch(
                            f'SELECT 1 FROM "MyCompany"."{safe_name}" LIMIT 1'
                        ),
                        timeout=timeout,
                    )
                    warmed += 1
                    return
                except Exception as exc:
                    if attempt == max_attempts:
                        failed += 1
                        logger.debug(
                            "View warm failed for %s.%s: %s (%s)",
                            vdb_id,
                            name,
                            exc,
                            exc.__class__.__name__,
                        )
                    else:
                        await asyncio.sleep(retry_delay)

    await asyncio.gather(*[_warm_one(name) for name in view_names])
    logger.info(
        "Warmed MyCompany views for VDB %s: ok=%d failed=%d",
        vdb_id,
        warmed,
        failed,
    )
