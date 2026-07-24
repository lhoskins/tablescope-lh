#!/usr/bin/env python3
"""Delete all Business Insight and Project Insight result caches.

Run from the app host after deploying the R-first catalog so that subsequent
requests rebuild cards using the R-first / Python-fallback engine.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import delete, text

from app.database import SessionLocal
from app.models.business_insight_result import BusinessInsightResult
from app.models.project_intelligence_snapshot import ProjectIntelligenceSnapshot

logger = logging.getLogger(__name__)


async def delete_insight_caches() -> dict[str, int]:
    async with SessionLocal() as session:
        async with session.begin():
            r1 = await session.execute(delete(BusinessInsightResult))
            r2 = await session.execute(
                delete(ProjectIntelligenceSnapshot).where(
                    ProjectIntelligenceSnapshot.suite == "project_insight"
                )
            )
            # Reset the sequence to the next free id so later snapshots do not
            # collide with existing rows after the cache is cleared.
            await session.execute(
                text(
                    "SELECT setval(pg_get_serial_sequence('project_intelligence_snapshots', 'id'), "
                    "COALESCE((SELECT MAX(id) FROM project_intelligence_snapshots), 0) + 1, false)"
                )
            )
            business_count = r1.rowcount
            project_count = r2.rowcount
        await session.commit()
    return {"business_insight_results": business_count, "project_insight_snapshots": project_count}


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    counts = asyncio.run(delete_insight_caches())
    logger.info("Deleted insight caches: %s", counts)


if __name__ == "__main__":
    main()
