from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dashboard import Dashboard
from app.models.project import Project
from app.models.project_intelligence_snapshot import ProjectIntelligenceSnapshot
from app.models.saved_query import SavedQuery
from app.schemas.project_insight import (
    ExecutiveSummary,
    ProjectInsightProject,
    ProjectInsightResponse,
)
from app.services import ai_intelligence_client as ai
from app.services import home_intelligence as hi
from app.services.ai_governance import ai_governance_service, infer_governance_key
from app.services.executive_insight_dependencies import ExecutiveInsightDependencyService
from app.services.knowledge_graph_ai_context import (
    collect_knowledge_graph_ai_context,
)
from app.services.project_ai_context import build_project_ai_context

from .activity_deltas import (
    _ACTIVITY_WINDOW,
    _acknowledgement_map,
    _apply_acknowledgements,
    _count_recent,
    _what_changed,
)
from .card_normalization import (
    _INVESTIGATION_QUESTIONS,
    _OPPORTUNITY_SEVERITIES,
    _RISK_SEVERITIES,
    _TREND_SEVERITIES,
    _card_group,
    _is_relationship_card,
    _normalize_severity,
    _to_insight_card,
)
from .method_envelopes import (
    _attach_method_envelope_to_card,
    _attach_method_envelopes_to_cards,
    _infer_method_intent,
    _series_to_result,
)

logger = logging.getLogger(__name__)


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
        "analysis": [],
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

    await _attach_method_envelopes_to_cards(session, tenant_id, cards, runner)

    for card in cards:
        if not isinstance(card, dict):
            continue
        group = _card_group(str(card.get("insightType", "")))
        grouped[group].append(_to_insight_card(card, group))
    return grouped


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
        session, tenant_id=tenant_id, project_id=project.id, user_id=user_id,
        surface="project_insights",
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
            analysis=grouped_cards["analysis"],
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
        analysis=grouped_cards["analysis"],
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


__all__ = [
    "_ACTIVITY_WINDOW",
    "_INVESTIGATION_QUESTIONS",
    "_OPPORTUNITY_SEVERITIES",
    "_RISK_SEVERITIES",
    "_TREND_SEVERITIES",
    "_acknowledgement_map",
    "_apply_acknowledgements",
    "_attach_method_envelope_to_card",
    "_attach_method_envelopes_to_cards",
    "_card_group",
    "_count_recent",
    "_grouped_intelligence_cards",
    "_infer_method_intent",
    "_is_relationship_card",
    "_missing_data_hint",
    "_normalize_severity",
    "_partition_questions",
    "_series_to_result",
    "_to_insight_card",
    "_what_changed",
    "build_project_insight",
    "logger",
    "mark_project_insight_stale",
]
