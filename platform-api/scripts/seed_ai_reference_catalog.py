#!/usr/bin/env python3
"""Seed the AI reference catalog tables from JSON pack files.

Usage (from platform-api root):
    python -m scripts.seed_ai_reference_catalog

Idempotent: skips catalogs/tags/KPIs that already exist (matched by key).
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SEED_DIR = Path(__file__).resolve().parent.parent / "app" / "seed_data" / "ai_catalogs"

PACK_FILES = [
    "tablescope_core.json",
    "supply_chain.json",
    "manufacturing.json",
    "finance.json",
    "healthcare.json",
    "government.json",
    "information_technology.json",
]


async def seed_catalogs() -> dict[str, int]:
    """Insert reference catalog data. Returns counts."""
    from sqlalchemy import select

    from app.database import SessionLocal as async_session_factory
    from app.models.ai_reference_catalog import (
        AIReferenceCatalog,
        AIReferenceKPI,
        AIReferenceTag,
    )

    stats: dict[str, int] = {"catalogs": 0, "tags": 0, "kpis": 0, "skipped": 0}

    async with async_session_factory() as session:
        for pack_file in PACK_FILES:
            path = SEED_DIR / pack_file
            if not path.exists():
                logger.warning("Pack file not found: %s", path)
                continue

            data = json.loads(path.read_text())
            catalog_key = data["catalog_key"]

            new_version = data.get("version", "1.0")
            existing = await session.scalar(
                select(AIReferenceCatalog).where(AIReferenceCatalog.catalog_key == catalog_key)
            )
            if existing and existing.version == new_version:
                logger.info("Catalog '%s' v%s up to date, skipping", catalog_key, new_version)
                stats["skipped"] += 1
                continue

            if existing:
                logger.info("Catalog '%s' upgrading %s -> %s", catalog_key, existing.version, new_version)
                old_tags = (await session.scalars(
                    select(AIReferenceTag).where(AIReferenceTag.catalog_id == existing.id)
                )).all()
                for ot in old_tags:
                    await session.delete(ot)
                old_kpis = (await session.scalars(
                    select(AIReferenceKPI).where(AIReferenceKPI.catalog_id == existing.id)
                )).all()
                for ok in old_kpis:
                    await session.delete(ok)
                existing.version = new_version  # type: ignore[assignment]
                existing.name = data["name"]  # type: ignore[assignment]
                existing.description = data.get("description")  # type: ignore[assignment]
                catalog = existing
            else:
                catalog = AIReferenceCatalog(
                    catalog_key=catalog_key,
                    name=data["name"],
                    description=data.get("description"),
                    industry=data.get("industry"),
                    source_framework=data.get("source_framework"),
                    version=new_version,
                    is_system=True,
                    is_active=True,
                )
                session.add(catalog)
            await session.flush()
            stats["catalogs"] += 1

            for tag_data in data.get("tags", []):
                tag = AIReferenceTag(
                    catalog_id=catalog.id,
                    tag_key=tag_data["tag_key"],
                    display_name=tag_data["display_name"],
                    description=tag_data.get("description"),
                    industry=data.get("industry"),
                    business_domain=tag_data.get("business_domain"),
                    process_area=tag_data.get("process_area"),
                    synonyms=tag_data.get("synonyms", []),
                    related_tags=tag_data.get("related_tags", []),
                    example_fields=tag_data.get("example_fields", []),
                )
                session.add(tag)
                stats["tags"] += 1

            for kpi_data in data.get("kpis", []):
                kpi = AIReferenceKPI(
                    catalog_id=catalog.id,
                    kpi_key=kpi_data["kpi_key"],
                    display_name=kpi_data["display_name"],
                    description=kpi_data.get("description"),
                    industry=data.get("industry"),
                    business_domain=kpi_data.get("business_domain"),
                    process_area=kpi_data.get("process_area"),
                    formula=kpi_data.get("formula"),
                    required_fields=kpi_data.get("required_fields", []),
                    optional_fields=kpi_data.get("optional_fields", []),
                    related_tags=kpi_data.get("related_tags", []),
                    recommended_chart_type=kpi_data.get("recommended_chart_type"),
                    recommended_aggregations=kpi_data.get("recommended_aggregations", []),
                    example_sql_template=kpi_data.get("example_sql_template"),
                )
                session.add(kpi)
                stats["kpis"] += 1

        await session.commit()

    logger.info("Seed complete: %s", stats)
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(seed_catalogs())
