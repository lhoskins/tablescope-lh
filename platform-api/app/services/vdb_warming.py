"""Background warming for Teiid VDBs.

The first asyncpg connection to a freshly deployed VDB pays several one-time
costs: pool creation, Teiid PG-wire handshake, internal pg_catalog
materialization, and per-source translator capability loading. Warming opens a
direct (short-lived) connection, runs a trivial SELECT so asyncpg's type
introspection triggers pg_catalog load, and optionally touches every MyCompany
view so source translator metadata and result-set caches are loaded in the
background. The platform-api connection pool is left for real user queries, so
this warming does not hold idle connections open.
"""

from __future__ import annotations

import asyncio
import logging

import asyncpg

from app.config import get_settings

logger = logging.getLogger(__name__)


async def warm_vdb(
    vdb_id: str,
    *,
    vdb_host: str | None = None,
    vdb_port: int | None = None,
    vdb_username: str = "test",
    vdb_password: str = "test",
    timeout: float = 60.0,
    connect_timeout: float | None = None,
    warm_views: bool = False,
    max_concurrent_views: int = 1,
    max_attempts: int = 3,
    retry_delay: float = 5.0,
) -> None:
    """Open a direct connection to a VDB and run queries to warm caches.

    Any failure is logged but not raised; warming must not break the caller's
    primary flow. Retries are used because a VDB may still be completing a
    redeploy when the warm is triggered.
    """
    settings = get_settings()
    host = vdb_host or settings.teiid_pg_host
    port = vdb_port or settings.teiid_pg_port
    database = f"{vdb_id}.1"

    logger.info("Warming VDB %s at %s:%s/%s", vdb_id, host, port, database)

    # NOTE: we intentionally do NOT evict the pool here.  Warming is a
    # best-effort background task and must not close pools that are currently
    # serving user queries.  Callers that redeploy a VDB are responsible for
    # evicting stale pools themselves.

    last_exc: Exception | None = None
    conn_timeout = connect_timeout or timeout
    for attempt in range(1, max_attempts + 1):
        conn: asyncpg.Connection | None = None
        try:
            conn = await asyncpg.connect(
                host=host,
                port=port,
                database=database,
                user=vdb_username,
                password=vdb_password,
                ssl=False,
                timeout=conn_timeout,
                command_timeout=timeout,
                statement_cache_size=0,
                server_settings={"application_name": "tablescope-platform-api-warm"},
            )
            # SELECT 1 warms pg_catalog / type introspection for the VDB.
            await asyncio.wait_for(conn.fetch("SELECT 1"), timeout=conn_timeout)
            if warm_views:
                await _warm_mycompany_views(
                    conn,
                    vdb_id=vdb_id,
                    timeout=timeout,
                    max_concurrent=max_concurrent_views,
                    max_attempts=max_attempts,
                    retry_delay=retry_delay,
                )
            logger.info(
                "Warmed VDB %s at %s:%s/%s (attempt %d/%d)",
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
                "VDB %s warm attempt %d/%d failed: %s (%s)",
                vdb_id,
                attempt,
                max_attempts,
                exc,
                exc.__class__.__name__,
            )
            if attempt < max_attempts:
                await asyncio.sleep(retry_delay)
        finally:
            if conn is not None:
                try:
                    await conn.close()
                except Exception as close_exc:
                    logger.debug("Could not close warm connection for %s: %s", vdb_id, close_exc)
    else:
        logger.warning(
            "VDB warm failed for %s after %d attempts: %s",
            vdb_id,
            max_attempts,
            last_exc,
        )


async def _warm_mycompany_views(
    conn: asyncpg.Connection,
    *,
    vdb_id: str,
    timeout: float,
    max_concurrent: int,
    max_attempts: int,
    retry_delay: float,
) -> None:
    """Load every MyCompany view once so source translator metadata is cached.

    Each view query uses the same connection with a concurrency semaphore so
    commands are never interleaved on a single asyncpg connection.
    """
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
                    # Lightweight query that still forces Teiid to plan and
                    # load per-source translator metadata for the view.
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
