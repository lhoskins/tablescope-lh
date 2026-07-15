"""Distributed Redis lock for repository scans."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from app.services.home_intel_queue import get_redis

logger = logging.getLogger(__name__)

_DEFAULT_TTL_SECONDS = 600
_LOCK_PREFIX = "repo:scan:lock"


class RepositoryScanLock:
    """A process-safe Redis-backed lock for a single repository scan."""

    def __init__(self, connection_id: int, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> None:
        self.connection_id = connection_id
        self.ttl_seconds = ttl_seconds
        self.lock_id = str(uuid.uuid4())
        self.key = f"{_LOCK_PREFIX}:{connection_id}"

    async def acquire(self) -> bool:
        redis = get_redis()
        acquired = await redis.set(
            self.key,
            self.lock_id,
            nx=True,
            ex=self.ttl_seconds,
        )
        return bool(acquired)

    async def refresh(self) -> bool:
        redis = get_redis()
        current = await redis.get(self.key)
        if current != self.lock_id:
            return False
        await redis.expire(self.key, self.ttl_seconds)
        return True

    async def release(self) -> None:
        redis = get_redis()
        current = await redis.get(self.key)
        if current == self.lock_id:
            await redis.delete(self.key)

    async def is_held(self) -> bool:
        redis = get_redis()
        current = await redis.get(self.key)
        return current == self.lock_id


class RepositoryScanHeartbeat:
    """Redis-backed stale-scan heartbeat for a repository scan."""

    def __init__(
        self,
        scan_id: int,
        ttl_seconds: int = 300,
    ) -> None:
        self.scan_id = scan_id
        self.ttl_seconds = ttl_seconds
        self.key = f"repo:scan:heartbeat:{scan_id}"

    async def beat(self) -> None:
        redis = get_redis()
        await redis.set(self.key, datetime.now(UTC).isoformat(), ex=self.ttl_seconds)

    async def is_alive(self) -> bool:
        redis = get_redis()
        return bool(await redis.exists(self.key))
