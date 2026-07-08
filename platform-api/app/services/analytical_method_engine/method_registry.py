"""Runtime method registry — reads only approved+active catalog records.

Never reads Markdown/JSON at runtime; the seed pipeline is the only writer. The
active registry is cached per active version and invalidated when the active
version changes.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytical_method_catalog import (
    STATUS_ACTIVE,
    AnalyticalMethod,
    AnalyticalSharedPolicy,
    MethodCatalog,
    MethodCatalogVersion,
    MethodSelectionMatrix,
)

CATALOG_KEY = "tablescope_analytical_methods"

# Cache keyed by active version id.
_cache: dict[int, dict[str, Any]] = {}


def invalidate_cache() -> None:
    _cache.clear()


async def _active_version_id(session: AsyncSession) -> int | None:
    catalog = await session.scalar(
        select(MethodCatalog).where(
            MethodCatalog.catalog_key == CATALOG_KEY,
            MethodCatalog.is_active.is_(True),
        )
    )
    if catalog is None or catalog.active_version_id is None:
        return None
    version = await session.get(MethodCatalogVersion, catalog.active_version_id)
    if version is None or version.status != STATUS_ACTIVE:
        return None
    return version.id


async def get_active_registry(session: AsyncSession) -> dict[str, Any] | None:
    """Return the cached active registry (methods, matrix, policies) or None."""
    version_id = await _active_version_id(session)
    if version_id is None:
        return None
    if version_id in _cache:
        return _cache[version_id]

    methods = (
        await session.scalars(
            select(AnalyticalMethod).where(
                AnalyticalMethod.catalog_version_id == version_id,
                AnalyticalMethod.status == STATUS_ACTIVE,
                AnalyticalMethod.is_executable.is_(True),
            )
        )
    ).all()
    matrix = (
        await session.scalars(
            select(MethodSelectionMatrix).where(
                MethodSelectionMatrix.catalog_version_id == version_id
            )
        )
    ).all()
    policies = (
        await session.scalars(
            select(AnalyticalSharedPolicy).where(
                AnalyticalSharedPolicy.catalog_version_id == version_id
            )
        )
    ).all()

    registry = {
        "version_id": version_id,
        "methods": {m.method_id: m.to_dict() for m in methods},
        "matrix": [row.to_dict() for row in sorted(matrix, key=lambda r: -r.priority)],
        "policies": {p.policy_key: p.to_dict() for p in policies},
    }
    _cache[version_id] = registry
    return registry


async def get_method(session: AsyncSession, method_id: str) -> dict[str, Any] | None:
    registry = await get_active_registry(session)
    if registry is None:
        return None
    return registry["methods"].get(method_id)


async def find_methods_by_intent(session: AsyncSession, intent: str) -> list[dict[str, Any]]:
    registry = await get_active_registry(session)
    if registry is None:
        return []
    return [m for m in registry["methods"].values() if intent in (m.get("supported_intents") or [])]


async def resolve_selection_matrix(
    session: AsyncSession, intent: str
) -> list[dict[str, Any]]:
    registry = await get_active_registry(session)
    if registry is None:
        return []
    return [row for row in registry["matrix"] if row["analysis_intent"] == intent]


async def get_shared_policy(session: AsyncSession, policy_key: str) -> dict[str, Any] | None:
    registry = await get_active_registry(session)
    if registry is None:
        return None
    return registry["policies"].get(policy_key)
