"""Home AI Intelligence snapshots: hydrate, refresh, run status, clear cache.

Split from ``home_intelligence.py``; siblings: ``home_intelligence_suite.py``,
``home_intelligence_suggestions.py`` and ``home_intelligence_dashboard_save.py``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import SessionLocal, get_db
from app.models.audit_event import AuditEvent
from app.models.business_insight_result import BusinessInsightResult
from app.models.intelligence_snapshot import IntelligenceSnapshot
from app.models.project_intelligence_snapshot import ProjectIntelligenceSnapshot
from app.routes.home_intelligence_suite import (
    _start_home_intelligence_run,
)
from app.services import home_intel_queue as q

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["AI Intelligence"])


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot — persist the latest completed run; hydrate instantly on open
# ─────────────────────────────────────────────────────────────────────────────

async def _save_snapshot(
    context: RequestContext,
    granularity: int,
    payload: dict[str, Any],
    *,
    failed_project_count: int = 0,
) -> None:
    """Upsert the caller's single latest intelligence snapshot.

    Results are *merged* with the prior snapshot rather than replacing it: the
    new run's per-project results win, but any project that produced no fresh
    result this run (because it ended terminally errored, or the run drained
    before it finished) keeps its previous entry. This guarantees a partial or
    failed refresh never wipes a good prior result with a blank one. The merge
    is scoped to the projects the current run actually covered, so results for
    projects the caller can no longer access are dropped.
    """
    async with SessionLocal() as session:
        snap = await session.scalar(
            select(IntelligenceSnapshot).where(
                IntelligenceSnapshot.user_id == context.user_id
            )
        )
        prior_results = (snap.payload.get("results") or []) if snap else []
        new_results = payload.get("results") or []
        merged: dict[str, dict[str, Any]] = {
            str(r.get("projectId")): r for r in prior_results
        }
        for r in new_results:
            merged[str(r.get("projectId"))] = r
        current_ids = {str(p.get("id")) for p in (payload.get("projects") or [])}
        if current_ids:
            merged = {
                pid: r for pid, r in merged.items() if pid in current_ids
            }
        if failed_project_count:
            logger.info(
                "home intelligence snapshot for user %s finalized with %s project "
                "failure(s); merged %s new result(s) over %s prior into %s total",
                context.user_id,
                failed_project_count,
                len(new_results),
                len(prior_results),
                len(merged),
            )
        payload = {**payload, "results": list(merged.values())}
        if snap is None:
            snap = IntelligenceSnapshot(
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
            session.add(snap)
        snap.tenant_id = context.tenant_id
        snap.granularity = granularity
        # Keep a previous synthesis if this update carries no replacement (e.g.
        # a refresh that has not yet produced a new synthesis).
        prior_synthesis = (snap.payload or {}).get("synthesis") if snap else None
        if payload.get("synthesis") is None and prior_synthesis is not None:
            payload = {**payload, "synthesis": prior_synthesis}
        snap.payload = payload
        await session.commit()


def _as_utc(dt: datetime | None) -> datetime | None:
    """Normalize a possibly-naive DB timestamp to aware UTC for comparison."""
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


async def _stale_project_ids(
    session: AsyncSession,
    context: RequestContext,
    snap: IntelligenceSnapshot,
) -> list[str]:
    """Projects whose Knowledge Graph rebuilt after this briefing was written.

    The KG lifecycle already rebuilds on every data change, so "a KG build
    postdates the snapshot" is a faithful, DB-only proxy for "the data behind
    this briefing changed" — no AI calls, one indexed query.
    """
    from app.models import KnowledgeGraph

    project_ids: list[int] = []
    for p in (snap.payload or {}).get("projects") or []:
        try:
            project_ids.append(int(p.get("id")))
        except (TypeError, ValueError):
            continue
    snap_time = _as_utc(snap.updated_at)
    if not project_ids or snap_time is None:
        return []

    graphs = (
        await session.scalars(
            select(KnowledgeGraph).where(
                KnowledgeGraph.tenant_id == context.tenant_id,
                KnowledgeGraph.project_id.in_(project_ids),
            )
        )
    ).all()
    stale: list[str] = []
    for graph in graphs:
        built = _as_utc(graph.last_successful_build_at)
        if built is not None and built > snap_time:
            stale.append(str(graph.project_id))
    return stale


async def _snapshot_payload_dict(
    session: AsyncSession,
    context: RequestContext,
    snap: IntelligenceSnapshot,
) -> dict[str, Any]:
    """Build the snapshot response, honouring both KG-drift and in-progress runs."""
    project_ids: set[str] = set()
    if isinstance(snap.payload, dict):
        for p in snap.payload.get("projects") or []:
            try:
                project_ids.add(str(p["id"]))
            except (TypeError, KeyError, ValueError):
                pass

    kg_stale: set[str] = set()
    try:
        kg_stale = set(await _stale_project_ids(session, context, snap))
    except Exception:  # staleness is advisory — never break the snapshot read
        logger.exception("Failed to compute snapshot staleness")

    payload_stale = False
    payload_stale_projects: set[str] = set()
    if isinstance(snap.payload, dict):
        payload_stale = bool(snap.payload.get("stale"))
        for pid in snap.payload.get("staleProjects") or []:
            try:
                payload_stale_projects.add(str(pid))
            except (TypeError, ValueError):
                pass

    if payload_stale:
        stale_projects = project_ids | kg_stale | payload_stale_projects
    else:
        stale_projects = kg_stale | payload_stale_projects

    payload = dict(snap.payload) if isinstance(snap.payload, dict) else {}
    payload.pop("stale", None)
    payload.pop("staleProjects", None)
    payload.pop("activeRunId", None)
    payload.pop("activeRunComplete", None)

    active_run = await q.get_current_run_status(context.tenant_id, context.user_id)
    active_run_id: str | None = None
    active_run_complete: bool | None = None
    if active_run:
        active_run_id = active_run["run_id"]
        active_run_complete = active_run["complete"]

    return {
        "granularity": snap.granularity,
        "updatedAt": snap.updated_at.isoformat() if snap.updated_at else None,
        **payload,
        "stale": bool(stale_projects),
        "staleProjects": sorted(stale_projects),
        "activeRunId": active_run_id,
        "activeRunComplete": active_run_complete,
    }


@router.get("/home-intelligence/snapshot")
async def get_intelligence_snapshot(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Return the caller's latest persisted run (or an in-progress run snapshot).

    ``stale``/``staleProjects`` flag projects whose data changed (Knowledge
    Graph rebuilt) after this briefing was written, so the UI can nudge a
    refresh without spending any AI capacity.
    """
    snap = await session.scalar(
        select(IntelligenceSnapshot).where(
            IntelligenceSnapshot.user_id == context.user_id
        )
    )
    if snap is not None:
        return {"snapshot": await _snapshot_payload_dict(session, context, snap)}

    active_run = await q.get_current_run_status(context.tenant_id, context.user_id)
    if active_run:
        return {
            "snapshot": {
                "granularity": active_run["meta"]["granularity"],
                "updatedAt": None,
                "generatedAt": None,
                "projects": active_run["meta"]["projects"],
                "results": [],
                "synthesis": None,
                "stale": True,
                "staleProjects": [str(p["id"]) for p in active_run["meta"]["projects"]],
                "activeRunId": active_run["run_id"],
                "activeRunComplete": active_run["complete"],
            }
        }

    return {"snapshot": None}


