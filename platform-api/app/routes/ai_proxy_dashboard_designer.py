"""AI-guided Operational Insight dashboard design and application.

This route is the product-facing replacement for the legacy widget builder.  A
user describes an operational decision, Tablescope profiles the governed
project sources, validates the AI proposal by executing its queries, and then
applies the approved design through the canonical Operational Insight factory.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.dashboard import Dashboard
from app.models.file_source_meta import FileSourceMeta
from app.routes.ai_proxy_dashboard_suggest import ai_suggest_dashboards
from app.routes.ai_proxy_schemas import AISuggestDashboardsRequest
from app.routes.ai_proxy_shared import _check_project_access
from app.services.operational_insight_dashboards import (
    operational_insight_config,
    resolve_dashboard_group,
)

router = APIRouter()

DesignMode = Literal["create", "edit_dashboard", "add_insight", "edit_insight"]
SupportStatus = Literal["fully_supported", "partially_supported", "not_supported"]


class DashboardDesignRequest(BaseModel):
    project_id: int
    prompt: str = Field(min_length=3, max_length=4000)
    mode: DesignMode = "create"
    dashboard_id: int | None = None
    target_insight_id: str | None = None
    audience: str = "operational"
    emphasis: str = "balanced_operational_health"
    period: str = "1_year"
    dimension_label: str = "Site"
    dashboard_group_id: int | None = None


class DashboardDesignApplyRequest(BaseModel):
    project_id: int
    prompt: str = Field(min_length=3, max_length=4000)
    mode: DesignMode = "create"
    dashboard_id: int | None = None
    target_insight_id: str | None = None
    dashboard_group_id: int | None = None
    audience: str = "operational"
    emphasis: str = "balanced_operational_health"
    period: str = "1_year"
    dimension_label: str = "Site"
    support_status: SupportStatus
    accept_partial: bool = False
    suggestion: dict[str, Any]


_DomainConcepts = dict[str, dict[str, tuple[tuple[str, ...], tuple[str, ...]]]]

_DOMAIN_CONCEPTS: _DomainConcepts = {
    "itsm": {
        "resolution time": (
            ("resolution", "resolve", "mttr", "mean restore", "time to close"),
            ("resolvedat", "closedat", "resolutionhours", "durationhours", "mttr"),
        ),
        "SLA performance": (
            ("sla", "breach", "service level"),
            ("slamet", "slabreached", "breached", "breachtime", "slatarget"),
        ),
        "backlog state": (
            ("backlog", "open incident", "unresolved"),
            ("state", "status", "active", "closedat", "resolvedat"),
        ),
        "priority": (("priority", "severity", "critical"), ("priority", "severity")),
        "category": (("category", "type", "classification"), ("category", "subcategory", "type")),
        "assignment group": (
            ("assignment group", "team", "resolver group"),
            ("assignmentgroup", "team", "resolvergroup"),
        ),
        "site or region": (
            ("site", "region", "location", "plant"),
            ("site", "region", "location", "plant"),
        ),
    },
    "finance": {
        "revenue": (
            ("revenue", "sales", "income", "top line", "turnover"),
            ("revenue", "sales", "salesamount", "income", "amount", "turnover"),
        ),
        "expense": (
            ("expense", "cost", "spend", "expenditure", "opex"),
            ("expense", "cost", "spend", "expenditure", "costamount", "opex"),
        ),
        "gross margin": (
            ("gross margin", "margin", "profitability", "gross profit"),
            ("grossmargin", "grossprofit", "margin", "profit", "profitability"),
        ),
        "site or region": (
            ("site", "region", "location", "plant", "business unit"),
            ("site", "region", "location", "plant", "businessunit", "costcenter"),
        ),
    },
    "manufacturing": {
        "production output": (
            ("production", "output", "units produced", "throughput", "yield"),
            ("unitsproduced", "output", "quantity", "units", "throughput", "yield", "orderedqty", "receivedqty"),
        ),
        "OEE": (
            ("oee", "overall equipment effectiveness", "equipment effectiveness"),
            ("oee", "effectiveness", "equipmenteffectiveness"),
        ),
        "downtime": (
            ("downtime", "downtime hours", "unplanned downtime"),
            ("downtime", "downtimehours", "unplanneddowntime"),
        ),
        "defect rate": (
            ("defect", "defect rate", "defective", "quality", "inspection"),
            ("defect", "defectqty", "defective", "quality", "inspection", "severity", "inspectiondate"),
        ),
        "supplier performance": (
            ("supplier", "vendor", "purchase order", "supplier performance"),
            ("supplierid", "vendorid", "purchaseorderid", "supplier", "vendor", "poid", "buyer"),
        ),
        "freight and delivery": (
            ("freight", "delivery", "shipment", "shipping", "carrier"),
            ("freight", "freightcost", "shipment", "deliverydate", "shipdate", "carrier", "mode"),
        ),
        "site or region": (
            ("site", "region", "location", "plant"),
            ("site", "region", "location", "plant", "destinationsite"),
        ),
    },
    "sales": {
        "revenue": (
            ("revenue", "sales", "bookings", "closed won"),
            ("revenue", "salesamount", "amount", "booking", "closedwon"),
        ),
        "pipeline": (
            ("pipeline", "pipeline amount", "opportunities", "open deals"),
            ("pipelineamount", "opportunityamount", "pipeline", "opportunities"),
        ),
        "win rate": (
            ("win rate", "close rate", "conversion rate"),
            ("winrate", "status", "won", "closedwon", "conversionrate"),
        ),
        "site or region": (
            ("site", "region", "location", "territory"),
            ("site", "region", "location", "territory"),
        ),
    },
    "hr": {
        "headcount": (
            ("headcount", "employees", "workforce", "staff"),
            ("headcount", "employeeid", "staff", "employee", "workforce"),
        ),
        "turnover": (
            ("turnover", "attrition", "churn", "retention"),
            ("turnover", "attrition", "churn", "retention", "terminated"),
        ),
        "time to fill": (
            ("time to fill", "days to fill", "time to hire", "hiring speed"),
            ("timetofill", "timetofilldays", "daystofill", "hiringdays", "timetohire"),
        ),
        "site or region": (
            ("site", "region", "location", "department"),
            ("site", "region", "location", "department", "costcenter"),
        ),
    },
    "generic": {},
}

_DOMAIN_NARRATIVES: dict[str, str] = {
    "itsm": "ITSM incidents, service requests, SLA performance, and backlog management.",
    "finance": "Finance revenue, expense, gross margin, and profitability analysis.",
    "manufacturing": "Manufacturing production output, OEE, and downtime analysis.",
    "sales": "Sales revenue, pipeline, and win-rate analysis.",
    "hr": "HR workforce headcount, turnover, and time-to-fill analysis.",
    "generic": "Operational metrics based on the available project data.",
}


def _normal(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _source_columns(source: FileSourceMeta) -> list[dict[str, str]]:
    columns: list[dict[str, str]] = []
    for raw in source.column_types or []:
        if not isinstance(raw, dict) or not raw.get("name"):
            continue
        columns.append(
            {
                "name": str(raw["name"]),
                "type": str(raw.get("type") or raw.get("data_type") or "unknown"),
            }
        )
    return columns


def _concept_supported(
    field_terms: tuple[str, ...], available: set[str]
) -> bool:
    return any(
        any(
            _normal(candidate) in field or field in _normal(candidate)
            for field in available
        )
        for candidate in field_terms
    )


def _infer_domain(prompt: str, columns: list[dict[str, str]]) -> str:
    """Pick the best matching domain from column names and prompt terms.

    Column matches decide the domain first; prompt keywords are used only
    as a tiebreaker or when no columns are available. Ties or empty scores
    fall back to the generic domain.
    """
    normalized_prompt = prompt.lower()
    available = {_normal(column["name"]) for column in columns}
    column_scores: dict[str, int] = {}
    prompt_scores: dict[str, int] = {}
    for domain, concepts in _DOMAIN_CONCEPTS.items():
        if domain == "generic":
            continue
        column_scores[domain] = 0
        prompt_scores[domain] = 0
        for _label, (request_terms, field_terms) in concepts.items():
            if _concept_supported(field_terms, available):
                column_scores[domain] += 2
            if any(term in normalized_prompt for term in request_terms):
                prompt_scores[domain] += 1
    if not column_scores:
        return "generic"
    best_column_score = max(column_scores.values())
    if best_column_score == 0:
        return "generic"
    best_domains = [d for d, s in column_scores.items() if s == best_column_score]
    if len(best_domains) == 1:
        return best_domains[0]
    best_prompt_score = max(prompt_scores[d] for d in best_domains)
    best_by_prompt = [d for d in best_domains if prompt_scores[d] == best_prompt_score]
    return best_by_prompt[0]


def _missing_concepts(
    prompt: str, columns: list[dict[str, str]], domain: str
) -> list[str]:
    normalized_prompt = prompt.lower()
    available = {_normal(column["name"]) for column in columns}
    missing: list[str] = []
    concepts = _DOMAIN_CONCEPTS.get(domain, {})
    for label, (request_terms, field_terms) in concepts.items():
        requested = any(term in normalized_prompt for term in request_terms)
        supported = _concept_supported(field_terms, available)
        if requested and columns and not supported:
            missing.append(label)
    return missing


def _column_shapes(columns: list[dict[str, str]]) -> dict[str, bool]:
    names = [_normal(column["name"]) for column in columns]
    types = [column["type"].lower() for column in columns]
    has_date = any(
        "date" in value or "time" in value
        for value in [*names, *types]
    )
    has_number = any(
        marker in value
        for value in types
        for marker in ("number", "numeric", "decimal", "integer", "float", "currency", "percent")
    )
    # Every datasource can support record counts even if no explicit numeric
    # measure is present.
    has_measure = has_number or bool(columns)
    category_count = sum(
        1
        for value, column_type in zip(names, types, strict=False)
        if not any(marker in value for marker in ("date", "time", "amount", "hours", "count"))
        and not any(marker in column_type for marker in ("date", "time", "number", "integer", "decimal", "float"))
    )
    return {
        "date": has_date,
        "measure": has_measure,
        "category": category_count >= 1,
        "two_categories": category_count >= 2,
        "two_measures": has_number and sum(1 for value in types if any(marker in value for marker in ("number", "numeric", "decimal", "integer", "float"))) >= 2,
    }


def _chart_recommendations(columns: list[dict[str, str]]) -> list[dict[str, Any]]:
    shape = _column_shapes(columns)
    candidates = [
        ("kpi", "KPI with prior-period comparison", shape["measure"], "Aggregate measure or record count plus a reporting period"),
        ("line", "Trend line", shape["date"] and shape["measure"], "Date or time field plus a measure"),
        ("horizontal_bar", "Skinny horizontal bars", shape["category"] and shape["measure"], "Category or dimension plus a measure"),
        ("stacked_bar", "Stacked comparison", shape["two_categories"] and shape["measure"], "Two categories plus a measure"),
        ("heatmap", "Concentration heatmap", shape["two_categories"] and shape["measure"], "Two dimensions plus a measure"),
        ("scatter", "Relationship scatterplot", shape["two_measures"], "Two numeric measures"),
    ]
    return [
        {"chartType": chart_type, "label": label, "compatible": compatible, "reason": reason}
        for chart_type, label, compatible, reason in candidates
    ]


def _validated_chart_recommendations(
    columns: list[dict[str, str]], suggestion: dict[str, Any] | None
) -> list[dict[str, Any]]:
    recommendations = _chart_recommendations(columns)
    validated_types = {
        str(widget.get("chartType") or "").lower()
        for widget in _valid_suggestion_widgets(suggestion or {})
    }
    aliases = {
        "bar": "horizontal_bar",
        "column": "stacked_bar",
        "area": "line",
        "scorecard": "kpi",
    }
    validated_types |= {aliases[value] for value in validated_types if value in aliases}
    return [
        {
            **item,
            "compatible": bool(item["compatible"] or item["chartType"] in validated_types),
            "reason": item["reason"]
            if item["compatible"]
            else "Validated by executing the proposed query against project data"
            if item["chartType"] in validated_types
            else item["reason"],
        }
        for item in recommendations
    ]


def _valid_suggestion_widgets(suggestion: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        widget
        for widget in suggestion.get("widgets", [])
        if isinstance(widget, dict)
        and str(widget.get("status") or "") == "valid"
        and str(widget.get("sql") or "").strip()
    ]


def _support_status(
    *,
    sources: list[FileSourceMeta],
    suggestion: dict[str, Any] | None,
    missing: list[str],
) -> SupportStatus:
    if not sources or suggestion is None:
        return "not_supported"
    valid = _valid_suggestion_widgets(suggestion)
    if not valid:
        return "not_supported"
    measurable = [
        widget
        for widget in suggestion.get("widgets", [])
        if isinstance(widget, dict) and str(widget.get("sql") or "").strip()
    ]
    if missing or len(valid) < len(measurable):
        return "partially_supported"
    return "fully_supported"


def _questions(req: DashboardDesignRequest) -> list[dict[str, Any]]:
    return [
        {
            "id": "audience",
            "question": "Who should use this dashboard to make decisions?",
            "recommended": req.audience,
            "options": ["operational", "manager", "executive", "analyst"],
        },
        {
            "id": "emphasis",
            "question": "What should the operational story emphasize?",
            "recommended": req.emphasis,
            "options": [
                "balanced_operational_health",
                "risk_and_service_levels",
                "demand_and_capacity",
                "cost_and_productivity",
            ],
        },
    ]


def _ai_prompt(req: DashboardDesignRequest, domain: str = "generic") -> str:
    scope = {
        "create": "Design one complete dashboard.",
        "edit_dashboard": "Redesign the existing dashboard according to the request.",
        "add_insight": "Design only one additional KPI card or chart. Do not redesign the dashboard.",
        "edit_insight": "Design one replacement for the selected dashboard insight.",
    }[req.mode]
    narrative = _DOMAIN_NARRATIVES.get(domain, _DOMAIN_NARRATIVES["generic"])
    return " ".join(
        [
            scope,
            req.prompt.strip(),
            "Use the Tablescope Operational Insight presentation.",
            f"Domain context: {narrative}",
            "Choose charts only when the available data shape supports them.",
            "Use compact KPI cards with correct units and prior-period direction when supported.",
            "Ground every calculation in governed project data; never invent fields or values.",
            f"Audience: {req.audience}.",
            f"Emphasis: {req.emphasis.replace('_', ' ')}.",
            f"Default period: {req.period.replace('_', ' ')}.",
            f"Primary dimension: {req.dimension_label}.",
        ]
    )


@router.post("/actions/dashboard-designer/review")
async def review_dashboard_design(
    req: DashboardDesignRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Profile data and return an executable, user-reviewable design."""
    await _check_project_access(session, context, req.project_id)
    sources = list(
        await session.scalars(
            select(FileSourceMeta).where(
                FileSourceMeta.project_id == req.project_id,
                FileSourceMeta.tenant_id == context.tenant_id,
                FileSourceMeta.archived.is_(False),
            )
        )
    )
    columns = [column for source in sources for column in _source_columns(source)]
    source_profiles = [
        {
            "viewName": source.view_name,
            "fileName": source.file_name,
            "columns": _source_columns(source),
        }
        for source in sources
    ]
    if not sources:
        return {
            "supportStatus": "not_supported",
            "supportSummary": "No governed datasource is assigned to this project.",
            "missingRequirements": ["A datasource containing the records needed for this operational decision"],
            "questions": _questions(req),
            "chartRecommendations": [],
            "sources": [],
            "suggestion": None,
        }

    domain = _infer_domain(req.prompt, columns)
    result = await ai_suggest_dashboards(
        AISuggestDashboardsRequest(
            project_id=req.project_id,
            prompt=_ai_prompt(req, domain=domain),
            audience=req.audience,
            desired_count=3,
        ),
        session=session,
        context=context,
    )
    suggestion = next(
        (
            item
            for item in result.get("suggestions", [])
            if isinstance(item, dict) and _valid_suggestion_widgets(item)
        ),
        None,
    )
    missing = _missing_concepts(req.prompt, columns, domain)
    support = _support_status(sources=sources, suggestion=suggestion, missing=missing)
    if support == "not_supported" and not missing:
        missing = [
            "Fields that can produce a validated measure, dimension or reporting period for this request"
        ]
    if suggestion and req.mode in {"add_insight", "edit_insight"}:
        valid = _valid_suggestion_widgets(suggestion)
        suggestion = dict(suggestion)
        suggestion["widgets"] = valid[:1]
        save_payload = dict(suggestion.get("savePayload") or {})
        save_payload["widgets"] = valid[:1]
        suggestion["savePayload"] = save_payload

    valid_count = len(_valid_suggestion_widgets(suggestion or {}))
    summary = {
        "fully_supported": f"All proposed insights are validated against {len(sources)} project datasource(s).",
        "partially_supported": f"{valid_count} insight(s) are supported; additional fields are required for the remaining request.",
        "not_supported": "The available datasources could not produce a validated insight for this request.",
    }[support]
    return {
        "supportStatus": support,
        "supportSummary": summary,
        "missingRequirements": missing,
        "questions": _questions(req),
        "chartRecommendations": _validated_chart_recommendations(columns, suggestion),
        "sources": source_profiles,
        "suggestion": suggestion,
        "domain": domain,
        "modelUsed": result.get("model_used", ""),
    }


