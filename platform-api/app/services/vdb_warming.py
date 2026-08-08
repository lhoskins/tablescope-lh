"""Background warming for Teiid VDBs.

The first asyncpg connection to a freshly deployed VDB pays several one-time
costs: pool creation, Teiid PG-wire handshake, and internal pg_catalog
materialization. Warming creates the pool and runs a trivial query so the
next real user query reuses a ready connection.
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
        logger.info("Warmed VDB %s at %s:%s/%s", vdb_id, host, port, database)
    except Exception as exc:
        logger.warning("VDB warm failed for %s: %s", vdb_id, exc)
