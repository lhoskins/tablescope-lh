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

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dashboard import Dashboard
from app.models.database_data_source import DatabaseDataSource
from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project
from app.models.project_asset import ProjectAsset
from app.models.project_insight_acknowledgement import (
    ProjectInsightAcknowledgement,
)
from app.models.project_intelligence_snapshot import ProjectIntelligenceSnapshot
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
from app.services.ai_governance import ai_governance_service, infer_governance_key
from app.services.executive_insight_dependencies import ExecutiveInsightDependencyService
from app.services.knowledge_graph_ai_context import (
    collect_knowledge_graph_ai_context,
)
from app.services.project_ai_context import build_project_ai_context

logger = logging.getLogger(__name__)

# Window used for the deterministic "What Changed Since Last Visit" deltas.
_ACTIVITY_WINDOW = timedelta(days=7)


async def mark_project_insight_stale(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int | None = None,
) -> None:
    """Mark all Project Insight snapshots for a tenant/project as stale."""
    stmt = (
        update(ProjectIntelligenceSnapshot)
        .where(ProjectIntelligenceSnapshot.tenant_id == tenant_id)
        .values(is_stale=True)
    )
    if project_id is not None:
        stmt = stmt.where(ProjectIntelligenceSnapshot.project_id == project_id)
    await session.execute(stmt)


def _missing_data_hint(result: Any) -> str:
    """Explain (data-driven) why a question can't be answered from the project.

    Uses the resolver's near-miss candidates when available; never hard-codes a
    business field. The message tells the user the current authorized sources
    lack the data and that adding the relevant source would enable the question.
    """
    near = [c for c in (result.candidates or []) if getattr(c, "score", 0) > 0]
    if near:
        closest = ", ".join(c.source for c in near[:2])
        return (
            "The project's current data sources "
            f"(closest: {closest}) don't contain the fields needed to answer "
            "this. Add a source with the relevant data to enable it."
        )
    return (
        "The project has no authorized data source with the fields needed to "
        "answer this. Add a source with the relevant data to enable it."
    )