def _operational_widgets(prompt: str, suggestion: dict[str, Any]) -> list[dict[str, Any]]:
    context = suggestion.get("knowledgeGraphContext") or {}
    risks = [str(item) for item in context.get("risks", []) if item]
    opportunities = [
        *[str(item) for item in context.get("opportunities", []) if item],
        *[str(item) for item in context.get("gaps", []) if item],
        *[
            str(widget.get("businessQuestion") or widget.get("title"))
            for widget in suggestion.get("widgets", [])
            if isinstance(widget, dict) and (widget.get("businessQuestion") or widget.get("title"))
        ],
    ]
    now = datetime.now(UTC).isoformat()
    return [
        {
            "id": "operational-brief",
            "type": "operational_brief",
            "title": "Operational Brief",
            "editable": True,
            "aiManaged": True,
            "prompt": prompt,
            "summary": suggestion.get("businessPurpose") or suggestion.get("description") or "AI-grounded operational summary.",
            "items": risks[:3],
            "updatedAt": now,
            "layout": {"position": 0, "width": "wide"},
        },
        {
            "id": "improvement-opportunities",
            "type": "improvement_opportunities",
            "title": "Best Improvement Opportunities",
            "editable": True,
            "aiManaged": True,
            "prompt": prompt,
            "items": opportunities[:5] or ["Continue monitoring the validated measures for the highest-impact change."],
            "updatedAt": now,
            "layout": {"position": 1, "width": "standard"},
        },
    ]


