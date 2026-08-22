"""AI-guided Operational Insight dashboard design and application.

This route is the product-facing replacement for the legacy widget builder.  A
user describes an operational decision, Tablescope profiles the governed
project sources, validates the AI proposal by executing its queries, and then
applies the approved design through the canonical Operational Insight factory.
"""

from __future__ import annotations

import re
from collections import defaultdict
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
from app.models.dashboard_primary_dimension import (
    DashboardPrimaryDimension,
    DashboardPrimaryDimensionAssignment,
    DashboardPrimaryDimensionBinding,
)
from app.models.file_source_meta import FileSourceMeta
from app.models.saved_query import SavedQuery
from app.routes.ai_proxy_dashboard_suggest import ai_suggest_dashboards
from app.routes.ai_proxy_schemas import AISuggestDashboardsRequest
from app.routes.ai_proxy_shared import _check_project_access
from app.services.ask_pipeline import resolve_presentation
from app.services.operational_insight_dashboards import (
    operational_insight_config,
    resolve_dashboard_group,
)
from app.services.visualization_engine import _is_period_dimension, derive_shape, rank_visualizations

router = APIRouter()

DesignMode = Literal["create", "edit_dashboard", "add_insight", "edit_insight"]
SupportStatus = Literal["fully_supported", "partially_supported", "not_supported"]


class ChartOverride(BaseModel):
    """An explicit per-chart request from the "Specific charts" list picker.

    ``chart_type`` is a chart FAMILY (e.g. "bar", "line", "combo" -- the
    same vocabulary as web-ui's CHART_REGISTRY top-level keys / WidgetType);
    ``chart_subtype`` is one of that family's variant values (e.g.
    "stacked_bar", "horizontal_bar"; "" is the family's default variant).
    Left at their defaults ("" / "auto"), the engine decides, matching
    today's behaviour.
    """
    label: str
    chart_type: str = ""
    chart_subtype: str = ""
    unit: str = "auto"


class DashboardDesignRequest(BaseModel):
    project_id: int
    prompt: str = Field(min_length=3, max_length=4000)
    mode: DesignMode = "create"
    dashboard_id: int | None = None
    target_insight_id: str | None = None
    audience: str = "operational"
    emphasis: str = "balanced_operational_health"
    period: str = "1_year"
    currency: Literal["USD", "EUR"] = "USD"
    dimension_label: str = "Site"
    dashboard_group_id: int | None = None
    chart_overrides: list[ChartOverride] = Field(default_factory=list)


class PrimaryDimensionSelection(BaseModel):
    """The AI-discovered dimension candidate a user picked on the review
    screen (see _discover_primary_dimensions) -- ``field`` is the real,
    validated column name; ``label`` is the AI-suggested label as the user
    may have edited it. Never a manually typed Site/Region label."""
    field: str
    label: str