async def _partition_questions(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
    kpi_names: list[str],
    items: list[dict[str, Any]],
    question_keys: tuple[str, ...],
    has_sources: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split questions into (answerable, needs-additional-data).

    Every suggested question is run through the Project Semantic Source
    Resolver. Items it can ground on a real authorized source
    (``status == "resolved"``) are answerable; the rest are returned separately
    (not dropped) annotated with a ``missingDataHint`` describing the data the
    project would need to answer them. Nothing is hard-coded — a question is
    answerable purely on whether its terms match a real source's columns.
    """
    from app.services.project_source_resolver import resolve_project_source

    if not has_sources:
        # With no authorized sources at all the answerable/needs-data split is
        # meaningless (project setup, not a data-coverage gap) — keep the AI's
        # suggestions as-is rather than emptying the list.
        return list(items), []

    answerable: list[dict[str, Any]] = []
    needs_data: list[dict[str, Any]] = []
    for item in items:
        question = ""
        for key in question_keys:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                question = value.strip()
                break
        if not question:
            continue
        try:
            result = await resolve_project_source(
                session,
                tenant_id=tenant_id,
                project_id=project_id,
                question=question,
                kpi_names=kpi_names,
            )
        except Exception as exc:  # never break the page on a resolver failure
            logger.warning(
                "resolver filter failed for project %s question %r: %s",
                project_id, question, exc,
            )
            answerable.append(item)
            continue
        if result.status != "resolved":
            needs_data.append({**item, "missingDataHint": _missing_data_hint(result)})
            continue

        # Filter suggested questions whose analytical method is disabled for the
        # tenant.  These are surfaced in the "needs data" bucket with a governance
        # hint instead of being offered as clickable follow-ups.
        method_key = infer_governance_key(question=question)
        decision = await ai_governance_service.evaluate_method(
            session, tenant_id, method_key, project_id=project_id, record=False
        )
        if not decision.allowed:
            needs_data.append({
                **item,
                "missingDataHint": decision.user_message,
                "governanceBlocked": True,
            })
        else:
            answerable.append({**item, "governance": decision.to_explanation_dict()})

    return answerable, needs_data


# Allowed severity values per card group (Package 3 unified schema).
_RISK_SEVERITIES = {"critical", "urgent", "warning", "watch"}
_TREND_SEVERITIES = {"watch", "warning", "informational"}
_OPPORTUNITY_SEVERITIES = {"opportunity", "recommendation"}

# A concrete, data-grounded question per built-in card type. Clicking a card
# opens the same AI Answer modal (Package 1) seeded with this question, so the
# investigation runs real SQL against the project's authorized sources.
_INVESTIGATION_QUESTIONS = {
    "risk_sla": (
        "Which suppliers have the highest average delivery lead times, and "
        "which exceed the SLA threshold?"
    ),
    "risk_threshold": (
        "Which records breach their target/threshold, or sit in a risk "
        "status, and how large is that share?"
    ),
    "risk_expiry": (
        "Which contracts or documents are expiring within the next 90 days?"
    ),
    "risk_upcoming": (
        "How many records are approaching an upcoming due/renewal/end date, "
        "and how soon?"
    ),
    "trend_spend": "How has total spend changed across recent periods?",
    "trend_metric": "How has this metric changed across recent periods?",
    "opportunity_supplier": (
        "Which suppliers have the highest performance scores?"
    ),
    "opportunity_performance": (
        "Which entities are the top and bottom performers on this metric, "
        "and how large is the gap?"
    ),
}


def _card_group(insight_type: str) -> str | None:
    """Map a built-in insight type onto risks / trends / opportunities."""
    if insight_type.startswith("risk"):
        return "risks"
    if insight_type.startswith(("trend", "relationship")):
        return "trends"
    if insight_type.startswith("opportunity"):
        return "opportunities"
    return None


def _normalize_severity(severity: str, group: str) -> str:
    """Coerce a card's severity onto the allowed values for its group."""
    sev = (severity or "").strip().lower()
    if group == "risks":
        return sev if sev in _RISK_SEVERITIES else "watch"
    if group == "trends":
        if sev in ("urgent", "critical"):
            return "warning"
        return sev if sev in _TREND_SEVERITIES else "informational"
    return sev if sev in _OPPORTUNITY_SEVERITIES else "opportunity"


def _to_insight_card(card: dict[str, Any], group: str) -> dict[str, Any]:
    """Map a deterministic Business Insight card onto the unified card schema."""
    insight_type = str(card.get("insightType", ""))
    callout = card.get("callout")
    recommended_action = (
        str(callout.get("text", "")) if isinstance(callout, dict) else ""
    )
    sources = card.get("sources") or {}
    source_tables = [str(t) for t in (sources.get("tables") or [])]
    supporting = [
        *source_tables,
        *(str(d) for d in (sources.get("documents") or [])),
    ]
    ctx = card.get("sourceContext") or {}
    metric = str(ctx.get("metric") or "")
    period_column = str(ctx.get("periodColumn") or "")
    source_columns = [str(c) for c in (ctx.get("sourceColumns") or [])]
    # Prefer the stable server-generated insightId; legacy ids are a fallback.
    stable_id = str(card.get("insightId") or card.get("id") or "")
    return {
        "id": stable_id,
        "insightId": stable_id,
        "insightType": insight_type,
        "title": str(card.get("title", "")),
        "summary": str(card.get("summary", "")),
        "severity": _normalize_severity(str(card.get("severity", "")), group),
        "recommendedAction": recommended_action,
        "question": _INVESTIGATION_QUESTIONS.get(
            insight_type, str(card.get("title", ""))
        ),
        "supportingSources": supporting,
        "sourceTables": source_tables,
        "sourceColumns": source_columns,
        "metric": metric,
        "periodColumn": period_column,
        "sql": card.get("sql"),
        "chartType": card.get("chartType"),
        "labelColumn": card.get("labelColumn"),
        "valueColumn": card.get("valueColumn"),
        "valueColumn2": card.get("valueColumn2"),
        "chart": card.get("chart"),
        "explanation": card.get("explanation"),
        "executedAt": card.get("executedAt"),
        "evidenceFingerprint": card.get("evidenceFingerprint"),
        "confidenceScore": card.get("confidenceScore"),
        "confidenceEvaluation": card.get("confidenceEvaluation"),
        "visualizationDecision": card.get("visualizationDecision"),
        "chartCandidates": card.get("chartCandidates"),
    }


def _is_relationship_card(card: dict[str, Any]) -> bool:
    """A multi-table relationship analysis with two populated series."""
    if not str(card.get("insightType", "")).startswith("relationship"):
        return False
    if card.get("chartType") not in ("dual_line", "scatter"):
        return False
    return bool(card.get("valueColumn2"))


async def _grouped_intelligence_cards(
    project: Project,
    ctx: hi.ProjectContext,
    runner: Any,
    *,
    session: AsyncSession | None = None,
    tenant_id: int | None = None,
    user_id: int | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Generate Business Insight-style cards grouped by risk/trend/opportunity.

    Deterministic and project-scoped: reuses the existing Business Insight card
    generators against this project's real data via its VDB runner. When the
    deterministic suite does not emit any multi-table relationship cards but
    the project has join evidence, we run the AI-driven analyst loop with the
    relationship floor so Project Insight also surfaces cross-table dual-line
    analyses.
    """
    grouped: dict[str, list[dict[str, Any]]] = {
        "risks": [],
        "trends": [],
        "opportunities": [],
    }
    cards: list[dict[str, Any]] = []
    try:
        if session is not None:
            cards = await hi.run_intelligence_suite(
                project,
                ctx,
                hi.ALL_PROMPT_TYPES,
                runner,
                session=session,
                tenant_id=tenant_id,
                user_id=user_id,
            )
        else:
            cards = await hi.run_intelligence_suite(
                project, ctx, hi.ALL_PROMPT_TYPES, runner
            )
    except Exception as exc:
        logger.warning(
            "project insight deterministic cards failed for project %s: %s",
            project.id,
            exc,
        )

    if session is not None and tenant_id is not None and user_id is not None:
        has_relationship = any(
            _is_relationship_card(c) for c in cards if isinstance(c, dict)
        )
        if not has_relationship:
            try:
                relationship_cards = await hi.run_ai_intelligence(
                    project,
                    ctx,
                    runner,
                    session=session,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    granularity=3,
                    max_analyses=4,
                )
                if relationship_cards:
                    cards.extend(
                        c
                        for c in relationship_cards
                        if isinstance(c, dict) and _is_relationship_card(c)
                    )
            except Exception as exc:
                logger.warning(
                    "project insight relationship floor failed for project %s: %s",
                    project.id,
                    exc,
                )

    for card in cards:
        if not isinstance(card, dict):
            continue
        group = _card_group(str(card.get("insightType", "")))
        if group is None:
            continue
        grouped[group].append(_to_insight_card(card, group))
    return grouped


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
    runner: Any = None,
) -> ProjectInsightResponse:
    """Build the Project Insight report for one authorized project."""
    now_iso = datetime.now(UTC).isoformat()
    project_meta = ProjectInsightProject(
        id=project.id,
        name=project.name,
        status=(project.type or "Active"),
    )

    ctx = await hi.gather_project_context(session, project)
    project_context = await build_project_ai_context(
        session,
        tenant_id=tenant_id,
        project_id=project.id,
        request_type="project_insight",
    )
    grouped_cards = await _grouped_intelligence_cards(
        project, ctx, runner, session=session, tenant_id=tenant_id, user_id=user_id
    )
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

    dep_service = ExecutiveInsightDependencyService(session)
    dep = await dep_service.check(project.id)
    graph_mode = dep["mode"]
    graph_status = dep["graph_status"]
    graph_blocking_reasons = dep["blocking_reasons"]
    graph_disclosure = dep["disclosure"]

    ai_result: dict[str, Any] | None = None
    if graph_mode == "blocked":
        logger.info(
            "Executive Insight blocked for project %s: %s", project.id, graph_blocking_reasons
        )
    else:
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
                project_context=project_context or {},
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
            risks=grouped_cards["risks"],
            trends=grouped_cards["trends"],
            opportunities=grouped_cards["opportunities"],
            whatChangedSinceLastVisit=what_changed,
            aiAvailable=False,
            aiContextEnabled=project_context.get("ai_context_enabled") if project_context else False,
            contextVersion=project_context.get("version") if project_context else 0,
            graphStatus=graph_status,
            graphMode=graph_mode,
            graphBlockingReasons=graph_blocking_reasons,
            graphDisclosure=graph_disclosure,
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

    # Split suggested questions by whether the resolver can ground them on a
    # confident authorized source. Answerable ones stay clickable; the rest are
    # surfaced separately with a hint about the additional data they'd need
    # (not dropped, not left to fail when clicked). Recommended queries the
    # project can't run are moved into the same "needs data" bucket.
    has_sources = bool(ctx.tables)
    questions_to_ask, questions_needing_data = await _partition_questions(
        session,
        tenant_id=tenant_id,
        project_id=project.id,
        kpi_names=kpi_names,
        items=[q for q in (ai_result.get("questionsToAsk") or []) if isinstance(q, dict)],
        question_keys=("question", "text", "label"),
        has_sources=has_sources,
    )
    recommended_queries, queries_needing_data = await _partition_questions(
        session,
        tenant_id=tenant_id,
        project_id=project.id,
        kpi_names=kpi_names,
        items=[q for q in (ai_result.get("recommendedQueries") or []) if isinstance(q, dict)],
        question_keys=("businessQuestion", "title", "name", "description"),
        has_sources=has_sources,
    )

    return ProjectInsightResponse(
        project=project_meta,
        generatedAt=now_iso,
        lastUpdatedAt=now_iso,
        executiveSummary=executive,
        questionsToAsk=questions_to_ask,
        questionsNeedingData=questions_needing_data + queries_needing_data,
        trendDetection=[t for t in (ai_result.get("trendDetection") or []) if isinstance(t, dict)],
        recommendedDashboards=[
            d for d in (ai_result.get("recommendedDashboards") or []) if isinstance(d, dict)
        ],
        recommendedQueries=recommended_queries,
        recommendedKpis=[
            k for k in (ai_result.get("recommendedKpis") or []) if isinstance(k, dict)
        ],
        risks=grouped_cards["risks"],
        trends=grouped_cards["trends"],
        opportunities=grouped_cards["opportunities"],
        whatChangedSinceLastVisit=what_changed,
        insightValidationWorkflow=workflow,
        aiAvailable=True,
        aiContextEnabled=project_context.get("ai_context_enabled") if project_context else False,
        contextVersion=project_context.get("version") if project_context else 0,
        graphStatus=graph_status,
        graphMode=graph_mode,
        graphBlockingReasons=graph_blocking_reasons,
        graphDisclosure=graph_disclosure,
    )
