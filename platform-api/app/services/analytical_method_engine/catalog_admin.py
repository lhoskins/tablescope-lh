"""Admin mutations for the governed analytical method catalog.

Activation and deactivation operate on the active catalog version and are audited
via ``MethodCatalogAuditLog``. Activation is gated on a real implementation being
available (Python executor or R method).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytical_method_catalog import (
    STATUS_ACTIVE,
    STATUS_DRAFT,
    AnalyticalMethod,
    MethodCatalogAuditLog,
)
from app.services.analytical_method_engine import method_executor, method_registry
from app.services.analytical_method_engine.r_config import (
    r_analytics_timeout_seconds,
    r_analytics_url,
)

logger = logging.getLogger(__name__)

# Static fallback allowlist for R methods (the curated Set A + Set B keys).
_STATIC_R_METHODS: set[str] = {
    "describe_numeric",
    "normality_test",
    "pearson_correlation",
    "spearman_correlation",
    "kendall_correlation",
    "one_sample_t_test",
    "welch_t_test",
    "students_t_test",
    "mann_whitney_u",
    "paired_t_test",
    "wilcoxon_signed_rank",
    "one_way_anova",
    "welch_anova",
    "kruskal_wallis",
    "chi_square_independence",
    "fisher_exact",
    "linear_regression",
    "logistic_regression",
    "poisson_regression",
    "negative_binomial_regression",
    "trend_slope",
    "mann_kendall_trend",
    "sens_slope",
    "stl_decomposition",
    "period_change",
    "detect_change_point",
    "detect_anomalies",
    "forecast_time_series",
    "contribution_to_change",
}


# Cached service method list: (methods_set, timestamp_seconds).  The list is
# stable, so a short TTL keeps the admin UI responsive while still reacting to
# a redeployed r-analytics container that exposes new methods.
_r_methods_cache: tuple[set[str], float] | None = None
_R_METHODS_CACHE_TTL_SECONDS = 10.0
_r_methods_lock = threading.Lock()


def _r_methods_from_service() -> set[str] | None:
    """Query the R analytics service for its available method names.

    Returns None if the service is unreachable so callers can fall back to the
    static allowlist. A short timeout keeps an unreachable service from hanging
    the admin activation flow.
    """
    from app.services.analytical_method_engine.r_config import is_r_analytics_enabled

    if not is_r_analytics_enabled():
        return None
    try:
        timeout = min(5.0, float(r_analytics_timeout_seconds()))
    except (TypeError, ValueError):
        timeout = 5.0
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(f"{r_analytics_url()}/methods")
            resp.raise_for_status()
            data = resp.json()
            return set(data.get("methods", []))
    except Exception as exc:
        logger.warning("Could not query r-analytics /methods: %s", exc)
    return None


def available_r_methods() -> set[str]:
    """Return the union of the static allowlist and whatever the service reports.

    If the service is unreachable, the last known good list is reused when
    available, and the static allowlist is always included so a transient R
    service outage does not hard-disable every R method toggle.
    """
    global _r_methods_cache
    with _r_methods_lock:
        if _r_methods_cache is not None:
            methods, ts = _r_methods_cache
            if time.monotonic() - ts < _R_METHODS_CACHE_TTL_SECONDS:
                return methods

    service_methods = _r_methods_from_service()
    with _r_methods_lock:
        if service_methods is not None:
            _r_methods_cache = (_STATIC_R_METHODS | service_methods, time.monotonic())
            return _r_methods_cache[0]
        if _r_methods_cache is not None:
            # Service is down but we have a stale cache; prefer it over dropping
            # all R methods to "unavailable".
            return _r_methods_cache[0]
        return _STATIC_R_METHODS


def implementation_available(method: AnalyticalMethod) -> bool:
    """True if the method can actually be executed right now.

    R-first methods are considered available when either a Python twin exists
    (so they can run even if R is disabled) or when R is enabled and the
    service reports the method.  This keeps ``R_ANALYTICS_ENABLED=false``
    equivalent to the pre-R Python-only behavior.
    """
    from app.services.analytical_method_engine.r_config import is_r_analytics_enabled

    executor_key = method.executor_key or ""
    if method.execution_engine == "r":
        if executor_key in method_executor.EXECUTORS:
            return True
        if is_r_analytics_enabled() and executor_key in available_r_methods():
            return True
        return False
    return executor_key in method_executor.EXECUTORS


async def activate_method(
    session: AsyncSession, method_id: str, actor_user_id: int | None = None
) -> dict[str, Any]:
    """Activate a method on the active catalog version.

    Returns the updated method dict or raises ValueError when the method cannot
    be activated (no implementation, already active, etc.).
    """
    from app.services.analytical_method_engine.catalog_browser import _active_version

    version = await _active_version(session)
    if version is None:
        raise ValueError("No active analytical method catalog")

    method = await session.scalar(
        select(AnalyticalMethod).where(
            AnalyticalMethod.catalog_version_id == version.id,
            AnalyticalMethod.method_id == method_id,
        )
    )
    if method is None:
        raise ValueError(f"Method {method_id} not found in active catalog")

    if method.is_executable and method.status == STATUS_ACTIVE:
        return method.to_dict()

    if not implementation_available(method):
        raise ValueError(f"No implementation available for {method_id}")

    method.is_executable = True
    method.status = STATUS_ACTIVE
    session.add(
        MethodCatalogAuditLog(
            tenant_id=None,
            catalog_version_id=version.id,
            method_id=method_id,
            event_type="activated",
            selected_method=method_id,
            reason=f"Activated by user {actor_user_id}",
        )
    )
    await session.commit()
    method_registry.invalidate_cache()
    return method.to_dict()


async def deactivate_method(
    session: AsyncSession, method_id: str, actor_user_id: int | None = None
) -> dict[str, Any]:
    """Deactivate a method on the active catalog version."""
    from app.services.analytical_method_engine.catalog_browser import _active_version

    version = await _active_version(session)
    if version is None:
        raise ValueError("No active analytical method catalog")

    method = await session.scalar(
        select(AnalyticalMethod).where(
            AnalyticalMethod.catalog_version_id == version.id,
            AnalyticalMethod.method_id == method_id,
        )
    )
    if method is None:
        raise ValueError(f"Method {method_id} not found in active catalog")

    method.is_executable = False
    method.status = STATUS_DRAFT
    session.add(
        MethodCatalogAuditLog(
            tenant_id=None,
            catalog_version_id=version.id,
            method_id=method_id,
            event_type="deactivated",
            selected_method=method_id,
            reason=f"Deactivated by user {actor_user_id}",
        )
    )
    await session.commit()
    method_registry.invalidate_cache()
    return method.to_dict()