async def _widget_configs(
    *,
    session: AsyncSession,
    context: RequestContext,
    project_id: int,
    suggestion: dict[str, Any],
    start_index: int,
) -> list[dict[str, Any]]:
    # Imported lazily because dashboard_widget intentionally consumes chart
    # mapping helpers re-exported by the ai_proxy aggregator.
    from app.services.dashboard_widget import (
        build_widget_config,
        find_or_create_saved_query,
    )

    sources = list(
        await session.scalars(
            select(FileSourceMeta).where(
                FileSourceMeta.project_id == project_id,
                FileSourceMeta.tenant_id == context.tenant_id,
                FileSourceMeta.archived.is_(False),
            )
        )
    )
    allowed_tables = [source.view_name for source in sources]
    configs: list[dict[str, Any]] = []
    existing_by_sql: dict[str, Any] = {}
    for offset, widget in enumerate(_valid_suggestion_widgets(suggestion)):
        index = start_index + offset
        query = await find_or_create_saved_query(
            session,
            project_id=project_id,
            title=f"AI - {widget.get('title') or 'Dashboard insight'}",
            sql=str(widget["sql"]),
            user_id=context.user_id,
            allowed_tables=allowed_tables,
            existing_by_sql=existing_by_sql,
        )
        config = build_widget_config(
            title=str(widget.get("title") or widget.get("businessQuestion") or "Dashboard insight"),
            query_id=query.id,
            chart_type=str(widget.get("chartType") or "bar"),
            label_column=str(widget.get("labelColumn") or "") or None,
            value_column=str(widget.get("valueColumn") or "") or None,
            explanation=str(widget.get("businessQuestion") or ""),
            visualization_options={
                "colorScheme": "operational_insight",
                "showTooltip": True,
                "showGrid": True,
                "roundedCorners": True,
                "barLayout": "horizontal" if str(widget.get("chartType")) == "horizontal_bar" else "vertical",
            },
            index=index,
            widget_id=f"ai_insight_{int(datetime.now(UTC).timestamp() * 1000)}_{index}",
        )
        if config.get("xColumn"):
            config["interactions"] = {
                "enabled": True,
                "clickAction": "cross_filter",
                "sourceField": config["xColumn"],
                "applyTo": "dashboard",
            }
        configs.append(config)
    return configs


