from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dashboard import Dashboard
from app.models.database_data_source import DatabaseDataSource
from app.models.file_source_meta import FileSourceMeta
from app.models.project_asset import ProjectAsset
from app.models.project_insight_acknowledgement import (
    ProjectInsightAcknowledgement,
)
from app.models.saved_query import SavedQuery
from app.models.user import User
from app.schemas.project_insight import (
    WhatChangedSinceLastVisit,
)

# Window used for the deterministic "What Changed Since Last Visit" deltas.
_ACTIVITY_WINDOW = timedelta(days=7)


async def _count_recent(
    session: AsyncSession, model: Any, project_id: int, since: datetime
) -> int:
    stmt = (
        select(func.count())
        .select_from(model)
        .where(model.project_id == project_id, model.created_at >= since)
    )
    return int(await session.scalar(stmt) or 0)


async def _what_changed(
    session: AsyncSession, project_id: int, kg_updated: int
) -> WhatChangedSinceLastVisit:
    since = datetime.now(UTC) - _ACTIVITY_WINDOW
    return WhatChangedSinceLastVisit(
        newFilesAdded=await _count_recent(session, ProjectAsset, project_id, since)
        + await _count_recent(session, FileSourceMeta, project_id, since),
        changedDataSources=await _count_recent(
            session, DatabaseDataSource, project_id, since
        ),
        newRisksIdentified=0,
        newQueries=await _count_recent(session, SavedQuery, project_id, since),
        newDashboards=await _count_recent(session, Dashboard, project_id, since),
        updatedKnowledgeGraph=kg_updated,
        changeLogLink=f"/projects/{project_id}/audit-log",
    )


async def _acknowledgement_map(
    session: AsyncSession, project_id: int
) -> dict[str, dict[str, Any]]:
    """Return {insight_id: {status, acknowledgedBy, acknowledgedAt}} for a project."""
    rows = (
        await session.execute(
            select(ProjectInsightAcknowledgement, User.display_name, User.email)
            .join(User, User.id == ProjectInsightAcknowledgement.user_id, isouter=True)
            .where(ProjectInsightAcknowledgement.project_id == project_id)
        )
    ).all()
    out: dict[str, dict[str, Any]] = {}
    for ack, display_name, email in rows:
        out[ack.insight_id] = {
            "status": ack.status or "reviewed",
            "acknowledgedBy": display_name or email or "",
            "acknowledgedAt": (
                ack.updated_at.isoformat() if ack.updated_at else None
            ),
        }
    return out


def _apply_acknowledgements(
    workflow: list[dict[str, Any]], acks: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for item in workflow:
        if not isinstance(item, dict):
            continue
        item = dict(item)
        ack = acks.get(str(item.get("id", "")))
        if ack:
            item["status"] = ack["status"]
            item["acknowledgedBy"] = ack["acknowledgedBy"]
            item["acknowledgedAt"] = ack["acknowledgedAt"]
        else:
            item.setdefault("status", "new")
            item.setdefault("acknowledgedBy", None)
            item.setdefault("acknowledgedAt", None)
        merged.append(item)
    return merged
