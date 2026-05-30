"""Async connection pool for Teiid (PG-wire) queries.

asyncpg pools are keyed by `(host, port, vdb_name, username)` so each tenant's
VDB gets its own pool. Pools are created lazily and cached.

Teiid's PG wire protocol is compatible with asyncpg but does NOT support
certain PostgreSQL internal functions (e.g. pg_advisory_unlock_all) that
asyncpg calls during pool reset.  We provide a no-op reset callback.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from decimal import Decimal

import asyncpg

from app.config import get_settings

logger = logging.getLogger(__name__)


async def _teiid_reset(conn: asyncpg.Connection) -> None:
    """No-op pool reset for Teiid connections.

    The default asyncpg pool reset calls ``pg_advisory_unlock_all()`` which
    Teiid does not implement (TEIID30068).  Skipping it is safe because
    advisory locks are not used.
    """


def _decode_numeric(value: str) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(value)


async def _teiid_init(conn: asyncpg.Connection) -> None:
    """Per-connection setup for Teiid (PG-wire) connections.

    Teiid's PG-wire binary encoding for ``NUMERIC`` is incompatible with
    asyncpg's binary decoder and fails with "insufficient data in buffer".
    Registering a text-format codec forces asyncpg to request the value as
    text, which Teiid encodes correctly.
    """
    await conn.set_type_codec(
        "numeric",
        schema="pg_catalog",
        encoder=str,
        decoder=_decode_numeric,
        format="text",
    )


@dataclass(frozen=True, slots=True)
class PoolKey:
    host: str
    port: int
    database: str
    username: str


class TeiidConnectionPoolManager:
    """Maintains per-VDB asyncpg pools with bounded size."""

    def __init__(self, *, min_size: int = 1, max_size: int = 10) -> None:
        self._min_size = min_size
        self._max_size = max_size
        self._pools: dict[PoolKey, asyncpg.Pool] = {}
        self._lock = asyncio.Lock()

    async def get_pool(
        self,
        *,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
    ) -> asyncpg.Pool:
        key = PoolKey(host=host, port=port, database=database, username=username)
        pool = self._pools.get(key)
        if pool is not None:
            return pool
        async with self._lock:
            pool = self._pools.get(key)
            if pool is not None:
                return pool
            logger.info("Creating new Teiid asyncpg pool for %s@%s:%s/%s", username, host, port, database)
            pool = await asyncpg.create_pool(
                host=host,
                port=port,
                database=database,
                user=username,
                password=password,
                min_size=self._min_size,
                max_size=self._max_size,
                command_timeout=60,
                statement_cache_size=0,
                server_settings={"application_name": "tablescope-platform-api"},
                reset=_teiid_reset,
                init=_teiid_init,
            )
            self._pools[key] = pool
            return pool

    async def evict_pool(
        self, *, host: str, port: int, database: str, username: str
    ) -> None:
        """Close and remove a specific pool (e.g. after a stale-session error)."""
        key = PoolKey(host=host, port=port, database=database, username=username)
        async with self._lock:
            pool = self._pools.pop(key, None)
            if pool is not None:
                logger.info("Evicting stale Teiid pool %s", key)
                await pool.close()

    async def close_all(self) -> None:
        async with self._lock:
            for key, pool in list(self._pools.items()):
                logger.info("Closing Teiid pool %s", key)
                await pool.close()
            self._pools.clear()


_settings = get_settings()
pool_manager = TeiidConnectionPoolManager(
    min_size=max(1, _settings.database_pool_min_size // 4),
    max_size=_settings.database_pool_max_size,
)
