#!/usr/bin/env python3
"""Seed the Industry-tier Reference Library starter catalog.

Reads the verified starter catalog CSV and inserts one metadata-only
``reference_documents`` stub per row (tier='industry', no file yet). This gives
every tenant a populated, browsable Industry Library on day one — entries show
"No document uploaded yet" until a file is uploaded (single upload) or fetched
(bulk import), at which point the stub is filled in rather than duplicated.

Usage (from platform-api root):
    python -m scripts.seed_reference_library

Idempotent: skips rows whose title already exists at the Industry tier.
"""

from __future__ import annotations

import asyncio
import csv
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SEED_CSV = (
    Path(__file__).resolve().parent.parent
    / "app"
    / "seed_data"
    / "reference_library"
    / "industry_starter_catalog.csv"
)


async def seed_reference_library() -> dict[str, int]:
    """Insert Industry-tier starter catalog stubs. Returns counts."""
    from sqlalchemy import func, select

    from app.database import SessionLocal as async_session_factory
    from app.models.reference_library import TIER_INDUSTRY, ReferenceDocument
    from app.services.reference_library_service import normalize_domain_tag

    stats: dict[str, int] = {"created": 0, "skipped": 0}

    if not SEED_CSV.exists():
        logger.warning("Reference library seed CSV not found: %s", SEED_CSV)
        return stats

    with SEED_CSV.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    async with async_session_factory() as session:
        # Existing industry titles (lower-cased) for idempotency.
        existing_titles = {
            (t or "").strip().lower()
            for t in (
                await session.scalars(
                    select(func.lower(ReferenceDocument.title)).where(
                        ReferenceDocument.tier == TIER_INDUSTRY
                    )
                )
            ).all()
        }

        for row in rows:
            title = (row.get("title") or "").strip()
            if not title:
                continue
            if title.lower() in existing_titles:
                stats["skipped"] += 1
                continue
            domain, _ = normalize_domain_tag(row.get("domain_tag"))
            doc = ReferenceDocument(
                tier=TIER_INDUSTRY,
                tenant_id=None,
                project_id=None,
                title=title,
                issuing_body=(row.get("issuing_body") or "").strip() or None,
                domain_tag=domain,
                applicability_tag=(row.get("applicability_tag") or "").strip() or None,
                source_url=(row.get("source_url") or "").strip() or None,
                version_label=(row.get("version_label") or "").strip() or None,
                status="active",
                file_path=None,
            )
            session.add(doc)
            existing_titles.add(title.lower())
            stats["created"] += 1

        await session.commit()

    logger.info("Reference library seed: %s", stats)
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(asyncio.run(seed_reference_library()))
