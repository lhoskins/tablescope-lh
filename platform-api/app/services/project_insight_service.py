"""Project Insight service — build the project-scoped executive insight report.

Distinct from Home / Business Insight (tenant-wide). This gathers ONLY the
selected project's authorized context (tables, documents, saved queries,
dashboards, Knowledge Graph), asks the AI server for the structured Project
Insight report (grounded in the Project Insight Best Practices prompt), computes
the "What Changed Since Last Visit" activity deltas deterministically from the
DB, and merges each user's acknowledgement state into the validation workflow.

If the AI server is unavailable the report degrades gracefully to an empty
structure (``aiAvailable=False``) rather than fabricating findings.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dashboard import Dashboard
from app.models.database_data_source import DatabaseDataSource
from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project
from app.models.project_asset import ProjectAsset
from app.models.project_insight_acknowledgement import (
    ProjectInsightAcknowledgement,
)
from app.models.saved_query import SavedQuery
from app.models.user import User
from app.schemas.project_insight import (
    ExecutiveSummary,
    ProjectInsightProject,
    ProjectInsightResponse,
    WhatChangedSinceLastVisit,
)
from app.services import ai_intelligence_client as ai
from app.services import home_intelligence as hi
from app.services.knowledge_graph_ai_context import (
    collect_knowledge_graph_ai_context,
)

logger = logging.getLogger(__name__)

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


async def build_project_insight(
    session: AsyncSession,
    *,
    project: Project,
    tenant_id: int,
    user_id: int,
) -> ProjectInsightResponse:
    """Build the Project Insight report for one authorized project."""
    now_iso = datetime.now(UTC).isoformat()
    project_meta = ProjectInsightProject(
        id=project.id,
        name=project.name,
        status=(project.type or "Active"),
    )

    ctx = await hi.gather_project_context(session, project)
    tables_payload = [
        {
            "name": t.view_name,
            "kind": t.kind,
            "columns": [f"{n} ({ty})" for (n, ty) in t.columns[:12]],
        }
        for t in ctx.tables
    ]
    documents_payload = [
        {"title": d.title, "summary": d.ai_summary or ""} for d in ctx.documents
    ]

    queries = (
        await session.scalars(
            select(SavedQuery).where(
                SavedQuery.project_id == project.id,
                SavedQuery.is_archived.is_(False),
            )
        )
    ).all()
    queries_payload = [
        {"name": q.name, "description": q.description or ""} for q in queries
    ]

    dashboards = (
        await session.scalars(
            select(Dashboard).where(Dashboard.project_id == project.id)
        )
    ).all()
    dashboards_payload = [{"name": d.name} for d in dashboards]

    kg_context = await collect_knowledge_graph_ai_context(
        session, tenant_id=tenant_id, project_id=project.id, user_id=user_id
    )
    kpi_names: list[str] = []
    for bucket in ("measured_kpis", "recommended_kpis"):
        for item in kg_context.get(bucket, []) or []:
            label = item.get("label") or item.get("name") if isinstance(item, dict) else None
            if label:
                kpi_names.append(str(label))

    kg_updated = len(kg_context.get("risks", []) or []) + len(
        kg_context.get("gaps", []) or []
    )

    ai_result: dict[str, Any] | None = None
    try:
        ai_result = await ai.project_insight(
            tenant_id=tenant_id,
            user_id=user_id,
            project_id=project.id,
            project=project_meta.model_dump(),
            tables=tables_payload,
            documents=documents_payload,
            queries=queries_payload,
            dashboards=dashboards_payload,
            kpis=kpi_names,
            knowledge_graph_context=kg_context,
        )
    except Exception as exc:  # never break the page on an AI failure
        logger.warning("project insight AI call failed (project %s): %s", project.id, exc)
        ai_result = None

    what_changed = await _what_changed(session, project.id, kg_updated)
    acks = await _acknowledgement_map(session, project.id)

    if not ai_result:
        return ProjectInsightResponse(
            project=project_meta,
            generatedAt=now_iso,
            lastUpdatedAt=now_iso,
            whatChangedSinceLastVisit=what_changed,
            aiAvailable=False,
        )

    es = ai_result.get("executiveSummary") or {}
    executive = ExecutiveSummary(
        summary=str(es.get("summary", "")),
        critical=[str(x) for x in (es.get("critical") or [])],
        warnings=[str(x) for x in (es.get("warnings") or [])],
        opportunities=[str(x) for x in (es.get("opportunities") or [])],
        recommendations=[str(x) for x in (es.get("recommendations") or [])],
    )
    workflow = _apply_acknowledgements(
        [w for w in (ai_result.get("insightValidationWorkflow") or []) if isinstance(w, dict)],
        acks,
    )

    return ProjectInsightResponse(
        project=project_meta,
        generatedAt=now_iso,
        lastUpdatedAt=now_iso,
        executiveSummary=executive,
        questionsToAsk=[q for q in (ai_result.get("questionsToAsk") or []) if isinstance(q, dict)],
        trendDetection=[t for t in (ai_result.get("trendDetection") or []) if isinstance(t, dict)],
        recommendedDashboards=[
            d for d in (ai_result.get("recommendedDashboards") or []) if isinstance(d, dict)
        ],
        recommendedQueries=[
            q for q in (ai_result.get("recommendedQueries") or []) if isinstance(q, dict)
        ],
        recommendedKpis=[
            k for k in (ai_result.get("recommendedKpis") or []) if isinstance(k, dict)
        ],
        whatChangedSinceLastVisit=what_changed,
        insightValidationWorkflow=workflow,
        aiAvailable=True,
    )
