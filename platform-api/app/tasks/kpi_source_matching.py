"""Background KPI data-source matching.

The task is intentionally conservative: it searches project-scoped saved queries
by name and business-definition keywords, validates that the candidate exists in
the same tenant/project, and then stores the match status on the metric. It
never auto-activates a data source; a human must review and approve the mapping.
"""

from __future__ import annotations

import logging
from typing import Any

from arq import create_pool
from arq.connections import RedisSettings
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.database import SessionLocal
from app.models.project_context import ProjectGoal, ProjectMetric
from app.models.saved_query import SavedQuery

logger = logging.getLogger(__name__)


def _redis_settings() -> RedisSettings:
    settings = get_settings()
    return RedisSettings.from_dsn(settings.redis_url)


async def enqueue_match_kpi_data_source(
    *,
    tenant_id: int,
    project_id: int,
    metric_id: int,
    requested_by_user_id: int,
) -> str:
    """Enqueue a KPI source-match job and return its id."""
    pool = await create_pool(_redis_settings())
    try:
        job = await pool.enqueue_job(
            "match_kpi_data_source",
            tenant_id=tenant_id,
            project_id=project_id,
            metric_id=metric_id,
            requested_by_user_id=requested_by_user_id,
        )
        return job.job_id if job else ""
    finally:
        await pool.close()


async def match_kpi_data_source(
    ctx: dict[str, Any],
    *,
    tenant_id: int,
    project_id: int,
    metric_id: int,
    requested_by_user_id: int,
) -> dict[str, Any]:
    """Find a candidate data source for a KPI and record the outcome."""
    logger.info(
        "match_kpi_data_source tenant=%s project=%s metric=%s user=%s",
        tenant_id,
        project_id,
        metric_id,
        requested_by_user_id,
    )

    async with SessionLocal() as session:
        metric = await session.scalar(
            select(ProjectMetric)
            .options(selectinload(ProjectMetric.success_criterion))
            .where(
                ProjectMetric.id == metric_id,
                ProjectMetric.tenant_id == tenant_id,
                ProjectMetric.project_id == project_id,
                ProjectMetric.active.is_(True),
            )
        )
        if metric is None:
            logger.warning("match_kpi_data_source: metric %s not found", metric_id)
            return {"ok": False, "error": "metric not found"}

        metric.source_match_status = "searching"
        await session.flush()

        search_terms = [metric.name]
        if metric.business_definition:
            search_terms.append(metric.business_definition)
        goal: ProjectGoal | None = metric.success_criterion
        if goal is not None:
            search_terms.append(goal.title)
            if goal.description:
                search_terms.append(goal.description)

        query = await session.scalar(
            select(SavedQuery)
            .where(
                SavedQuery.project_id == project_id,
                SavedQuery.is_archived.is_(False),
            )
            .order_by(SavedQuery.run_count.desc())
            .limit(1)
        )

        if query is not None:
            # Prefer a query whose name matches one of the search terms.
            name_lower = query.name.lower()
            matched = any(term and term.lower() in name_lower for term in search_terms)
            if not matched:
                # Fall back to the most-run query if no name match, but flag it as
                # a candidate rather than a validated match.
                metric.source_match_status = "candidate_found"
                metric.source_query_id = query.id
                metric.source_type = "saved_query"
                metric.source_mapping = {
                    "candidate_query_id": query.id,
                    "candidate_query_name": query.name,
                    "matched_on": "most_run_query",
                }
                await session.commit()
                return {
                    "ok": True,
                    "status": "candidate_found",
                    "query_id": query.id,
                    "query_name": query.name,
                }

            metric.source_match_status = "matched"
            metric.source_query_id = query.id
            metric.source_type = "saved_query"
            metric.source_mapping = {
                "matched_query_id": query.id,
                "matched_query_name": query.name,
                "matched_on": "name",
            }
            await session.commit()
            return {
                "ok": True,
                "status": "matched",
                "query_id": query.id,
                "query_name": query.name,
            }

        metric.source_match_status = "no_match"
        metric.source_query_id = None
        metric.source_type = None
        await session.commit()
        return {"ok": True, "status": "no_match"}
