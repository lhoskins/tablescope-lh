"""Admin mutations for the governed analytical method catalog.

Activation and deactivation operate on the active catalog version and are audited
via ``MethodCatalogAuditLog``. Activation is gated on a real implementation being
available (Python executor or R method).
"""

from __future__ import annotations

import logging
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


def _r_methods_from_service() -> set[str] | None:
    """Query the R analytics service for its available method names.

    Returns None if the service is unreachable so callers can fall back to the
    static allowlist.
    """
    try:
        with httpx.Client(timeout=r_analytics_timeout_seconds()) as client:
            resp = client.get(f"{r_analytics_url()}/methods")
            resp.raise_for_status()
            data = resp.json()
            return set(data.get("methods", []))
    except Exception as exc:
        logger.warning("Could not query r-analytics /methods: %s", exc)
    return None


def available_r_methods() -> set[str]:
    """Return the union of the static allowlist and whatever the service reports."""
    service_methods = _r_methods_from_service()
    if service_methods:
        return _STATIC_R_METHODS | service_methods
    return _STATIC_R_METHODS


def implementation_available(method: AnalyticalMethod) -> bool:
    """True if the method has a bound Python executor or an R implementation."""
    executor_key = method.executor_key or ""
    if method.execution_engine == "r":
        return executor_key in available_r_methods()
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

    method.is_executable = True  # type: ignore[assignment]
    method.status = STATUS_ACTIVE  # type: ignore[assignment]
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

    method.is_executable = False  # type: ignore[assignment]
    method.status = STATUS_DRAFT  # type: ignore[assignment]
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