class DashboardDesignApplyRequest(BaseModel):
    project_id: int
    prompt: str = Field(min_length=3, max_length=4000)
    mode: DesignMode = "create"
    dashboard_id: int | None = None
    target_insight_id: str | None = None
    dashboard_group_id: int | None = None
    dashboard_title: str = ""
    # A saved query the user picked as the dimension's real value source
    # (must return exactly one column) -- None keeps today's decorative,
    # unbound "manual" dimension label. Superseded by primary_dimensions for
    # AI-discovered dimensions; kept for a query-backed manual pick.
    primary_dimension_query_id: int | None = None
    # Every AI-discovered dimension candidate the user wants assigned to the
    # dashboard (see PrimaryDimensionSelection) -- ordinarily every candidate
    # that reached full coverage on the review screen, since the header's
    # switch icon (not a separate pick step) is how a user with more than one
    # full-coverage field chooses which is active. The first entry becomes
    # the dashboard's initially active dimension. Empty keeps the
    # pre-discovery fallback (primary_dimension_query_id or a decorative,
    # unbound dimension_label).
    primary_dimensions: list[PrimaryDimensionSelection] = Field(default_factory=list)
    audience: str = "operational"
    emphasis: str = "balanced_operational_health"
    period: str = "1_year"
    currency: Literal["USD", "EUR"] = "USD"
    dimension_label: str = "Dimension"
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
    """Does any actual column name plausibly represent one of these concepts?

    ``field`` (an actual, uncurated column name from the project's data) is
    only checked as a substring of the curated concept term -- never the
    other way for short fields. Without the length floor, a 2-letter column
    name from an unrelated demo source (e.g. "IP", "PL") is trivially a
    substring of *some* long compound concept term ("ip" inside
    "equipmenteffectiveness", "pl" inside "unplanneddowntime"), scoring a
    domain match on pure coincidence rather than a real abbreviation like
    "sla" genuinely abbreviating "slamet".
    """
    return any(
        any(
            _normal(candidate) in field
            or (len(field) >= 3 and field in _normal(candidate))
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
    if len(best_by_prompt) > 1:
        # Column matches AND prompt keywords are genuinely tied across
        # multiple domains -- nothing in the data or the request actually
        # distinguishes them. Picking one anyway is an arbitrary guess
        # driven only by _DOMAIN_CONCEPTS's dict order, which can land on
        # the wrong domain (e.g. a sales project scoring equally on itsm's
        # generic "backlog"/"state" concepts) and then skews the dashboard
        # suggestion prompt and "missing concept" messaging toward a domain
        # the project isn't actually about. "generic" applies no
        # domain-specific bias, so it's the safe answer when truly tied.
        return "generic"
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


_CHART_LABELS: dict[str, str] = {
    "kpi": "KPI with prior-period comparison",
    "line": "Trend line",
    "dual_line": "Dual trend lines",
    "area": "Area trend",
    "bar": "Bar comparison",
    "horizontal_bar": "Skinny horizontal bars",
    "stacked_bar": "Stacked comparison",
    "grouped_bar": "Grouped comparison",
    "combo": "Combo (bar + line)",
    "heatmap": "Concentration heatmap",
    "scatter": "Relationship scatterplot",
    "bubble": "Relationship bubbles",
    "pie": "Category mix",
    "donut": "Category mix (donut)",
    "treemap": "Proportional treemap",
    "funnel": "Funnel",
    "radar": "Radar comparison",
    "table": "Detail table",
}


def _chart_label(chart_type: str, chart_style: str) -> str:
    return (
        _CHART_LABELS.get(chart_style)
        or _CHART_LABELS.get(chart_type)
        or chart_type.replace("_", " ").title()
    )


def _engine_chart_recommendations(
    columns: list[dict[str, str]], suggestion: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """"Charts compatible with this data", ranked by the same engine that
    grounds each widget's chart type (``visualization_engine.rank_visualizations``)
    instead of a separate column-name heuristic.

    Ranks every valid widget's real executed preview data (already captured
    by ``ai_suggest_dashboards`` -- see ``_grounded_chart_selection`` for the
    same data used to ground the widget itself) and merges results across
    widgets, keeping the highest-confidence decision per chart family so the
    review step's compatibility list agrees with what widgets actually get
    built with. Falls back to the project-level column-shape heuristic only
    when there's no executed preview data yet to rank against.
    """
    best_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for widget in _valid_suggestion_widgets(suggestion or {}):
        preview = widget.get("previewData") or {}
        preview_columns = [str(c) for c in (preview.get("columns") or [])]
        preview_rows = list(preview.get("rows") or [])
        if not preview_columns or not preview_rows:
            continue
        for candidate in rank_visualizations(preview_columns, preview_rows, limit=10):
            decision = candidate.decision
            key = (decision.chart_type.value, decision.chart_style)
            existing = best_by_key.get(key)
            if existing is not None and existing["_confidence"] >= decision.confidence:
                continue
            best_by_key[key] = {
                "chartType": decision.chart_style or decision.chart_type.value,
                "label": _chart_label(decision.chart_type.value, decision.chart_style),
                "compatible": True,
                "reason": decision.reason,
                "_confidence": decision.confidence,
            }

    if not best_by_key:
        return _chart_recommendations(columns)

    ranked = sorted(best_by_key.values(), key=lambda item: -item["_confidence"])
    return [{k: v for k, v in item.items() if k != "_confidence"} for item in ranked]


def _valid_suggestion_widgets(suggestion: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        widget
        for widget in suggestion.get("widgets", [])
        if isinstance(widget, dict)
        and str(widget.get("status") or "") == "valid"
        and str(widget.get("sql") or "").strip()
    ]


def _normalize_title(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _dimension_label(field: str) -> str:
    """AI-suggested starting label for a discovered field (e.g.
    "business_unit" -> "Business Unit") -- editable by the user afterward,
    both on the review screen and later from the dashboard header."""
    return re.sub(r"[_\-]+", " ", field).strip().title() or field


def _discover_primary_dimensions(suggestion: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Find categorical fields shared across the proposed widgets'
    already-executed previews.

    A "primary dimension" candidate is a real, validated column -- never a
    manually typed Site/Region label -- found in at least two widgets'
    result sets. Coverage is computed against every validated widget
    (including KPIs, which rarely carry a categorical column and are
    therefore usually the incompatible case the review screen must surface).
    Widgets are identified by title, the same identity ``_apply_chart_overrides``
    already uses to match a "Specific charts" request to a proposed widget --
    the frontend removes an incompatible widget by title before re-submitting,
    so apply-time recomputation must use the same key to see that removal.
    """
    widgets = _valid_suggestion_widgets(suggestion or {})
    if len(widgets) < 2:
        return []

    widget_dims: dict[str, set[str]] = {}
    field_widgets: dict[str, list[str]] = defaultdict(list)
    for widget in widgets:
        title = str(widget.get("title") or "")
        if not title:
            continue
        preview = widget.get("previewData") or {}
        cols = list(preview.get("columns") or [])
        rows = list(preview.get("rows") or [])
        if not cols or not rows:
            widget_dims[title] = set()
            continue
        shape = derive_shape(cols, rows)
        dims = {name for name in shape.dimensions if not _is_period_dimension(shape, name)}
        widget_dims[title] = dims
        for field in dims:
            field_widgets[field].append(title)

    all_titles = list(widget_dims.keys())
    candidates: list[dict[str, Any]] = []
    for field, compatible in field_widgets.items():
        if len(compatible) < 2:
            continue
        incompatible = [title for title in all_titles if title not in compatible]
        candidates.append({
            "field": field,
            "label": _dimension_label(field),
            "compatibleCount": len(compatible),
            "totalCount": len(all_titles),
            "fullCoverage": len(incompatible) == 0,
            "compatibleWidgets": list(compatible),
            "incompatibleWidgets": [{"title": title} for title in incompatible],
        })
    candidates.sort(key=lambda c: (not c["fullCoverage"], -c["compatibleCount"], c["field"]))
    return candidates


def _apply_chart_overrides(
    suggestion: dict[str, Any], overrides: list[ChartOverride]
) -> None:
    """Force a widget's chart type / value scale from an explicit per-chart
    request in the designer's "Specific charts" list, matched to the AI's
    widget by title-word overlap rather than list position -- the AI's
    proposed title doesn't always match the requested label verbatim, and
    the request/widget counts can differ (see the "Requested N charts; AI
    proposed M" mismatch the review step already surfaces). An override
    left at its defaults (chart_type "", unit "auto") is a no-op, so this
    changes nothing for a request that never touched these controls.

    Mutates ``suggestion["widgets"]`` in place: sets ``_chartTypeForced`` so
    ``_grounded_chart_selection`` keeps this exact family/subtype instead of
    re-deriving it from the ranking engine, and ``_valueScale`` for
    ``_widget_configs`` to copy into ``visualizationOptions`` at apply time.
    """
    real_overrides = [o for o in overrides if o.chart_type or o.unit not in ("", "auto")]
    if not real_overrides:
        return
    candidates = [
        w for w in (suggestion.get("widgets") or [])
        if isinstance(w, dict) and str(w.get("status") or "") == "valid"
    ]
    for override in real_overrides:
        target_words = set(_normalize_title(override.label).split())
        if not target_words:
            continue
        best: dict[str, Any] | None = None
        best_score = 0.0
        for widget in candidates:
            title_words = set(_normalize_title(str(widget.get("title") or "")).split())
            if not title_words:
                continue
            overlap = len(title_words & target_words) / len(title_words | target_words)
            if overlap > best_score:
                best_score, best = overlap, widget
        if best is None or best_score < 0.25:
            continue
        if override.chart_type:
            best["chartType"] = override.chart_type
            best["_chartTypeForced"] = True
            best["_forcedChartSubtype"] = override.chart_subtype
        if override.unit and override.unit != "auto":
            best["_valueScale"] = override.unit
        candidates.remove(best)


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
            (
                "Match the ITSM dashboard hierarchy: shared header controls, full-width "
                "operational brief, KPI row, balanced chart grid, and improvement "
                "opportunities at bottom-right."
            ),
            "Never recommend a full-width horizontal bar chart.",
            (
                "When the user requests display units such as thousands, millions or "
                "billions, return yAxisScale using that exact plural value; do not divide "
                "the SQL result."
            ),
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
        stop_after_first_valid=True,
    )
    suggestion = next(
        (
            item
            for item in result.get("suggestions", [])
            if isinstance(item, dict) and _valid_suggestion_widgets(item)
        ),
        None,
    )
    if suggestion is not None:
        _apply_chart_overrides(suggestion, req.chart_overrides)
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
        "chartRecommendations": _engine_chart_recommendations(columns, suggestion),
        "sources": source_profiles,
        "suggestion": suggestion,
        "domain": domain,
        "modelUsed": result.get("model_used", ""),
        "primaryDimensionCandidates": _discover_primary_dimensions(suggestion),
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
    summary = str(
        suggestion.get("businessPurpose")
        or suggestion.get("description")
        or "AI-grounded operational summary."
    )
    driver = next(
        (
            str(widget.get("businessQuestion") or widget.get("title"))
            for widget in suggestion.get("widgets", [])
            if isinstance(widget, dict) and (widget.get("businessQuestion") or widget.get("title"))
        ),
        summary,
    )
    return [
        {
            "id": "operational-brief",
            "type": "operational_brief",
            "title": "Operational Brief",
            "editable": True,
            "aiManaged": True,
            "prompt": prompt,
            "summary": summary,
            "items": [
                {"label": "Backing risk", "detail": risks[0] if risks else summary, "tone": "critical"},
                {"label": "Primary driver", "detail": driver, "tone": "warning"},
                {
                    "label": "Recommended action",
                    "detail": opportunities[0]
                    if opportunities
                    else "Review the highest-impact validated measure and act on its leading contributor.",
                    "tone": "positive",
                },
            ],
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
            "items": opportunities[:5]
            or ["Continue monitoring the validated measures for the highest-impact change."],
            "updatedAt": now,
            "layout": {
                "position": 1,
                "width": "standard",
                "gridX": 9,
                "gridY": 5,
                "gridW": 3,
                "gridH": 3,
            },
        },
    ]


def _requested_axis_scale(widget: dict[str, Any]) -> str | None:
    """Normalize scale hints supplied by the AI design contract."""
    candidates = [
        widget.get("yAxisScale"),
        widget.get("axisScale"),
        widget.get("numberScale"),
        widget.get("displayScale"),
        widget.get("valueFormat"),
    ]
    text = " ".join(str(value).lower() for value in candidates if value)
    for scale in ("thousands", "millions", "billions"):
        if scale in text or scale[:-1] in text:
            return scale
    return None


def _apply_operational_layout(configs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Give new AI dashboards the same visual hierarchy as ITSM Insights.

    KPIs occupy a single top row, then charts fill a balanced grid. A
    horizontal ranking bar is capped at half width so it never stretches the
    full page (see the ITSM Insights shell, which does the same), leaving the
    bottom-right cell free for the "Best Improvement Opportunities" panel that
    ``_operational_widgets`` pins there.
    """
    kpis = [config for config in configs if config.get("type") == "kpi"]
    charts = [config for config in configs if config.get("type") != "kpi"]
    kpi_width = 6 if len(kpis) <= 2 else 4 if len(kpis) == 3 else 3
    for index, config in enumerate(kpis):
        config.update({"gridX": (index * kpi_width) % 12, "gridY": 0, "gridW": kpi_width, "gridH": 2})

    placements = [
        {"gridX": 0, "gridY": 2, "gridW": 6, "gridH": 6},
        {"gridX": 6, "gridY": 2, "gridW": 6, "gridH": 3},
        {"gridX": 6, "gridY": 5, "gridW": 3, "gridH": 3},
    ]
    for index, config in enumerate(charts):
        placement = placements[index] if index < len(placements) else {
            "gridX": (index - len(placements)) % 2 * 6,
            "gridY": 8 + ((index - len(placements)) // 2) * 4,
            "gridW": 6,
            "gridH": 4,
        }
        horizontal = config.get("chartSubtype") in {
            "horizontal_bar",
            "stacked_horizontal",
            "population_pyramid",
        } or (config.get("visualizationOptions") or {}).get("barLayout") == "horizontal"
        if horizontal:
            placement = {**placement, "gridW": min(int(placement["gridW"]), 6)}
        config.update(placement)
    ordered = [*kpis, *charts]
    # ``build_widget_config`` stamped ``position`` from the pre-layout index;
    # re-stamp it so the persisted order matches the grid hierarchy above.
    # Counting from the lowest position already present (rather than 0) keeps
    # ``_widget_configs``' ``start_index`` offset intact -- "add_insight"
    # appends after the dashboard's existing widgets and must not renumber
    # itself back to the front.
    positions = [config["position"] for config in ordered if "position" in config]
    base = min(positions) if positions else 0
    for index, config in enumerate(ordered):
        if "position" in config:
            config["position"] = base + index
    return ordered


def _grounded_chart_selection(
    widget: dict[str, Any],
) -> tuple[str, str | None, str | None, str | None]:
    """Ground a suggested widget's chart type in the same ranking engine
    Business Insight and Ask Anything use, instead of trusting the LLM's
    ``chartType`` field unconstrained.

    ``ai_suggest_dashboards`` already executes each widget's SQL during
    review and attaches the result as ``previewData`` (see
    ``_render_preview_widgets`` in ``ai_proxy_dashboard_suggest.py``), so no
    extra query runs here. The LLM's own chart type is passed as
    ``intent_hint``: the engine still weights toward it when the data shape
    supports it, but a shape that can't actually render that way (e.g. a
    single numeric column the LLM called "line") is corrected rather than
    persisted as-is. Falls back to the LLM's raw fields when there's no
    preview data to rank, or when the engine can't find a plottable shape
    (resolves to "table") -- a dashboard widget defaulting to the LLM's
    guess beats defaulting to a table.

    The engine already recognises a time axis with two measures and ranks
    ``ChartType.COMBO`` above a plain line for it (see
    ``visualization_engine/recommend.py``, "Time series -> line / area /
    combo"), returning both ``y_field`` and ``y2_field``. This is the same
    decision Business Insight's combo cards rely on -- the fix here is
    consuming the engine's second value column instead of discarding it,
    not a separate heuristic.
    """
    chart_type = str(widget.get("chartType") or "bar")
    label_column = str(widget.get("labelColumn") or "") or None
    value_column = str(widget.get("valueColumn") or "") or None
    # An explicit per-chart type the user picked in the designer (see
    # _apply_chart_overrides) always wins over the engine's own ranking --
    # everything else about the widget (label/value columns) still comes
    # from the engine below, since only the final family/subtype is forced.
    forced_type = chart_type if widget.get("_chartTypeForced") else None

    preview = widget.get("previewData") or {}
    columns = [str(c) for c in (preview.get("columns") or [])]
    rows = list(preview.get("rows") or [])
    if not columns or not rows:
        return forced_type or chart_type, label_column, value_column, None

    presentation = resolve_presentation(columns, rows, intent_hint=chart_type)
    chart = presentation.chart
    if not chart or chart.get("type") in (None, "table"):
        return forced_type or chart_type, label_column, value_column, None

    # `_map_chart_type`/`_map_chart_subtype` (ai_proxy_widget_helpers) key on
    # this same compound-string convention -- a subtype like "horizontal_bar"
    # or "donut" is itself a top-level key; a bare family ("line", "kpi", ...)
    # is too. Falling back to "bar" only if the engine's own family is empty,
    # which resolve_presentation never actually returns.
    grounded_type = forced_type or str(chart.get("subtype") or chart.get("type") or "bar")
    grounded_label = chart.get("labelColumn") or label_column
    value_columns = chart.get("valueColumns") or []
    grounded_value = value_columns[0] if value_columns else value_column
    grounded_value_2 = value_columns[1] if len(value_columns) > 1 else None
    # Forcing combo when the engine ranked a single-metric shape (so it
    # never found a second value column): fall back to the widget's own
    # second value field so the forced combo still has two series to plot.
    if forced_type == "combo" and not grounded_value_2:
        grounded_value_2 = str(widget.get("valueColumn2") or "") or None
    return grounded_type, grounded_label, grounded_value, grounded_value_2


def _widget_date_field(
    widget: dict[str, Any], label_column: str | None
) -> dict[str, Any] | None:
    """Detect whether a widget's label column is a real time/period axis.

    Query-backed widgets replay their saved SQL verbatim with no other hook
    for the dashboard's date-range control (DashboardViewer.tsx's
    fetchWidgetData only builds a filtered query for datasource-backed
    widgets) -- buildRuntimeWidgetFilters only applies a date range when the
    widget carries an enabled dateField naming a real period column, so
    AI-generated widgets need this set explicitly or the period control is
    silently a no-op for them.
    """
    if not label_column:
        return None
    preview = widget.get("previewData") or {}
    columns = [str(c) for c in (preview.get("columns") or [])]
    rows = list(preview.get("rows") or [])
    if not columns or not rows or label_column not in columns:
        return None
    shape = derive_shape(columns, rows)
    if not _is_period_dimension(shape, label_column):
        return None
    return {"enabled": True, "field": label_column}


async def _dimension_parameters(
    session: AsyncSession,
    *,
    project_id: int,
    dimension_label: str,
    default_period: str,
    query_id: int | None,
) -> dict[str, Any]:
    """Build the dashboard template's dimension parameters.

    A picked single-column query binds the dimension to real values (the
    same ``valueSource: "query"`` mechanism DashboardViewer.tsx already
    hydrates for manually-built dashboards); otherwise falls back to
    today's decorative, unbound "manual" label with no values.
    """
    params = {
        "dimensionLabel": dimension_label,
        "dimensionField": _normal(dimension_label) or "dimension",
        "manualValues": [],
        "defaultPeriod": default_period,
    }
    if query_id is not None:
        query = await session.scalar(
            select(SavedQuery).where(
                SavedQuery.id == query_id,
                SavedQuery.project_id == project_id,
            )
        )
        if query is not None:
            return {**params, "valueSource": "query", "queryId": query_id}
    return {**params, "valueSource": "manual"}


_SOURCE_VIEW_RE = re.compile(r'(?i)FROM\s+"([^"]+)"')


def _widget_source_view(widget: dict[str, Any]) -> str | None:
    """Best-effort extraction of the primary source view a widget's
    generated SQL reads from -- the query-generation pipeline consistently
    emits ``FROM "view_name"``, so the first quoted identifier after FROM is
    the view. Used only to key the reusable DashboardPrimaryDimension record
    and to build its distinct-values query; a chart that already validated
    and ran is what determines coverage, not this string."""
    match = _SOURCE_VIEW_RE.search(str(widget.get("sql") or ""))
    return match.group(1) if match else None


async def _apply_primary_dimension_selection(
    session: AsyncSession,
    *,
    context: RequestContext,
    project_id: int,
    dashboard_id: int,
    suggestion: dict[str, Any],
    configs: list[dict[str, Any]],
    selection: PrimaryDimensionSelection,
    default_period: str,
    make_active: bool = True,
) -> dict[str, Any]:
    """Validate an AI-discovered dimension against the FINAL widget list
    (after any incompatible-chart removal) and persist it.

    Recomputing here -- server-side, against the design that's actually
    about to be saved -- rather than trusting the client's earlier review-
    step coverage is what makes a stale or still-partial selection a 409
    instead of a silently wrong dashboard: the review screen's coverage was
    computed against the *proposed* widget list, which the client may have
    since edited (a "Remove incompatible chart" click, another regenerate).

    A dashboard can have more than one full-coverage dimension assigned (the
    header's switch icon toggles between them); ``make_active=False`` for
    every selection after the first keeps exactly one assignment active at
    a time instead of every call in a batch clobbering the previous one.
    """
    candidates = {c["field"]: c for c in _discover_primary_dimensions(suggestion)}
    candidate = candidates.get(selection.field)
    if candidate is None or not candidate["fullCoverage"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"'{selection.field}' is no longer a fully-covered dimension for this "
                "design. Remove the incompatible chart(s) or re-analyze before applying."
            ),
        )

    widgets_by_title = {str(w.get("title") or ""): w for w in _valid_suggestion_widgets(suggestion)}
    source_view = next(
        (
            view
            for title in candidate["compatibleWidgets"]
            if (view := _widget_source_view(widgets_by_title.get(title, {}))) is not None
        ),
        None,
    )
    if source_view is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Could not resolve a source view for dimension '{selection.field}'.",
        )

    dimension = await session.scalar(
        select(DashboardPrimaryDimension).where(
            DashboardPrimaryDimension.tenant_id == context.tenant_id,
            DashboardPrimaryDimension.project_id == project_id,
            DashboardPrimaryDimension.source_view == source_view,
            DashboardPrimaryDimension.field == selection.field,
        )
    )
    if dimension is None:
        dimension = DashboardPrimaryDimension(
            tenant_id=context.tenant_id,
            project_id=project_id,
            source_view=source_view,
            field=selection.field,
            default_label=_dimension_label(selection.field),
        )
        session.add(dimension)
        await session.flush()

    from app.services.dashboard_widget import find_or_create_saved_query

    quoted_field = f'"{selection.field}"'
    quoted_view = f'"{source_view}"'
    distinct_query = await find_or_create_saved_query(
        session,
        project_id=project_id,
        title=f"AI - {selection.label} values",
        sql=f"SELECT DISTINCT {quoted_field} AS value FROM {quoted_view} ORDER BY 1",
        user_id=context.user_id,
        allowed_tables=[source_view],
    )

    existing_assignments = list(
        await session.scalars(
            select(DashboardPrimaryDimensionAssignment).where(
                DashboardPrimaryDimensionAssignment.dashboard_id == dashboard_id,
            )
        )
    )
    if make_active:
        for assignment in existing_assignments:
            assignment.is_active = False

    assignment = next(
        (a for a in existing_assignments if a.dimension_id == dimension.id), None,
    )
    if assignment is None:
        assignment = DashboardPrimaryDimensionAssignment(
            tenant_id=context.tenant_id,
            project_id=project_id,
            dashboard_id=dashboard_id,
            dimension_id=dimension.id,
            label=selection.label,
            is_active=make_active,
            position=len(existing_assignments),
        )
        session.add(assignment)
    else:
        assignment.label = selection.label
        if make_active:
            assignment.is_active = True
    await session.flush()

    persisted_id_by_title = {
        str(config.get("title") or ""): str(config.get("id"))
        for config in configs
        if config.get("id")
    }
    await session.execute(
        DashboardPrimaryDimensionBinding.__table__.delete().where(
            DashboardPrimaryDimensionBinding.assignment_id == assignment.id,
        )
    )
    for title in candidate["compatibleWidgets"]:
        widget_id = persisted_id_by_title.get(title)
        if widget_id is None:
            continue
        session.add(
            DashboardPrimaryDimensionBinding(
                tenant_id=context.tenant_id,
                project_id=project_id,
                assignment_id=assignment.id,
                widget_id=widget_id,
                column_name=selection.field,
            )
        )

    return await _dimension_parameters(
        session,
        project_id=project_id,
        dimension_label=selection.label,
        default_period=default_period,
        query_id=distinct_query.id,
    )


_CURRENCY_SYMBOLS: dict[str, str] = {"USD": "$", "EUR": "€"}


async def _widget_configs(
    *,
    session: AsyncSession,
    context: RequestContext,
    project_id: int,
    suggestion: dict[str, Any],
    start_index: int,
    currency: Literal["USD", "EUR"] = "USD",
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
        chart_type, label_column, value_column, value_column_2 = _grounded_chart_selection(widget)
        # A display-unit request ("thousands") only divides the rendered axis
        # tick labels; the widget's SQL and raw values are left untouched.
        axis_scale = _requested_axis_scale(widget)
        config = build_widget_config(
            title=str(widget.get("title") or widget.get("businessQuestion") or "Dashboard insight"),
            query_id=query.id,
            chart_type=chart_type,
            label_column=label_column,
            value_column=value_column,
            value_column_2=value_column_2,
            explanation=str(widget.get("businessQuestion") or ""),
            visualization_options={
                "colorScheme": "operational_insight",
                "showTooltip": True,
                "showGrid": True,
                "roundedCorners": True,
                "barLayout": "horizontal" if chart_type == "horizontal_bar" else "vertical",
                **({"yAxisScale": axis_scale} if axis_scale else {}),
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
        date_field = _widget_date_field(widget, label_column)
        if date_field:
            config["dateField"] = date_field
        value_scale = widget.get("_valueScale")
        if value_scale:
            config["visualizationOptions"]["valueScale"] = value_scale
        config["visualizationOptions"]["currencySymbol"] = _CURRENCY_SYMBOLS[currency]
        # A forced chart type/subtype from the designer's picker is already
        # the exact WidgetType + variant value the frontend registry uses --
        # _map_chart_type's narrower planner vocabulary (built for LLM-guessed
        # strings) doesn't recognise all of them and can map some outright
        # wrong for this purpose (e.g. "heatmap" maps to a table elsewhere).
        # An explicit user pick always wins over that mapping.
        if widget.get("_chartTypeForced"):
            config["type"] = chart_type
            config["chartSubtype"] = widget.get("_forcedChartSubtype") or ""
        configs.append(config)
    return _apply_operational_layout(configs)


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
            currency=req.currency,
        )
        dashboard_name = (
            req.dashboard_title.strip()
            or str(suggestion.get("title") or "Operational Insight Dashboard")
        )[:255]
        dimension_parameters = await _dimension_parameters(
            session,
            project_id=project.id,
            dimension_label=req.dimension_label,
            default_period=req.period,
            query_id=req.primary_dimension_query_id,
        )
        config = operational_insight_config(
            {
                "widgets": configs,
                "globalFilters": [],
                "dashboardTemplate": {"parameters": dimension_parameters},
                "operationalWidgets": _operational_widgets(req.prompt, suggestion),
                "operationalLayoutVersion": 2,
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
            # AI-generated (operational_insight) dashboards go live immediately --
            # the ITSM-style header they render with has no draft/publish concept.
            status="published",
            config=config,
            ai_generated=True,
        )
        session.add(dashboard)
        if req.primary_dimensions:
            await session.flush()  # assigns dashboard.id
            dimension_parameters = None
            for index, selection in enumerate(req.primary_dimensions):
                result = await _apply_primary_dimension_selection(
                    session,
                    context=context,
                    project_id=project.id,
                    dashboard_id=dashboard.id,
                    suggestion=suggestion,
                    configs=configs,
                    selection=selection,
                    default_period=req.period,
                    make_active=(index == 0),
                )
                if index == 0:
                    dimension_parameters = result
            next_config = dict(dashboard.config)
            metadata = dict(next_config.get("dashboardTemplate") or {})
            metadata["parameters"] = dimension_parameters
            next_config["dashboardTemplate"] = metadata
            dashboard.config = operational_insight_config(
                next_config, group=group, dashboard_name=dashboard_name,
            )
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
                currency=req.currency,
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
                currency=req.currency,
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
                currency=req.currency,
            )

        next_config = dict(dashboard.config or {})
        next_config.update(
            {
                "widgets": next_widgets,
                "operationalWidgets": _operational_widgets(req.prompt, suggestion)
                if req.mode == "edit_dashboard"
                else next_config.get("operationalWidgets") or _operational_widgets(req.prompt, suggestion),
                "operationalLayoutVersion": 2,
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
        if req.mode == "edit_dashboard" and req.primary_dimensions:
            for index, selection in enumerate(req.primary_dimensions):
                result = await _apply_primary_dimension_selection(
                    session,
                    context=context,
                    project_id=project.id,
                    dashboard_id=dashboard.id,
                    suggestion=suggestion,
                    configs=next_widgets,
                    selection=selection,
                    default_period=req.period,
                    make_active=(index == 0),
                )
                if index == 0:
                    parameters = result
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


class WidgetChartCandidatesRequest(BaseModel):
    project_id: int
    columns: list[str]
    rows: list[dict[str, Any]]


@router.post("/actions/dashboard-designer/chart-candidates")
async def dashboard_widget_chart_candidates(
    req: WidgetChartCandidatesRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Rank alternative chart types for one already-fetched widget result.

    The same chart-fit ranking Business Insight cards use
    (``ask_pipeline.resolve_presentation``), reused here rather than
    reimplemented, so a dashboard widget's "Chart options" picker agrees with
    every other surface on what charts a given data shape supports. Takes
    columns/rows the caller already fetched for the widget (the dashboard
    page already has this from rendering it) instead of re-executing SQL.
    """
    await _check_project_access(session, context, req.project_id)

    presentation = resolve_presentation(req.columns, req.rows)
    return presentation.to_dict()
