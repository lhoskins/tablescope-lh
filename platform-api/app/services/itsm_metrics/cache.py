"""Small stale-while-revalidate cache for rendered ITSM dashboards.

Teiid already caches result sets. This layer caches the assembled dashboard
payload so navigation can return immediately without repeating metric
orchestration and response serialization.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from time import monotonic

from .models import DashboardResult

FRESH_SECONDS = 300
STALE_SECONDS = 86_400
MAX_ENTRIES = 256


@dataclass
class _Entry:
    result: DashboardResult
    stored_at: float


_entries: OrderedDict[str, _Entry] = OrderedDict()
_entries_lock = Lock()
_refresh_locks: dict[str, asyncio.Lock] = {}


def make_cache_key(
    *,
    tenant_id: int,
    project_id: int,
    dashboard_key: str,
    site_code: str | None,
    as_of: datetime | None,
    duration_unit: str,
    period_key: str | None = None,
) -> str:
    as_of_key = as_of.isoformat() if as_of else "latest-complete-month"
    return ":".join(
        [
            str(tenant_id),
            str(project_id),
            dashboard_key,
            site_code or "all",
            as_of_key,
            duration_unit,
            period_key or "latest_month",
        ]
    )


def _get_entry(key: str) -> tuple[DashboardResult, str, int] | None:
    with _entries_lock:
        entry = _entries.get(key)
        if entry is None:
            return None
        age_seconds = max(0, int(monotonic() - entry.stored_at))
        if age_seconds > STALE_SECONDS:
            _entries.pop(key, None)
            return None
        _entries.move_to_end(key)
        state = "fresh" if age_seconds <= FRESH_SECONDS else "stale"
        return entry.result, state, age_seconds


def set_cached_dashboard(key: str, result: DashboardResult) -> None:
    with _entries_lock:
        _entries[key] = _Entry(result=result, stored_at=monotonic())
        _entries.move_to_end(key)
        while len(_entries) > MAX_ENTRIES:
            _entries.popitem(last=False)


async def get_or_compute_dashboard(
    key: str,
    compute: Callable[[], Awaitable[DashboardResult]],
    *,
    force_refresh: bool = False,
) -> tuple[DashboardResult, str, int]:
    if not force_refresh:
        cached = _get_entry(key)
        if cached is not None:
            return cached

    lock = _refresh_locks.setdefault(key, asyncio.Lock())
    async with lock:
        if not force_refresh:
            cached = _get_entry(key)
            if cached is not None:
                return cached
        result = await compute()
        set_cached_dashboard(key, result)
        return result, "refreshed" if force_refresh else "miss", 0


def clear_dashboard_cache() -> None:
    """Test/support hook; production invalidation normally uses force refresh."""
    with _entries_lock:
        _entries.clear()
