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

import asyncpg

from app.config import get_settings

logger = logging.getLogger(__name__)


async def _teiid_reset(conn: asyncpg.Connection) -> None:
    """No-op pool reset for Teiid connections.

    The default asyncpg pool reset calls ``pg_advisory_unlock_all()`` which
    Teiid does not implement (TEIID30068).  Skipping it is safe because
    advisory locks are not used.
    """


@dataclass(frozen=True, slots=True)
class PoolKey:
    host: str
    port: int
    database: str
    username: str


class TeiidConnectionPoolManager:
    """Maintains per-VDB asyncpg pools with bounded size."""

    def __init__(
        self,
        *,
        min_size: int = 1,
        max_size: int = 20,
        max_inactive_connection_lifetime: float = 120.0,
    ) -> None:
        self._min_size = min_size
        self._max_size = max_size
        self._max_inactive_connection_lifetime = max_inactive_connection_lifetime
        self._pools: dict[PoolKey, asyncpg.Pool] = {}
        # Per-key locks serialize pool creation/eviction for a single VDB.
        # _locks_lock protects the _key_locks map itself.
        self._key_locks: dict[PoolKey, asyncio.Lock] = {}
        self._locks_lock = asyncio.Lock()

    def _key_lock(self, key: PoolKey) -> asyncio.Lock:
        """Return (and lazily create) the lock for a specific pool key."""
        lock = self._key_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._key_locks[key] = lock
        return lock

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
        if pool is not None and not pool._closed:
            return pool

        # Serialize on the VDB key so a slow/defunct VDB creation does not
        # block pools for other VDBs.
        async with self._locks_lock:
            pool = self._pools.get(key)
            if pool is not None and not pool._closed:
                return pool
            key_lock = self._key_lock(key)

        async with key_lock:
            pool = self._pools.get(key)
            if pool is not None and not pool._closed:
                return pool
            logger.info("Creating new Teiid asyncpg pool for %s@%s:%s/%s", username, host, port, database)
            # Teiid's PG wire does not support SSL; disable it to avoid a
            # negotiation hang.  min_size=1 pre-warms one connection so the
            # first user query does not pay the full handshake cost.  Timeouts
            # are generous for cold CSV scans but not unbounded.
            pool = await asyncpg.create_pool(
                host=host,
                port=port,
                database=database,
                user=username,
                password=password,
                min_size=self._min_size,
                max_size=self._max_size,
                max_inactive_connection_lifetime=self._max_inactive_connection_lifetime,
                ssl=False,
                timeout=120,
                command_timeout=180,
                statement_cache_size=0,
                server_settings={"application_name": "tablescope-platform-api"},
                reset=_teiid_reset,
            )
            self._pools[key] = pool
            return pool

    async def evict_pool(
        self, *, host: str, port: int, database: str, username: str
    ) -> None:
        """Close and remove a specific pool (e.g. after a stale-session error)."""
        key = PoolKey(host=host, port=port, database=database, username=username)
        async with self._locks_lock:
            key_lock = self._key_lock(key)

        async with key_lock:
            pool = self._pools.pop(key, None)

        if pool is not None:
            logger.info("Evicting stale Teiid pool %s", key)
            try:
                await asyncio.wait_for(pool.close(), timeout=5.0)
            except TimeoutError:
                logger.warning("Timed out closing evicted Teiid pool %s", key)
            except Exception as exc:
                logger.warning("Could not close evicted Teiid pool %s: %s", key, exc)

    async def evict_by_vdb_id(self, vdb_id: str) -> None:
        """Close all cached pools for a VDB (e.g. after a VDB redeploy)."""
        database = f"{vdb_id}.1"
        keys = [k for k in list(self._pools.keys()) if k.database == database]
        for key in keys:
            async with self._locks_lock:
                key_lock = self._key_lock(key)

            async with key_lock:
                pool = self._pools.pop(key, None)

            if pool is not None:
                logger.info("Evicting stale Teiid pool %s", key)
                try:
                    await asyncio.wait_for(pool.close(), timeout=5.0)
                except TimeoutError:
                    logger.warning("Timed out closing evicted Teiid pool %s", key)
                except Exception as exc:
                    logger.warning("Could not close evicted Teiid pool %s: %s", key, exc)

    @property
    def max_size(self) -> int:
        return self._max_size

    async def close_all(self) -> None:
        async with self._locks_lock:
            pools = list(self._pools.items())
            self._pools.clear()

        for key, pool in pools:
            key_lock = self._key_locks.get(key)
            if key_lock is not None:
                async with key_lock:
                    pass  # ensure no creation is in flight for this key
            logger.info("Closing Teiid pool %s", key)
            try:
                await asyncio.wait_for(pool.close(), timeout=5.0)
            except TimeoutError:
                logger.warning("Timed out closing Teiid pool %s", key)
            except Exception as exc:
                logger.warning("Could not close Teiid pool %s: %s", key, exc)


_settings = get_settings()
pool_manager = TeiidConnectionPoolManager(
    min_size=1,
    max_size=min(_settings.database_pool_max_size, 20),
    max_inactive_connection_lifetime=120.0,
)
