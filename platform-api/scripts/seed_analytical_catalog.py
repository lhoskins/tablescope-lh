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
from pathlib import Path

logger = logging.getLogger(__name__)

CATALOG_FILE = (
    Path(__file__).resolve().parent.parent
    / "app" / "seed_data" / "analytical_methods" / "catalog.json"
)


async def seed_analytical_catalog() -> dict[str, int]:
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

    stats = {"methods": 0, "executable": 0, "policies": 0, "matrix": 0, "skipped": 0}

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
            logger.info("Analytical catalog %s v%s already seeded", catalog_key, version_str)
            stats["skipped"] = 1
            return stats

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

        version.method_count = stats["methods"]  # type: ignore[assignment]
        catalog.active_version_id = version.id
        # Version itself is active so the registry can read it; only active
        # methods within it are executed.
        await session.commit()

    logger.info("Analytical catalog seed complete: %s", stats)
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(seed_analytical_catalog())
