"""Durable per-run coordination for the Home / Business Insight feed on Redis.

The SSE feed used to fan every accessible project out inline on the request
coroutine, so under concurrent AI load projects were silently dropped. This
module backs a durable alternative: each project is analysed by an ``arq``
worker job, results are written to a per-run store in Redis, and the SSE
request only *streams* what the workers produce. Because all state lives in
Redis (shared across worker replicas):

* the per-tenant concurrency cap is authoritative even when the worker is
  scaled horizontally (unlike an in-process semaphore);
* results and the final snapshot survive a dropped SSE connection — the run
  finishes server-side regardless.

Keys (all namespaced by ``run_id`` and TTL'd):

===============================  ======  ====================================
``home-intel:{run_id}:meta``     hash    run metadata (tenant/user/…)
``home-intel:{run_id}:expected`` set     project ids expected in the run
``home-intel:{run_id}:results``  hash    project_id -> result JSON
``home-intel:{run_id}:synthesis`` str    cross-project synthesis JSON (final;
                                         also the run's completion signal)
``home-intel:{run_id}:finalized`` str    set-once marker (finalizer winner)
``home-intel:{run_id}``          channel pub/sub wakeups on progress
``home-intel:tenant-slots:{id}`` str     per-tenant tokens currently held
===============================  ======  ====================================
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from typing import Any, cast

import redis.asyncio as redis

from app.config import get_settings

logger = logging.getLogger(__name__)

# A leaked per-tenant token (worker killed mid-analysis) self-heals within this
# window; kept comfortably above a single project's worst-case runtime.
_TENANT_SLOT_TTL_SECONDS = 900

_KEY_PREFIX = "home-intel"

_redis: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """Return a process-wide Redis client (text mode). Patchable in tests."""
    global _redis
    if _redis is None:
        _redis = redis.from_url(
            get_settings().redis_url, decode_responses=True
        )
    return _redis


def _ttl() -> int:
    return max(60, get_settings().home_intelligence_run_result_ttl_seconds)


def _k(run_id: str, suffix: str) -> str:
    return f"{_KEY_PREFIX}:{run_id}:{suffix}"


def channel(run_id: str) -> str:
    return f"{_KEY_PREFIX}:{run_id}"


def _tenant_slots_key(tenant_id: int) -> str:
    return f"{_KEY_PREFIX}:tenant-slots:{tenant_id}"


# ─────────────────────────────────────────────────────────────────────────────
# Run lifecycle
# ─────────────────────────────────────────────────────────────────────────────

async def create_run(
    *,
    run_id: str,
    tenant_id: int,
    user_id: int,
    granularity: int,
    cross_project: bool,
    projects: list[dict[str, Any]],
) -> None:
    """Register a run: its metadata and the set of project ids to expect."""
    r = get_redis()
    ttl = _ttl()
    meta = {
        "tenant_id": str(tenant_id),
        "user_id": str(user_id),
        "granularity": str(granularity),
        "cross_project": "1" if cross_project else "0",
        "projects": json.dumps(projects),
    }
    pipe = r.pipeline()
    pipe.hset(_k(run_id, "meta"), mapping=meta)
    pipe.expire(_k(run_id, "meta"), ttl)
    if projects:
        pipe.sadd(_k(run_id, "expected"), *[str(p["id"]) for p in projects])
        pipe.expire(_k(run_id, "expected"), ttl)
    await pipe.execute()


async def get_meta(run_id: str) -> dict[str, Any] | None:
    m = await cast(
        "Awaitable[dict[str, str]]", get_redis().hgetall(_k(run_id, "meta"))
    )
    if not m:
        return None
    return {
        "tenant_id": int(m["tenant_id"]),
        "user_id": int(m["user_id"]),
        "granularity": int(m["granularity"]),
        "cross_project": m["cross_project"] == "1",
        "projects": json.loads(m["projects"]),
    }


async def get_expected(run_id: str) -> set[str]:
    members = await cast(
        "Awaitable[set[str]]", get_redis().smembers(_k(run_id, "expected"))
    )
    return set(members)


async def write_result(
    run_id: str, project_id: int | str, result: dict[str, Any]
) -> None:
    """Persist one project's terminal result and wake any SSE subscriber."""
    r = get_redis()
    ttl = _ttl()
    pipe = r.pipeline()
    pipe.hset(_k(run_id, "results"), str(project_id), json.dumps(result))
    pipe.expire(_k(run_id, "results"), ttl)
    pipe.publish(channel(run_id), str(project_id))
    await pipe.execute()