class RefreshHomeIntelligenceRequest(BaseModel):
    cross_project: bool = True
    granularity: int = 3


@router.post("/home-intelligence/refresh")
async def refresh_home_intelligence(
    req: RefreshHomeIntelligenceRequest | None = None,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Queue a background business-intelligence run and return immediately.

    The caller can poll ``GET /api/ai/home-intelligence/snapshot`` (or
    ``/run/{run_id}``) to update the cards once the arq workers finish.
    """
    cross_project = req.cross_project if req else True
    granularity = req.granularity if req else 3
    run_id, project_meta = await _start_home_intelligence_run(
        context, cross_project, granularity
    )
    if not run_id:
        return {"snapshot": None, "run_id": None}

    payload: dict[str, Any] = {
        "projects": project_meta,
        "results": [],
        "synthesis": None,
        "generatedAt": datetime.now(UTC).isoformat(),
        "stale": True,
        "staleProjects": [p["id"] for p in project_meta],
    }
    await _save_snapshot(context, granularity, payload)

    snap = await session.scalar(
        select(IntelligenceSnapshot).where(
            IntelligenceSnapshot.user_id == context.user_id
        )
    )
    return {
        "snapshot": await _snapshot_payload_dict(session, context, snap) if snap else None,
        "run_id": run_id,
    }


@router.get("/home-intelligence/run/{run_id}")
async def home_intelligence_run_status(
    run_id: str,
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Return whether a queued business-intelligence run has finalized."""
    stored, _ = await q.get_synthesis(run_id)
    return {"run_id": run_id, "complete": stored}


@router.post("/home-intelligence/clear-cache")
async def clear_home_intelligence_cache(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> dict[str, Any]:
    """Clear Business Insight caches for the caller's tenant.

    Deletes the tenant's shared Business Insight result cache, the stream
    snapshot, per-user project snapshots, and the Percent Change Summary cache.
    Any in-progress run is superseded so the next Analyze starts fresh.
    """
    r1 = await session.execute(
        delete(BusinessInsightResult).where(
            BusinessInsightResult.tenant_id == context.tenant_id
        )
    )
    r2 = await session.execute(
        delete(IntelligenceSnapshot).where(
            IntelligenceSnapshot.tenant_id == context.tenant_id
        )
    )
    r3 = await session.execute(
        delete(ProjectIntelligenceSnapshot).where(
            ProjectIntelligenceSnapshot.tenant_id == context.tenant_id,
            ProjectIntelligenceSnapshot.suite == "insights",
        )
    )
    business_count = int(getattr(r1, "rowcount", 0) or 0)
    snapshot_count = int(getattr(r2, "rowcount", 0) or 0)
    insight_snapshot_count = int(getattr(r3, "rowcount", 0) or 0)
    session.add(
        AuditEvent(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            event_type="tenant_settings",
            scope="business_insight_cache_clear",
            title="Cleared business insight cache",
        )
    )
    await session.commit()

    try:
        redis = q.get_redis()
        # Supersede any in-progress home-intelligence run so queued jobs exit
        # instead of writing stale results after the cache is cleared.
        current_run = await q.get_current_run(context.tenant_id, context.user_id)
        if current_run:
            await redis.set(
                q._current_run_key(context.tenant_id, context.user_id),
                uuid.uuid4().hex,
                ex=60,
            )
        # Clear the Percent Change Summary Redis cache for this tenant.
        pcs_keys = await redis.keys(f"pcs:{context.tenant_id}:*")
        if pcs_keys:
            await redis.delete(*pcs_keys)
    except Exception:
        logger.exception("Failed to clear Redis caches during BI cache clear")

    return {
        "deleted": {
            "business_insight_results": business_count,
            "intelligence_snapshots": snapshot_count,
            "project_insight_snapshots": insight_snapshot_count,
        }
    }
