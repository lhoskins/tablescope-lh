"""Read-only browsing of the governed method catalog for the admin surface.

Unlike ``method_registry`` (which only ever exposes ``approved`` + ``active`` +
executable methods to the runtime), this module surfaces the *whole* active
version — every tier and lifecycle status — so an operator can see what the
catalog contains and which methods are live. It never writes.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytical_method_catalog import (
    AnalyticalMethod,
    MethodCatalog,
    MethodCatalogVersion,
)
from app.services.analytical_method_engine import method_executor
from app.services.analytical_method_engine.method_registry import CATALOG_KEY

# Static R method allowlist (Set A + Set B) for the admin implementation badge.
_STATIC_R_METHODS: set[str] = {
    "describe_numeric", "normality_test",
    "pearson_correlation", "spearman_correlation", "kendall_correlation",
    "one_sample_t_test", "welch_t_test", "students_t_test",
    "mann_whitney_u", "paired_t_test", "wilcoxon_signed_rank",
    "one_way_anova", "welch_anova", "kruskal_wallis",
    "chi_square_independence", "fisher_exact",
    "linear_regression", "logistic_regression", "poisson_regression", "negative_binomial_regression",
    "trend_slope", "mann_kendall_trend", "sens_slope", "stl_decomposition",
    "period_change", "detect_change_point", "detect_anomalies",
    "forecast_time_series", "contribution_to_change",
}


def _implementation_available(method: AnalyticalMethod) -> bool:
    executor_key = method.executor_key or ""
    if method.execution_engine == "r":
        return executor_key in _STATIC_R_METHODS
    return executor_key in method_executor.EXECUTORS


async def _active_version(session: AsyncSession) -> MethodCatalogVersion | None:
    catalog = await session.scalar(
        select(MethodCatalog).where(MethodCatalog.catalog_key == CATALOG_KEY)
    )
    if catalog is None:
        return None
    if catalog.active_version_id is not None:
        version = await session.get(MethodCatalogVersion, catalog.active_version_id)
        if version is not None:
            return version
    # Fall back to the newest version so the admin can inspect a catalog that
    # was imported but not yet activated.
    return await session.scalar(
        select(MethodCatalogVersion)
        .where(MethodCatalogVersion.catalog_id == catalog.id)
        .order_by(MethodCatalogVersion.id.desc())
    )


def _method_summary(m: AnalyticalMethod) -> dict[str, Any]:
    """A compact card for list views — omits the heavy rule/contract blobs."""
    return {
        "id": m.id,
        "method_id": m.method_id,
        "display_name": m.display_name,
        "category": m.category,
        "subcategory": m.subcategory,
        "tier": m.tier,
        "status": m.status,
        "summary": m.summary,
        "supported_intents": m.supported_intents or [],
        "is_executable": m.is_executable,
        "execution_engine": m.execution_engine,
        "executor_key": m.executor_key,
        "implementation_available": _implementation_available(m),
    }


async def get_catalog_overview(session: AsyncSession) -> dict[str, Any] | None:
    """Catalog + active version metadata with tier/status/category breakdowns."""
    catalog = await session.scalar(
        select(MethodCatalog).where(MethodCatalog.catalog_key == CATALOG_KEY)
    )
    if catalog is None:
        return None
    version = await _active_version(session)
    if version is None:
        return {**catalog.to_dict(), "version": None, "methods_total": 0}

    rows = (
        await session.scalars(
            select(AnalyticalMethod).where(
                AnalyticalMethod.catalog_version_id == version.id
            )
        )
    ).all()

    by_tier: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_category: dict[str, int] = {}
    executable = 0
    for m in rows:
        by_tier[f"tier_{m.tier}"] = by_tier.get(f"tier_{m.tier}", 0) + 1
        by_status[str(m.status)] = by_status.get(str(m.status), 0) + 1
        cat = str(m.category) if m.category else "Uncategorized"
        by_category[cat] = by_category.get(cat, 0) + 1
        if m.is_executable:
            executable += 1

    return {
        **catalog.to_dict(),
        "version": version.to_dict(),
        "methods_total": len(rows),
        "executable_total": executable,
        "by_tier": by_tier,
        "by_status": by_status,
        "by_category": dict(sorted(by_category.items())),
    }


async def list_methods(
    session: AsyncSession,
    *,
    tier: int | None = None,
    status: str | None = None,
    category: str | None = None,
    query: str | None = None,
    executable: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Paginated, filterable list of method cards for the active version."""
    version = await _active_version(session)
    if version is None:
        return {"total": 0, "limit": limit, "offset": offset, "methods": []}

    conditions = [AnalyticalMethod.catalog_version_id == version.id]
    if tier is not None:
        conditions.append(AnalyticalMethod.tier == tier)
    if status:
        conditions.append(AnalyticalMethod.status == status)
    if category:
        conditions.append(AnalyticalMethod.category == category)
    if executable is not None:
        conditions.append(AnalyticalMethod.is_executable.is_(executable))
    if query:
        like = f"%{query.lower()}%"
        conditions.append(
            func.lower(AnalyticalMethod.display_name).like(like)
            | func.lower(AnalyticalMethod.method_id).like(like)
            | func.lower(func.coalesce(AnalyticalMethod.summary, "")).like(like)
        )

    total = await session.scalar(
        select(func.count()).select_from(AnalyticalMethod).where(*conditions)
    )
    rows = (
        await session.scalars(
            select(AnalyticalMethod)
            .where(*conditions)
            .order_by(
                AnalyticalMethod.tier.asc(),
                AnalyticalMethod.display_name.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()

    return {
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
        "methods": [_method_summary(m) for m in rows],
    }


async def get_method_detail(
    session: AsyncSession, method_id: str
) -> dict[str, Any] | None:
    """Full method record (all rules/contracts/cards) by its ``method_id``."""
    version = await _active_version(session)
    if version is None:
        return None
    method = await session.scalar(
        select(AnalyticalMethod).where(
            AnalyticalMethod.catalog_version_id == version.id,
            AnalyticalMethod.method_id == method_id,
        )
    )
    return method.to_dict() if method is not None else None
