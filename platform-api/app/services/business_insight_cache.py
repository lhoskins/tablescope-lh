"""Tenant-shared per-project Business Insight result cache.

A project's insight cards are expensive (plan → execute SQL → interpret), but
identical for every user who can open the project, so they are cached once per
(tenant, project, granularity) and keyed to the Knowledge Graph version the
analysis was built against. Freshness = the cached ``kg_version_id`` still
matches the project's active graph version AND the row is younger than the
TTL safety net. Both helpers are fail-open: a cache failure means a normal
uncached analysis, never a failed run.

Access control stays with the callers: rows are only served after the
existing project access check, so the cache never widens visibility.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import BusinessInsightResult, KnowledgeGraph

logger = logging.getLogger(__name__)

# Bump when the analysis pipeline's output quality changes (prompt fixes,
# planner behavior, card shape) so cached cards built by the older pipeline
# are treated as stale instead of being served until their KG version drifts
# or the TTL expires. Rows without a version (or with an older one) miss.
#   2: planner regression fix — relationship-analysis floor, additive KG
#      hypotheses framing, larger plan context window.
#   3: resolved the join contradiction — Teiid rules and the mandatory
#      relationship SQL shape now explicitly allow verified two-table joins,
#      so planners stop borrowing columns into single-table queries and
#      multi-table cards survive validation.
#   4: ported the PR #44/#47/#48/#49 multi-table stack — tiered relationship
#      evidence, per-pair join budgets with a join-protecting parse slice,
#      truncated-JSON salvage, join-preserving SQL repair, and uncapped
#      multi-table ranking.
ANALYSIS_VERSION = 4


async def _active_kg_version_id(
    session: AsyncSession, *, tenant_id: int, project_id: int
) -> int | None:
    graph = await session.scalar(
        select(KnowledgeGraph).where(
            KnowledgeGraph.tenant_id == tenant_id,
            KnowledgeGraph.project_id == project_id,
        )
    )
    return graph.active_version_id if graph else None


async def get_fresh_result(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
    granularity: int,
) -> list[dict[str, Any]] | None:
    """Return the cached cards for a project, or ``None`` when absent/stale."""
    try:
        row = await session.scalar(
            select(BusinessInsightResult).where(
                BusinessInsightResult.tenant_id == tenant_id,
                BusinessInsightResult.project_id == project_id,
                BusinessInsightResult.granularity == granularity,
            )
        )
        if row is None:
            return None

        ttl = timedelta(
            seconds=max(0, get_settings().business_insight_result_ttl_seconds)
        )
        built_at = row.updated_at
        if built_at is not None and built_at.tzinfo is None:
            built_at = built_at.replace(tzinfo=UTC)
        if built_at is None or datetime.now(UTC) - built_at > ttl:
            return None

        active_version_id = await _active_kg_version_id(
            session, tenant_id=tenant_id, project_id=project_id
        )
        if row.kg_version_id != active_version_id:
            return None

        payload = row.payload or {}
        if payload.get("analysis_version") != ANALYSIS_VERSION:
            return None

        cards = payload.get("insights")
        return cards if isinstance(cards, list) else None
    except Exception:
        logger.exception(
            "business insight cache read failed (tenant=%s project=%s)",
            tenant_id,
            project_id,
        )
        return None


async def store_result(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
    granularity: int,
    cards: list[dict[str, Any]],
    built_by: int | None,
) -> None:
    """Upsert the project's cached cards, keyed to the active KG version.

    Best-effort: failures are logged and swallowed so cache persistence can
    never fail the analysis that produced the cards.
    """
    try:
        active_version_id = await _active_kg_version_id(
            session, tenant_id=tenant_id, project_id=project_id
        )
        fingerprint: str | None = None
        graph = await session.scalar(
            select(KnowledgeGraph).where(
                KnowledgeGraph.tenant_id == tenant_id,
                KnowledgeGraph.project_id == project_id,
            )
        )
        if graph is not None:
            fingerprint = graph.current_source_fingerprint

        row = await session.scalar(
            select(BusinessInsightResult).where(
                BusinessInsightResult.tenant_id == tenant_id,
                BusinessInsightResult.project_id == project_id,
                BusinessInsightResult.granularity == granularity,
            )
        )
        if row is None:
            row = BusinessInsightResult(
                tenant_id=tenant_id,
                project_id=project_id,
                granularity=granularity,
            )
            session.add(row)
        row.kg_version_id = active_version_id
        row.source_fingerprint = fingerprint
        row.payload = {"insights": cards, "analysis_version": ANALYSIS_VERSION}
        row.built_by = built_by
        # Freshness is judged on updated_at; touch it explicitly so an upsert
        # that changes nothing else still renews the TTL window.
        row.updated_at = datetime.now(UTC)
        await session.commit()
    except Exception:
        logger.exception(
            "business insight cache write failed (tenant=%s project=%s)",
            tenant_id,
            project_id,
        )
        try:
            await session.rollback()
        except Exception:  # pragma: no cover - defensive
            pass
