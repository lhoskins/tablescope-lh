#!/usr/bin/env python3
"""Delete every insight cache so cards regenerate through the current code.

Run from the app host after a deploy that changes how cards are built. Cards are
cached per user, and a stale cache is indistinguishable from a broken deploy:
the old cards render fine, just without whatever the new code adds.

Three stores back the insight surfaces and **all three must go**:

- ``BusinessInsightResult``          — the per-run card results
- ``IntelligenceSnapshot``           — the tenant-wide snapshot the Business
  Insight feed and the full-analysis route both read
- ``ProjectIntelligenceSnapshot``    — per-project, in two suites: ``insights``
  (Business Insight's per-project cards) and ``project_insight`` (the Project
  Insight page)

Missing any of them leaves a surface serving pre-deploy cards.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import delete, text

from app.database import SessionLocal
from app.models.business_insight_result import BusinessInsightResult
from app.models.intelligence_snapshot import IntelligenceSnapshot
from app.models.project_intelligence_snapshot import ProjectIntelligenceSnapshot

logger = logging.getLogger(__name__)


async def delete_insight_caches() -> dict[str, int]:
    async with SessionLocal() as session:
        async with session.begin():
            r1 = await session.execute(delete(BusinessInsightResult))
            # The tenant-wide snapshot. Omitting this was why a cleared cache
            # still served pre-deploy cards: the feed and the full-analysis
            # route both read from here, not from BusinessInsightResult.
            r_snap = await session.execute(delete(IntelligenceSnapshot))
            # Both suites. `insights` backs Business Insight's per-project
            # cards; `project_insight` backs the Project Insight page. Clearing
            # only one leaves the other surface stale.
            r2 = await session.execute(delete(ProjectIntelligenceSnapshot))
            # Reset the sequence to the next free id so later snapshots do not
            # collide with existing rows after the cache is cleared.
            await session.execute(
                text(
                    "SELECT setval(pg_get_serial_sequence('project_intelligence_snapshots', 'id'), "
                    "COALESCE((SELECT MAX(id) FROM project_intelligence_snapshots), 0) + 1, false)"
                )
            )
            business_count = r1.rowcount
            snapshot_count = r_snap.rowcount
            project_count = r2.rowcount
        await session.commit()
    return {
        "business_insight_results": business_count,
        "intelligence_snapshots": snapshot_count,
        "project_intelligence_snapshots": project_count,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    counts = asyncio.run(delete_insight_caches())
    logger.info("Deleted insight caches: %s", counts)


if __name__ == "__main__":
    main()
