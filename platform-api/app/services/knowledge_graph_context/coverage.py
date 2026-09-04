"""KG-11 / KG-15: an explicit per-source-type coverage manifest for a build.

``collect_structural_graph`` silently caps each source kind at ``_MAX_PER_KIND``
records, and per-source ingestion status (a document still profiling, a file
source stuck pending, a database connection that never tested successfully)
was invisible at the graph-build level -- a build could succeed while quietly
omitting sources that were truncated, still processing, or failed. This module
counts, per source type, exactly what the review's item #11 and #15 ask for:
how many exist in total, how many made it into the graph, how many were
excluded by the per-kind cap, and how many are failed/pending -- so that
information rides along on every build's ``validation_summary`` instead of
being concealed by an overall "succeeded" status.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dashboard import Dashboard
from app.models.database_data_source import DatabaseDataSource
from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project
from app.models.project_asset import ProjectAsset
from app.models.reference_library import (
    TIER_COMPANY,
    TIER_INDUSTRY,
    TIER_PROJECT,
    ReferenceDocument,
)
from app.models.saved_query import SavedQuery

from .graph_primitives import _MAX_PER_KIND

# ProjectAsset.ai_status values reached while a document is still being
# processed (see document_processing_service) -- not yet a terminal
# success/failure.
_ASSET_PENDING_STATUSES = {"pending", "profiling", "extracting", "chunking"}
_ASSET_FAILED_STATUSES = {"failed"}


async def _all_statuses(session: AsyncSession, stmt: Any) -> list[Any]:
    """Return every status value for a query selecting a single status-like
    column, across the *whole* matching population -- failed/pending counts
    must reflect every source, not just the ones a build's per-kind cap would
    include, or a failure past the cap would stay invisible."""
    return list((await session.execute(stmt)).scalars().all())


def _bucket(statuses: list[Any], *, pending: set[str], failed: set[str]) -> dict[str, int]:
    total = len(statuses)
    return {
        "total": total,
        "included": min(total, _MAX_PER_KIND),
        "excluded": max(0, total - _MAX_PER_KIND),
        "failed": sum(1 for s in statuses if s in failed),
        "pending": sum(1 for s in statuses if s in pending),
    }


async def compute_source_coverage(
    session: AsyncSession, *, tenant_id: int, project_id: int,
) -> dict[str, dict[str, int]]:
    """Return a ``{source_type: {total, included, excluded, failed, pending}}``
    manifest for everything ``collect_structural_graph`` draws on for this
    project. Best-effort per source type: one query failing never blocks the
    others or the build itself.
    """
    coverage: dict[str, dict[str, int]] = {}

    async def _safe(key: str, coro: Any) -> None:
        try:
            coverage[key] = await coro
        except Exception:
            coverage[key] = {"total": 0, "included": 0, "excluded": 0, "failed": 0, "pending": 0}

    async def _file_sources() -> dict[str, int]:
        statuses = await _all_statuses(
            session,
            select(FileSourceMeta.ai_profile_status).where(
                FileSourceMeta.project_id == project_id,
                FileSourceMeta.tenant_id == tenant_id,
                FileSourceMeta.archived.is_(False),
            ),
        )
        # No explicit failed state exists for file-source profiling today --
        # anything that never reached "profiled" is reported as pending.
        return _bucket(statuses, pending={"pending"}, failed=set())

    async def _data_sources() -> dict[str, int]:
        statuses = await _all_statuses(
            session,
            select(DatabaseDataSource.last_test_status).where(
                DatabaseDataSource.project_id == project_id,
                DatabaseDataSource.tenant_id == tenant_id,
                DatabaseDataSource.archived.is_(False),
            ),
        )
        bucket = _bucket(statuses, pending=set(), failed=set())
        bucket["pending"] = sum(1 for s in statuses if not s)
        bucket["failed"] = sum(1 for s in statuses if s and s != "success")
        return bucket

    async def _assets() -> dict[str, int]:
        statuses = await _all_statuses(
            session,
            select(ProjectAsset.ai_status).where(
                ProjectAsset.project_id == project_id,
                ProjectAsset.tenant_id == tenant_id,
            ),
        )
        return _bucket(
            statuses, pending=_ASSET_PENDING_STATUSES, failed=_ASSET_FAILED_STATUSES,
        )

    async def _reference_documents() -> dict[str, int]:
        # Same tier scope as collect_structural_graph -- project docs,
        # tenant-wide company docs, and global industry standards.
        stmt = select(ReferenceDocument.status).where(
            ReferenceDocument.status != "archived",
            ReferenceDocument.status != "superseded",
            or_(
                ReferenceDocument.tier == TIER_INDUSTRY,
                and_(ReferenceDocument.tier == TIER_COMPANY, ReferenceDocument.tenant_id == tenant_id),
                and_(ReferenceDocument.tier == TIER_PROJECT, ReferenceDocument.project_id == project_id),
            ),
        )
        statuses = await _all_statuses(session, stmt)
        return _bucket(statuses, pending={"draft", "processing"}, failed=set())

    async def _no_pipeline(model: Any, *, has_tenant_id: bool) -> dict[str, int]:
        """Saved queries and dashboards are user-authored, not ingested --
        there's no extraction pipeline for them to fail or leave pending, but
        the truncation-cap manifest (total/included/excluded) still applies."""
        conditions = [model.project_id == project_id]
        if has_tenant_id:
            conditions.append(model.tenant_id == tenant_id)
        total = await session.scalar(select(func.count()).where(*conditions))
        return _bucket([None] * int(total or 0), pending=set(), failed=set())

    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != tenant_id:
        return coverage

    await _safe("file_sources", _file_sources())
    await _safe("data_sources", _data_sources())
    await _safe("assets", _assets())
    await _safe("reference_documents", _reference_documents())
    await _safe("saved_queries", _no_pipeline(SavedQuery, has_tenant_id=False))
    await _safe("dashboards", _no_pipeline(Dashboard, has_tenant_id=True))
    return coverage
