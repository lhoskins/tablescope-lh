"""Project metadata catalog and activity feed.

Split from ``projects.py``; see ``projects_shared.py`` for the helper cluster.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.audit_event import AuditEvent
from app.models.dashboard import Dashboard
from app.models.data_source_ai_profile import (
    DataSourceAIProfile,
    DataSourceFieldProfile,
)
from app.models.project import Project
from app.models.project_asset import ProjectAsset
from app.models.saved_query import SavedQuery
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["projects"])


def _ai_metadata_count(meta: dict, keys: list[str]) -> int:
    for key in keys:
        value = meta.get(key) if isinstance(meta, dict) else None
        if isinstance(value, int):
            return value
        if isinstance(value, list):
            return len(value)
    return 0


@router.get("/{project_id}/metadata-catalog")
async def get_metadata_catalog(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict:
    """AI-profiled schema catalog for a project: tables (with field profiles)
    and documents. Powers the Metadata Catalog (Intelligence) screen."""
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")

    profiles = (
        await session.scalars(
            select(DataSourceAIProfile)
            .where(
                DataSourceAIProfile.tenant_id == context.tenant_id,
                DataSourceAIProfile.project_id == project_id,
            )
            .order_by(DataSourceAIProfile.file_name)
        )
    ).all()

    tables: list[dict] = []
    for p in profiles:
        fields = (
            await session.scalars(
                select(DataSourceFieldProfile)
                .where(DataSourceFieldProfile.data_source_id == p.data_source_id)
                .order_by(DataSourceFieldProfile.id)
            )
        ).all()
        tables.append({
            "data_source_id": p.data_source_id,
            "name": p.file_name or f"source-{p.data_source_id}",
            "source": p.file_type,
            "row_count": p.row_count,
            "field_count": p.column_count or len(fields),
            "ai_summary": p.ai_summary,
            "ai_quality_summary": p.ai_quality_summary,
            "status": p.status,
            "last_synced": p.updated_at.isoformat() if p.updated_at else None,
            "fields": [
                {
                    "name": f.field_name,
                    "type": f.recommended_type or f.detected_type,
                    "ai_description": f.ai_description,
                    "null_percent": (
                        float(f.null_percent) if f.null_percent is not None else None
                    ),
                    "distinct_count": f.distinct_count,
                    "sample_values": f.sample_values or [],
                    "include_in_ai": f.include_in_ai,
                }
                for f in fields
            ],
        })

    assets = (
        await session.scalars(
            select(ProjectAsset)
            .where(ProjectAsset.project_id == project_id)
            .order_by(ProjectAsset.created_at.desc())
        )
    ).all()
    documents = [
        {
            "id": a.id,
            "title": a.title,
            "type": (a.file_extension or "").replace(".", "").upper() or "FILE",
            "status": a.ai_status,
            "clauses": _ai_metadata_count(
                a.ai_metadata, ["extraction_count", "clauses", "kpis"]
            ),
            "relationships": _ai_metadata_count(
                a.ai_metadata, ["relationship_count", "relationships", "links"]
            ),
        }
        for a in assets
    ]

    return {"tables": tables, "documents": documents}


@router.get("/{project_id}/activity")
async def get_project_activity(
    project_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict:
    """Real activity/audit feed for a project, derived from saved queries,
    dashboards and document assets. Powers the Audit Log (Intelligence) screen."""
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")

    queries = (
        await session.scalars(
            select(SavedQuery).where(SavedQuery.project_id == project_id)
        )
    ).all()
    dashboards = (
        await session.scalars(
            select(Dashboard).where(Dashboard.project_id == project_id)
        )
    ).all()
    assets = (
        await session.scalars(
            select(ProjectAsset).where(ProjectAsset.project_id == project_id)
        )
    ).all()

    # Resolve actor display names in one batch.
    user_ids = {
        uid
        for uid in (
            [q.owner_id for q in queries]
            + [d.owner_id for d in dashboards]
            + [a.created_by for a in assets]
        )
        if uid is not None
    }
    actors: dict[int, str] = {}
    if user_ids:
        users = await session.scalars(select(User).where(User.id.in_(user_ids)))
        for u in users:
            actors[u.id] = u.display_name or u.email or f"User #{u.id}"

    def actor_name(uid: int | None) -> str:
        return actors.get(uid, "System") if uid is not None else "System"

    events: list[dict] = []

    for q in queries:
        ai = bool(q.ai_generated)
        events.append({
            "id": f"query-{q.id}-saved",
            "ts": q.created_at.isoformat() if q.created_at else None,
            "category": "ai" if ai else "query",
            "label": "AI Action" if ai else "Query",
            "title": f"Query saved: {q.name}",
            "detail": q.left_datasource,
            "actor": actor_name(q.owner_id),
        })
        if q.last_run_at and q.run_count:
            events.append({
                "id": f"query-{q.id}-run",
                "ts": q.last_run_at.isoformat(),
                "category": "query",
                "label": "Query",
                "title": f"Query executed: {q.name}",
                "detail": (
                    f"{q.run_count} runs"
                    + (f" · {q.avg_runtime_ms}ms avg" if q.avg_runtime_ms else "")
                ),
                "actor": actor_name(q.owner_id),
            })

    for d in dashboards:
        ai = bool(d.ai_generated)
        events.append({
            "id": f"dashboard-{d.id}-created",
            "ts": d.created_at.isoformat() if d.created_at else None,
            "category": "ai" if ai else "dashboard",
            "label": "AI Action" if ai else "Dashboard",
            "title": f"Dashboard created: {d.name}",
            "detail": f"{d.view_count} views" if d.view_count else None,
            "actor": actor_name(d.owner_id),
        })

    for a in assets:
        events.append({
            "id": f"asset-{a.id}-uploaded",
            "ts": a.created_at.isoformat() if a.created_at else None,
            "category": "upload",
            "label": "Upload",
            "title": f"Document uploaded: {a.title}",
            "detail": a.ai_status,
            "actor": actor_name(a.created_by),
        })
        if a.ai_status.lower() in {"ready", "indexed", "completed", "complete"}:
            events.append({
                "id": f"asset-{a.id}-indexed",
                "ts": a.updated_at.isoformat() if a.updated_at else None,
                "category": "ai",
                "label": "AI Action",
                "title": f"Document indexed: {a.title}",
                "detail": "AI indexing complete",
                "actor": "System",
            })

    audit_events = (
        await session.scalars(
            select(AuditEvent)
            .where(AuditEvent.project_id == project_id)
            .order_by(AuditEvent.created_at.desc())
            .limit(limit)
        )
    ).all()
    for ev in audit_events:
        src_bits: list[str] = []
        if ev.tables_queried:
            src_bits.append(", ".join(str(t) for t in ev.tables_queried))
        if ev.documents_read:
            src_bits.append(", ".join(str(d) for d in ev.documents_read))
        detail = " · ".join(src_bits) if src_bits else None
        if ev.duration_ms is not None:
            detail = f"{detail} · {ev.duration_ms}ms" if detail else f"{ev.duration_ms}ms"
        events.append({
            "id": f"audit-{ev.id}",
            "ts": ev.created_at.isoformat() if ev.created_at else None,
            "category": "ai",
            "label": "AI Action",
            "title": ev.title or f"AI intelligence: {ev.prompt_type or ev.event_type}",
            "detail": detail,
            "actor": actor_name(ev.user_id),
        })

    events = [e for e in events if e["ts"] is not None]
    events.sort(key=lambda e: e["ts"], reverse=True)
    events = events[:limit]

    actor_set = {e["actor"] for e in events if e["actor"] != "System"}
    return {
        "events": events,
        "stats": {
            "total_events": len(events),
            "ai_actions": sum(1 for e in events if e["category"] == "ai"),
            "active_users": len(actor_set),
            "isolation_violations": 0,
        },
    }
