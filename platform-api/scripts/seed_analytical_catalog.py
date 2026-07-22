#!/usr/bin/env python3
"""Seed the Analytical Method Reference Catalog from ``catalog.json``.

Usage (from platform-api root)::

    python -m scripts.seed_analytical_catalog

Governance model:
- The catalog + version are created once (idempotent by catalog_key + version).
- Every method is imported. Tier-1 **executable** methods land ``approved`` +
  ``active`` (runtime-executable). Every other method lands ``draft`` — imported
  and reviewable but never executed until approved. This matches the plan's
  rollout gating (import the whole document, activate only Tier 1 for v1).
- The version is marked ``active`` so the runtime registry can read it, but only
  ``active`` methods within it are executed.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CATALOG_FILE = (
    Path(__file__).resolve().parent.parent
    / "app" / "seed_data" / "analytical_methods" / "catalog.json"
)


async def seed_analytical_catalog() -> dict[str, Any]:
    """Seed and *activate* the analytical catalog idempotently.

    The runtime registry (``method_registry.get_active_registry``) reads *only*
    the version referenced by ``MethodCatalog.active_version_id`` when that
    version's ``status == active`` and the catalog ``is_active``. Seeding the
    rows is therefore not enough — production also needs the catalog *activated*
    at startup with no manual admin step. This routine:

    - creates the catalog + version + methods once (idempotent by version), and
    - on **every** boot ensures the seeded version is the active one (status
      ``active``, system-approved ``approved_at``, ``catalog.active_version_id``
      pointing at it, ``is_active`` true) — repairing a half-activated state
      from a prior partial boot without ever creating a duplicate version.

    Returns an activation-status dict (``version_id``, ``active``, method /
    executable counts) so startup can log whether hybrid is actually live.
    """
    from sqlalchemy import func as sa_func
    from sqlalchemy import select

    from app.database import SessionLocal as async_session_factory
    from app.models.analytical_method_catalog import (
        STATUS_ACTIVE,
        STATUS_DRAFT,
        AnalyticalMethod,
        AnalyticalSharedPolicy,
        MethodCatalog,
        MethodCatalogVersion,
        MethodSelectionMatrix,
    )
    from app.services.analytical_method_engine import method_registry

    stats: dict[str, Any] = {
        "methods": 0,
        "executable": 0,
        "policies": 0,
        "matrix": 0,
        "skipped": 0,
        "version_id": None,
        "active": False,
    }

    async def _counts(version_id: int) -> tuple[int, int]:
        total = await session.scalar(
            select(sa_func.count()).select_from(AnalyticalMethod).where(
                AnalyticalMethod.catalog_version_id == version_id
            )
        )
        executable = await session.scalar(
            select(sa_func.count()).select_from(AnalyticalMethod).where(
                AnalyticalMethod.catalog_version_id == version_id,
                AnalyticalMethod.is_executable.is_(True),
                AnalyticalMethod.status == STATUS_ACTIVE,
            )
        )
        return int(total or 0), int(executable or 0)

    def _ensure_active(cat: MethodCatalog, ver: MethodCatalogVersion) -> bool:
        """Idempotently make ``ver`` the active version of ``cat``. Returns True
        if anything changed (so the caller knows to commit + invalidate)."""
        changed = False
        if ver.status != STATUS_ACTIVE:
            ver.status = STATUS_ACTIVE
            changed = True
        if ver.approved_at is None:
            # System approval: no human approver, but stamp the approval time so
            # the governed lifecycle (draft->…->approved->active) is satisfied.
            ver.approved_at = datetime.now(UTC)
            changed = True
        if not cat.is_active:
            cat.is_active = True
            changed = True
        if cat.active_version_id != ver.id:
            cat.active_version_id = ver.id
            changed = True
        return changed

    if not CATALOG_FILE.exists():
        logger.warning("Analytical catalog file not found: %s", CATALOG_FILE)
        return stats

    data = json.loads(CATALOG_FILE.read_text())
    catalog_key = data["catalog_key"]
    version_str = data.get("version", "1.0")

    async with async_session_factory() as session:
        catalog = await session.scalar(
            select(MethodCatalog).where(MethodCatalog.catalog_key == catalog_key)
        )
        if catalog is None:
            catalog = MethodCatalog(
                catalog_key=catalog_key,
                name=data["name"],
                description=data.get("description"),
                source_document=data.get("source_document"),
                is_system=True,
                is_active=True,
            )
            session.add(catalog)
            await session.flush()

        version = await session.scalar(
            select(MethodCatalogVersion).where(
                MethodCatalogVersion.catalog_id == catalog.id,
                MethodCatalogVersion.version == version_str,
            )
        )
        if version is not None:
            # Rows already seeded — do NOT re-insert. But still guarantee the
            # version is activated (repairs a partial prior boot); idempotent.
            changed = _ensure_active(catalog, version)
            if changed:
                await session.commit()
                method_registry.invalidate_cache()
            total, executable = await _counts(int(version.id))
            stats.update(
                skipped=1,
                version_id=int(version.id),
                active=True,
                methods=total,
                executable=executable,
            )
            logger.info(
                "Analytical catalog %s v%s already seeded; active version_id=%s "
                "(methods=%s, executable=%s, activation_repaired=%s)",
                catalog_key, version_str, version.id, total, executable, changed,
            )
            return stats

        # Capture activation overrides from the previous active version so a
        # catalog version bump does not silently discard admin toggles.
        previous_by_id: dict[str, dict[str, Any]] = {}
        if catalog.active_version_id:
            prev_methods = (
                await session.scalars(
                    select(AnalyticalMethod).where(
                        AnalyticalMethod.catalog_version_id == catalog.active_version_id
                    )
                )
            ).all()
            previous_by_id = {
                str(m.method_id): {"is_executable": m.is_executable, "status": m.status}
                for m in prev_methods
            }

        version = MethodCatalogVersion(
            catalog_id=catalog.id,
            version=version_str,
            status=STATUS_ACTIVE,
            notes="Initial seed from source taxonomy; Tier-1 activated.",
        )
        session.add(version)
        await session.flush()

        for m in data.get("methods", []):
            executable = bool(m.get("is_executable"))
            status = STATUS_ACTIVE if executable else STATUS_DRAFT
            if m["method_id"] in previous_by_id:
                prev = previous_by_id[m["method_id"]]
                executable = bool(prev["is_executable"])
                status = prev["status"]
            session.add(
                AnalyticalMethod(
                    catalog_version_id=version.id,
                    method_id=m["method_id"],
                    display_name=m["display_name"],
                    category=m.get("category"),
                    subcategory=m.get("subcategory"),
                    tier=m.get("tier", 2),
                    status=status,
                    summary=m.get("summary"),
                    applicability_condition=m.get("applicability_condition"),
                    supported_intents=m.get("supported_intents", []),
                    selection_rules=m.get("selection_rules", []),
                    rejection_rules=m.get("rejection_rules", []),
                    required_checks=m.get("required_checks", []),
                    fallback_methods=m.get("fallback_methods", []),
                    output_contract=m.get("output_contract", {}),
                    method_card=m.get("method_card", {}),
                    llm_guardrails=m.get("llm_guardrails", []),
                    executor_key=m.get("executor_key"),
                    execution_engine=m.get("execution_engine", "python"),
                    result_schema_version=m.get("result_schema_version", 1),
                    chart_contract=m.get("chart_contract", {}),
                    max_rows=m.get("max_rows"),
                    timeout_seconds=m.get("timeout_seconds"),
                    dependencies=m.get("dependencies", []),
                    is_executable=executable,
                )
            )
            stats["methods"] += 1
            if executable:
                stats["executable"] += 1

        for p in data.get("shared_policies", []):
            session.add(
                AnalyticalSharedPolicy(
                    catalog_version_id=version.id,
                    policy_key=p["policy_key"],
                    name=p["name"],
                    description=p.get("description"),
                    rules=p.get("rules", {}),
                )
            )
            stats["policies"] += 1

        for row in data.get("selection_matrix", []):
            session.add(
                MethodSelectionMatrix(
                    catalog_version_id=version.id,
                    analysis_intent=row["analysis_intent"],
                    data_profile=row.get("data_profile"),
                    primary_method_id=row["primary_method_id"],
                    alternative_method_ids=row.get("alternative_method_ids", []),
                    priority=row.get("priority", 100),
                )
            )
            stats["matrix"] += 1

        version.method_count = int(stats["methods"])
        # Version itself is active so the registry can read it; only active
        # methods within it are executed. Activate + system-approve so
        # get_active_registry() returns a live registry with no admin step.
        _ensure_active(catalog, version)
        await session.commit()
        method_registry.invalidate_cache()
        stats.update(version_id=int(version.id), active=True)

    logger.info("Analytical catalog seed complete: %s", stats)
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(seed_analytical_catalog())