def _history_entry(dashboard: Dashboard, prompt: str, mode: str) -> dict[str, Any]:
    config = dashboard.config or {}
    return {
        "createdAt": datetime.now(UTC).isoformat(),
        "mode": mode,
        "prompt": prompt,
        "widgets": list(config.get("widgets") or []),
        "operationalWidgets": list(config.get("operationalWidgets") or []),
    }


@router.post("/actions/dashboard-designer/apply", status_code=201)
async def apply_dashboard_design(
    req: DashboardDesignApplyRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Apply only a user-approved, query-validated dashboard design."""
    project = await _check_project_access(session, context, req.project_id)
    if req.support_status == "not_supported":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This design has no validated datasource support.",
        )
    if req.support_status == "partially_supported" and not req.accept_partial:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Approve the supported subset before applying this design.",
        )
    suggestion = req.suggestion
    if not _valid_suggestion_widgets(suggestion):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The approved design contains no validated insight queries.",
        )

    group = await resolve_dashboard_group(
        session,
        tenant_id=context.tenant_id,
        project_id=project.id,
        requested_group_id=req.dashboard_group_id,
    )
    dashboard: Dashboard
    created = req.mode == "create"
    if created:
        configs = await _widget_configs(
            session=session,
            context=context,
            project_id=project.id,
            suggestion=suggestion,
            start_index=0,
        )
        dashboard_name = str(suggestion.get("title") or "Operational Insight Dashboard")[:255]
        config = operational_insight_config(
            {
                "widgets": configs,
                "globalFilters": [],
                "dashboardTemplate": {
                    "parameters": {
                        "dimensionLabel": req.dimension_label,
                        "dimensionField": _normal(req.dimension_label) or "dimension",
                        "valueSource": "manual",
                        "manualValues": [],
                        "defaultPeriod": req.period,
                    }
                },
                "operationalWidgets": _operational_widgets(req.prompt, suggestion),
                "aiDesign": {
                    "version": 1,
                    "mode": req.mode,
                    "prompt": req.prompt,
                    "supportStatus": req.support_status,
                    "audience": req.audience,
                    "emphasis": req.emphasis,
                    "updatedAt": datetime.now(UTC).isoformat(),
                },
                "aiDesignHistory": [],
            },
            group=group,
            dashboard_name=dashboard_name,
        )
        dashboard = Dashboard(
            project_id=project.id,
            owner_id=context.user_id,
            tenant_id=context.tenant_id,
            name=dashboard_name,
            description=str(suggestion.get("description") or suggestion.get("businessPurpose") or ""),
            status="draft",
            config=config,
            ai_generated=True,
        )
        session.add(dashboard)
    else:
        if req.dashboard_id is None:
            raise HTTPException(status_code=422, detail="dashboard_id is required")
        loaded_dashboard = await session.get(Dashboard, req.dashboard_id)
        if (
            loaded_dashboard is None
            or loaded_dashboard.project_id != project.id
            or loaded_dashboard.tenant_id != context.tenant_id
        ):
            raise HTTPException(status_code=404, detail="Dashboard not found")
        dashboard = loaded_dashboard
        existing = list((dashboard.config or {}).get("widgets") or [])
        history = list((dashboard.config or {}).get("aiDesignHistory") or [])
        history.append(_history_entry(dashboard, req.prompt, req.mode))
        history = history[-10:]

        if req.mode == "add_insight":
            additions = await _widget_configs(
                session=session,
                context=context,
                project_id=project.id,
                suggestion=suggestion,
                start_index=len(existing),
            )
            next_widgets = [*existing, *additions[:1]]
        elif req.mode == "edit_insight":
            if not req.target_insight_id:
                raise HTTPException(status_code=422, detail="target_insight_id is required")
            replacements = await _widget_configs(
                session=session,
                context=context,
                project_id=project.id,
                suggestion=suggestion,
                start_index=0,
            )
            target = next((item for item in existing if item.get("id") == req.target_insight_id), None)
            if target is None:
                raise HTTPException(status_code=404, detail="Dashboard insight not found")
            replacement = {**replacements[0], **{key: target[key] for key in ("id", "position", "gridX", "gridY", "gridW", "gridH") if key in target}}
            next_widgets = [replacement if item.get("id") == req.target_insight_id else item for item in existing]
        else:
            next_widgets = await _widget_configs(
                session=session,
                context=context,
                project_id=project.id,
                suggestion=suggestion,
                start_index=0,
            )

        next_config = dict(dashboard.config or {})
        next_config.update(
            {
                "widgets": next_widgets,
                "operationalWidgets": _operational_widgets(req.prompt, suggestion)
                if req.mode == "edit_dashboard"
                else next_config.get("operationalWidgets") or _operational_widgets(req.prompt, suggestion),
                "aiDesign": {
                    "version": int((next_config.get("aiDesign") or {}).get("version") or 0) + 1,
                    "mode": req.mode,
                    "prompt": req.prompt,
                    "supportStatus": req.support_status,
                    "audience": req.audience,
                    "emphasis": req.emphasis,
                    "updatedAt": datetime.now(UTC).isoformat(),
                },
                "aiDesignHistory": history,
            }
        )
        metadata = dict(next_config.get("dashboardTemplate") or {})
        parameters = dict(metadata.get("parameters") or {})
        parameters.update(
            {
                "dimensionLabel": req.dimension_label,
                "dimensionField": _normal(req.dimension_label) or "dimension",
                "defaultPeriod": req.period,
            }
        )
        metadata["parameters"] = parameters
        next_config["dashboardTemplate"] = metadata
        dashboard.config = operational_insight_config(
            next_config,
            group=group,
            dashboard_name=dashboard.name,
        )
        dashboard.ai_generated = True

    await session.commit()
    await session.refresh(dashboard)
    return {
        "status": "created" if created else "updated",
        "dashboard_id": dashboard.id,
        "dashboard_name": dashboard.name,
        "insights_created": len(_valid_suggestion_widgets(suggestion)) if req.mode in {"create", "edit_dashboard"} else 1,
        "support_status": req.support_status,
        "dashboard_url": f"/projects/{project.id}/dashboards/{dashboard.id}",
    }