async def get_results(run_id: str) -> dict[str, dict[str, Any]]:
    raw = await cast(
        "Awaitable[dict[str, str]]", get_redis().hgetall(_k(run_id, "results"))
    )
    return {pid: json.loads(v) for pid, v in raw.items()}


async def is_complete(run_id: str) -> bool:
    """True once every expected project has written a result."""
    expected = await get_expected(run_id)
    if not expected:
        return False
    keys = await cast(
        "Awaitable[list[str]]", get_redis().hkeys(_k(run_id, "results"))
    )
    finished = set(keys)
    return expected <= finished


# ─────────────────────────────────────────────────────────────────────────────
# Per-tenant fairness tokens
# ─────────────────────────────────────────────────────────────────────────────

async def acquire_tenant_slot(tenant_id: int, *, cap: int) -> bool:
    """Try to take one of the tenant's ``cap`` concurrency tokens.

    Returns ``True`` if a token was acquired (caller must
    :func:`release_tenant_slot` in a ``finally``), ``False`` if the tenant is
    already at its cap so the caller should defer and let another tenant run.
    """
    r = get_redis()
    key = _tenant_slots_key(tenant_id)
    held = await r.incr(key)
    # Refresh the TTL each acquire so a leaked counter self-heals.
    await r.expire(key, _TENANT_SLOT_TTL_SECONDS)
    if held > max(1, cap):
        await r.decr(key)
        return False
    return True


async def release_tenant_slot(tenant_id: int) -> None:
    r = get_redis()
    key = _tenant_slots_key(tenant_id)
    held = await r.decr(key)
    if held < 0:
        # Never let the counter drift negative (e.g. after a TTL expiry).
        await r.set(key, 0)


# ─────────────────────────────────────────────────────────────────────────────
# Finalization (exactly-once) + completion signal
# ─────────────────────────────────────────────────────────────────────────────

async def try_claim_finalize(run_id: str) -> bool:
    """Atomically claim the right to finalize a run (synthesis + snapshot).

    Only the first caller after completion wins, so synthesis/snapshot run once
    even when several projects finish near-simultaneously across workers.
    """
    ok = await get_redis().set(
        _k(run_id, "finalized"), "1", nx=True, ex=_ttl()
    )
    return bool(ok)


async def store_synthesis(run_id: str, synthesis: dict[str, Any] | None) -> None:
    """Store the final synthesis (``None`` allowed) — the completion signal."""
    r = get_redis()
    pipe = r.pipeline()
    pipe.set(_k(run_id, "synthesis"), json.dumps(synthesis), ex=_ttl())
    pipe.publish(channel(run_id), "__done__")
    await pipe.execute()


async def get_synthesis(run_id: str) -> tuple[bool, dict[str, Any] | None]:
    """Return ``(stored, synthesis)``; ``stored`` is False until finalized."""
    raw = await get_redis().get(_k(run_id, "synthesis"))
    if raw is None:
        return (False, None)
    return (True, json.loads(raw))


# ─────────────────────────────────────────────────────────────────────────────
# Pub/sub — low-latency wakeups for the SSE consumer (source of truth is the
# results hash, so a missed message only delays a poll tick, never drops data).
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def subscribe(run_id: str) -> AsyncIterator[Any]:
    r = get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(channel(run_id))
    try:
        yield pubsub
    finally:
        try:
            await pubsub.unsubscribe(channel(run_id))
            await pubsub.aclose()
        except Exception:  # pragma: no cover - best-effort cleanup
            pass


async def wait_for_wakeup(pubsub: Any, *, timeout: float) -> None:
    """Wait up to ``timeout`` for a progress message; degrade to a poll tick."""
    import asyncio

    try:
        await pubsub.get_message(ignore_subscribe_messages=True, timeout=timeout)
    except Exception:  # pragma: no cover - pub/sub optional, poll still drives
        await asyncio.sleep(timeout)
