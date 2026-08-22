from __future__ import annotations

import pytest

from app.auth.jwt import create_access_token
from app.models.file_source_meta import FileSourceMeta
from app.routes.ai_proxy_dashboard_designer import (
    ChartOverride,
    PrimaryDimensionSelection,
    _apply_chart_overrides,
    _apply_operational_layout,
    _apply_primary_dimension_selection,
    _chart_recommendations,
    _concept_supported,
    _discover_primary_dimensions,
    _engine_chart_recommendations,
    _grounded_chart_selection,
    _infer_domain,
    _missing_concepts,
    _operational_widgets,
    _requested_axis_scale,
    _support_status,
    _widget_date_field,
)
from app.services.supabase_auth_service import SupabaseAuthService, SupabaseUser

pytestmark = pytest.mark.anyio


class _FakeSupabase(SupabaseAuthService):
    def __init__(self) -> None:
        pass

    async def create_or_invite_user(
        self, email, *, first_name=None, last_name=None, redirect_to=None
    ) -> SupabaseUser:
        return SupabaseUser(
            id=f"supa-{email}",
            email=email,
            created=True,
            action_link=f"https://invite/{email}",
        )


class _FakeEmail:
    async def send_transactional_email(
        self, *, to, template, variables, subject=None, reply_to=None
    ) -> bool:
        return True


@pytest.fixture(autouse=True)
def _mock_supabase(monkeypatch):
    import app.routes.tenants_users as tenants_module

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)


def _editor_headers(tenant_id: int, user_id: int) -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role="editor"
    )
    return {"Authorization": f"Bearer {token}"}


async def _tenant_project(client, service_headers, slug: str = "dd-chart-cand"):
    r = await client.post(
        "/api/tenants",
        json={"slug": slug, "name": "Dashboard Designer Chart Candidates"},
        headers=service_headers,
    )
    assert r.status_code == 201
    tenant = r.json()

    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": f"{slug}@test.com",
            "display_name": "DD User",
            "role": "editor",
            "external_id": f"ext-{slug}",
        },
        headers=service_headers,
    )
    assert r.status_code == 201
    user = r.json()
    headers = _editor_headers(tenant["id"], user["id"])

    r = await client.post(
        "/api/projects",
        json={"name": "Sales Project", "description": "t", "is_shared": False},
        headers=headers,
    )
    assert r.status_code == 201
    project = r.json()
    return tenant, project, headers


def _source() -> FileSourceMeta:
    return FileSourceMeta(
        id=1,
        tenant_id=33,
        owner_id=7,
        project_id=44,
        view_name="incidents",
        file_name="incidents.csv",
        vdb_type="user",
        archived=False,
    )


def test_missing_concepts_only_reports_requested_unsupported_fields() -> None:
    columns = [
        {"name": "incident_number", "type": "string"},
        {"name": "opened_at", "type": "datetime"},
        {"name": "state", "type": "string"},
        {"name": "site", "type": "string"},
    ]

    missing = _missing_concepts(
        "Show backlog, site performance, resolution SLA and assignment group",
        columns,
        "itsm",
    )

    assert "backlog state" not in missing
    assert "site or region" not in missing
    assert "SLA performance" in missing
    assert "assignment group" in missing


def test_chart_recommendations_follow_detected_data_shape() -> None:
    recommendations = _chart_recommendations(
        [
            {"name": "opened_at", "type": "datetime"},
            {"name": "category", "type": "string"},
            {"name": "site", "type": "string"},
            {"name": "resolution_hours", "type": "decimal"},
        ]
    )
    compatible = {item["chartType"] for item in recommendations if item["compatible"]}
    assert {"kpi", "line", "horizontal_bar", "heatmap"}.issubset(compatible)


def test_grounded_chart_selection_corrects_a_chart_type_the_data_cannot_support() -> None:
    """The LLM asked for a KPI (single aggregate value); the executed preview
    is multi-row categorical data, which no KPI can render. Grounding through
    the shared ranking engine must not persist that mismatch."""
    widget = {
        "chartType": "kpi",
        "labelColumn": "",
        "valueColumn": "incident_count",
        "previewData": {
            "columns": ["region", "incident_count"],
            "rows": [
                {"region": "East", "incident_count": 42},
                {"region": "West", "incident_count": 31},
                {"region": "North", "incident_count": 18},
                {"region": "South", "incident_count": 27},
            ],
        },
    }

    chart_type, label_column, value_column, value_column_2 = _grounded_chart_selection(widget)

    assert chart_type != "kpi"
    assert label_column == "region"
    assert value_column == "incident_count"
    assert value_column_2 is None


def test_grounded_chart_selection_falls_back_without_preview_data() -> None:
    """A widget with no executed preview (e.g. narrative, or the query
    failed) has nothing to ground against -- keep the LLM's raw fields
    rather than guessing from nothing."""
    widget = {"chartType": "line", "labelColumn": "month", "valueColumn": "revenue"}

    assert _grounded_chart_selection(widget) == ("line", "month", "revenue", None)


def test_grounded_chart_selection_falls_back_when_engine_finds_no_chart() -> None:
    """A shape with no plottable measure resolves to a table in the shared
    engine; a dashboard widget defaulting to the LLM's original guess beats
    silently downgrading every such widget to a table."""
    widget = {
        "chartType": "bar",
        "labelColumn": "note",
        "valueColumn": "",
        "previewData": {"columns": ["note"], "rows": [{"note": "hello"}]},
    }

    chart_type, label_column, _value_column, value_column_2 = _grounded_chart_selection(widget)

    assert chart_type == "bar"
    assert label_column == "note"
    assert value_column_2 is None


def test_grounded_chart_selection_produces_a_combo_for_two_measures_over_time() -> None:
    """A time axis with two measures (e.g. actual vs. forecast revenue) is
    exactly the shape the shared engine already ranks ChartType.COMBO for,
    above a plain line (see visualization_engine/recommend.py). Grounding
    must surface the engine's second value column, not just the first."""
    widget = {
        "chartType": "line",
        "labelColumn": "month",
        "valueColumn": "actual_revenue",
        "previewData": {
            "columns": ["month", "actual_revenue", "forecast_revenue"],
            "rows": [
                {"month": "2026-01", "actual_revenue": 100000, "forecast_revenue": 98000},
                {"month": "2026-02", "actual_revenue": 110000, "forecast_revenue": 105000},
                {"month": "2026-03", "actual_revenue": 108000, "forecast_revenue": 112000},
                {"month": "2026-04", "actual_revenue": 121000, "forecast_revenue": 118000},
            ],
        },
    }

    chart_type, label_column, value_column, value_column_2 = _grounded_chart_selection(widget)

    assert chart_type == "combo"
    assert label_column == "month"
    assert value_column == "actual_revenue"
    assert value_column_2 == "forecast_revenue"


def test_engine_chart_recommendations_ranks_widgets_from_executed_preview_data() -> None:
    """The "charts compatible with this data" panel is ranked from each
    widget's real executed preview data via the shared engine, not project
    column metadata -- it must produce a confident result even when that
    metadata is sparse/absent, exactly the case the old heuristic needed a
    special-cased validation path for."""
    recommendations = _engine_chart_recommendations(
        [],
        {
            "widgets": [
                {
                    "status": "valid",
                    "sql": 'SELECT "site", COUNT(*) AS "count" FROM "incidents" GROUP BY "site"',
                    "chartType": "bar",
                    "previewData": {
                        "columns": ["site", "count"],
                        "rows": [
                            {"site": "East", "count": 42},
                            {"site": "West", "count": 31},
                            {"site": "North", "count": 18},
                        ],
                    },
                }
            ]
        },
    )
    assert recommendations
    assert all(item["compatible"] for item in recommendations)
    assert any("bar" in item["chartType"] for item in recommendations)


def test_engine_chart_recommendations_falls_back_without_preview_data() -> None:
    """No widgets (or none with executed preview data) yet -- fall back to
    the project-level column-shape heuristic rather than an empty panel."""
    columns = [
        {"name": "opened_at", "type": "datetime"},
        {"name": "site", "type": "string"},
        {"name": "resolution_hours", "type": "decimal"},
    ]
    assert _engine_chart_recommendations(columns, None) == _chart_recommendations(columns)


def test_engine_chart_recommendations_surfaces_combo_for_two_measures_over_time() -> None:
    """The compatibility panel must agree with the widget's actual grounded
    type -- a combo-eligible shape should show as compatible here too, not
    just at apply time."""
    recommendations = _engine_chart_recommendations(
        [],
        {
            "widgets": [
                {
                    "status": "valid",
                    "sql": "SELECT month, actual_revenue, forecast_revenue FROM revenue",
                    "chartType": "line",
                    "previewData": {
                        "columns": ["month", "actual_revenue", "forecast_revenue"],
                        "rows": [
                            {"month": "2026-01", "actual_revenue": 100000, "forecast_revenue": 98000},
                            {"month": "2026-02", "actual_revenue": 110000, "forecast_revenue": 105000},
                            {"month": "2026-03", "actual_revenue": 108000, "forecast_revenue": 112000},
                            {"month": "2026-04", "actual_revenue": 121000, "forecast_revenue": 118000},
                        ],
                    },
                }
            ]
        },
    )
    assert any(item["chartType"] == "combo" for item in recommendations)


def test_support_status_has_three_explicit_outcomes() -> None:
    source = _source()
    valid = {
        "widgets": [
            {"status": "valid", "sql": "SELECT 1", "chartType": "kpi"}
        ]
    }
    partial = {
        "widgets": [
            {"status": "valid", "sql": "SELECT 1", "chartType": "kpi"},
            {"status": "preview_only", "sql": "SELECT 2", "chartType": "line"},
        ]
    }

    assert _support_status(sources=[], suggestion=None, missing=[]) == "not_supported"
    assert _support_status(sources=[source], suggestion=valid, missing=[]) == "fully_supported"
    assert _support_status(sources=[source], suggestion=partial, missing=[]) == "partially_supported"
    assert _support_status(sources=[source], suggestion=valid, missing=["SLA performance"]) == "partially_supported"


def test_infer_domain_prefers_real_column_matches_over_prompt_words() -> None:
    finance_columns = [
        {"name": "revenue", "type": "decimal"},
        {"name": "expense", "type": "decimal"},
        {"name": "date", "type": "date"},
    ]
    assert _infer_domain("Show monthly revenue and gross margin", finance_columns) == "finance"

    manufacturing_columns = [
        {"name": "oee", "type": "decimal"},
        {"name": "downtime_hours", "type": "decimal"},
        {"name": "units_produced", "type": "integer"},
    ]
    assert _infer_domain("How is my plant performing?", manufacturing_columns) == "manufacturing"

    # Unmatched prompts/columns fall back to generic, not a forced ITSM label.
    assert _infer_domain("Interesting data", [{"name": "foo", "type": "string"}]) == "generic"


def test_infer_domain_ignores_short_junk_columns_that_coincidentally_substring_match() -> None:
    """A real project's ITSM columns plus a couple of unrelated demo CSVs
    with 2-letter column names (e.g. "IP", "PL") must not tip the domain to
    manufacturing just because those short names happen to appear inside
    long compound concept terms ("ip" in "equipmenteffectiveness", "pl" in
    "unplanneddowntime") -- reproduces the project-44 misclassification
    (manufacturing 12 vs itsm 10) traced to _concept_supported's reversed
    substring check having no minimum length on the actual column name."""
    columns = [
        {"name": "IncidentID", "type": "string"},
        {"name": "Priority", "type": "string"},
        {"name": "OpenedDate", "type": "date"},
        {"name": "ResolvedAt", "type": "date"},
        {"name": "AssignmentGroup", "type": "string"},
        {"name": "State", "type": "string"},
        # Unrelated demo CSVs with short, coincidentally-matching columns.
        {"name": "IP", "type": "string"},
        {"name": "PL", "type": "string"},
        {"name": "NS", "type": "string"},
    ]
    assert _infer_domain("IT incident count by priority", columns) == "itsm"


def test_infer_domain_falls_back_to_generic_on_a_genuine_multi_domain_tie() -> None:
    """Reproduces the project-41 misclassification: itsm/finance/sales all
    score equally (2 matched concepts each -> 4) on generic columns like
    Region/Amount/Priority, and the prompt gives no tiebreak either. Picking
    any one of them is an arbitrary guess driven only by _DOMAIN_CONCEPTS's
    dict order (previously always landing on "itsm", the first entry) --
    "generic" is the only answer the data actually supports."""
    columns = [
        {"name": "Region", "type": "string"},
        {"name": "Amount", "type": "decimal"},
        {"name": "Priority", "type": "string"},
    ]
    assert _infer_domain("Show me a dashboard", columns) == "generic"


def test_widget_date_field_detects_a_real_month_axis() -> None:
    """A widget whose label column holds real period-like values (e.g. a
    FORMATDATE'd "Month" column) must get an enabled dateField so the
    dashboard's period control can actually filter it -- query-backed
    widgets have no other hook for that (see DashboardViewer.tsx's
    fetchWidgetData / buildRuntimeWidgetFilters)."""
    widget = {
        "previewData": {
            "columns": ["Month", "RevenueUSD"],
            "rows": [{"Month": f"2026-{m:02d}", "RevenueUSD": 100 + m} for m in range(1, 13)],
        }
    }
    assert _widget_date_field(widget, "Month") == {"enabled": True, "field": "Month"}


def test_widget_date_field_is_none_for_a_non_period_label_column() -> None:
    widget = {
        "previewData": {
            "columns": ["Customer", "RevenueUSD"],
            "rows": [{"Customer": c, "RevenueUSD": 100} for c in ["Acme", "Globex", "Initech"]],
        }
    }
    assert _widget_date_field(widget, "Customer") is None


def test_widget_date_field_is_none_without_preview_data() -> None:
    assert _widget_date_field({}, "Month") is None
    assert _widget_date_field({"previewData": {"columns": [], "rows": []}}, "Month") is None


def _combo_widget(title: str) -> dict:
    return {
        "title": title,
        "status": "valid",
        "sql": "SELECT 1",
        "chartType": "bar_line",
        "labelColumn": "Month",
        "valueColumn": "RevenueUSD",
        "previewData": {
            "columns": ["Month", "RevenueUSD", "BacklogUSD"],
            "rows": [
                {"Month": f"2026-{m:02d}", "RevenueUSD": 100 + m, "BacklogUSD": 50 + m}
                for m in range(1, 13)
            ],
        },
    }


def _dimension_widget(title: str, *, with_dimension: bool, kpi: bool = False) -> dict:
    """A widget whose preview does (or doesn't) carry a shared categorical
    "business_unit" column, for _discover_primary_dimensions tests."""
    columns = ["business_unit", "revenue"] if with_dimension else ["revenue"]
    rows = (
        [{"business_unit": unit, "revenue": 100 + i} for i, unit in enumerate(["East", "West", "Central"])]
        if with_dimension
        else [{"revenue": 4200}]
    )
    return {
        "title": title,
        "status": "valid",
        "sql": f'SELECT * FROM "revenue_by_unit" -- {title}',
        "chartType": "kpi" if kpi else "bar",
        "labelColumn": "business_unit" if with_dimension else None,
        "valueColumn": "revenue",
        "previewData": {"columns": columns, "rows": rows},
    }


def test_chart_overrides_match_by_title_and_force_the_chart_type() -> None:
    suggestion = {"widgets": [_combo_widget("Monthly Revenue vs Backlog")]}
    _apply_chart_overrides(
        suggestion,
        [ChartOverride(label="Monthly Revenue vs Backlog", chart_type="line", unit="thousands")],
    )
    widget = suggestion["widgets"][0]
    assert widget["chartType"] == "line"
    assert widget["_chartTypeForced"] is True
    assert widget["_valueScale"] == "thousands"

    chart_type, _label, _value, _value2 = _grounded_chart_selection(widget)
    assert chart_type == "line"


def test_chart_overrides_left_at_defaults_are_a_no_op() -> None:
    suggestion = {"widgets": [_combo_widget("Monthly Revenue vs Backlog")]}
    original = dict(suggestion["widgets"][0])
    _apply_chart_overrides(
        suggestion, [ChartOverride(label="Monthly Revenue vs Backlog")],
    )
    assert suggestion["widgets"][0] == original


def test_chart_overrides_ignore_a_request_with_no_matching_widget_title() -> None:
    suggestion = {"widgets": [_combo_widget("Monthly Revenue vs Backlog")]}
    _apply_chart_overrides(
        suggestion, [ChartOverride(label="Headcount by Department", chart_type="bar")],
    )
    assert "_chartTypeForced" not in suggestion["widgets"][0]


def test_chart_overrides_match_each_request_to_a_distinct_widget() -> None:
    """Two overrides must not both claim the same best-scoring widget."""
    suggestion = {
        "widgets": [
            _combo_widget("Monthly Revenue vs Backlog"),
            _combo_widget("Monthly Revenue Trend"),
        ]
    }
    _apply_chart_overrides(
        suggestion,
        [
            ChartOverride(label="Monthly Revenue vs Backlog", chart_type="line"),
            ChartOverride(label="Monthly Revenue Trend", chart_type="area"),
        ],
    )
    types = {w["title"]: w["chartType"] for w in suggestion["widgets"]}
    assert types == {"Monthly Revenue vs Backlog": "line", "Monthly Revenue Trend": "area"}


def test_concept_supported_still_matches_genuine_short_abbreviations() -> None:
    """The length floor targets uncurated column names, not the curated
    concept terms -- a real 3-letter abbreviation like "sla" must still
    match a longer concept term like "slamet"."""
    assert _concept_supported(("slamet", "slabreached"), {"sla"})
    assert not _concept_supported(("equipmenteffectiveness",), {"ip"})
    assert not _concept_supported(("unplanneddowntime",), {"pl"})


def test_missing_concepts_respects_inferred_domain() -> None:
    finance_columns = [
        {"name": "revenue", "type": "decimal"},
        {"name": "date", "type": "date"},
    ]
    missing = _missing_concepts(
        "Show revenue, expense, and gross margin",
        finance_columns,
        "finance",
    )
    assert "revenue" not in missing
    assert "expense" in missing
    assert "gross margin" in missing


async def test_chart_candidates_reuses_the_shared_ranking_engine(
    client, service_headers
) -> None:
    """The dashboard widget "Chart options" picker must rank the same way
    Business Insight cards do -- this endpoint is a thin wrapper over
    ask_pipeline.resolve_presentation, not a separate heuristic."""
    _tenant, project, headers = await _tenant_project(client, service_headers)

    r = await client.post(
        "/api/ai/actions/dashboard-designer/chart-candidates",
        json={
            "project_id": project["id"],
            "columns": ["month", "revenue"],
            "rows": [
                {"month": "2026-01", "revenue": 100000},
                {"month": "2026-02", "revenue": 120000},
                {"month": "2026-03", "revenue": 115000},
            ],
        },
        headers=headers,
    )

    assert r.status_code == 200
    body = r.json()
    assert "chart" in body
    assert body["chartCandidates"], "a time-series shape must rank at least one chart"
    chart_types = {c["decision"]["chartType"] for c in body["chartCandidates"]}
    assert "line" in chart_types or "bar" in chart_types


async def test_chart_candidates_requires_project_access(
    client, service_headers
) -> None:
    _tenant, _project, headers = await _tenant_project(client, service_headers, "dd-cc-access")
    other_tenant, other_project, _other_headers = await _tenant_project(
        client, service_headers, "dd-cc-other"
    )

    r = await client.post(
        "/api/ai/actions/dashboard-designer/chart-candidates",
        json={
            "project_id": other_project["id"],
            "columns": ["x"],
            "rows": [{"x": 1}],
        },
        headers=headers,
    )
    assert r.status_code in (403, 404)


def test_operational_sections_match_the_itsm_story_and_bottom_right_layout() -> None:
    widgets = _operational_widgets(
        "Show sales health",
        {
            "businessPurpose": "Monitor delivery and forecast alignment.",
            "knowledgeGraphContext": {
                "risks": ["Backlog is rising"],
                "opportunities": ["Rebalance the highest-volume region"],
            },
            "widgets": [{"businessQuestion": "Which region drives the backlog?"}],
        },
    )
    brief, improvements = widgets
    assert [item["label"] for item in brief["items"]] == [
        "Backing risk",
        "Primary driver",
        "Recommended action",
    ]
    assert improvements["layout"] == {
        "position": 1,
        "width": "standard",
        "gridX": 9,
        "gridY": 5,
        "gridW": 3,
        "gridH": 3,
    }


def test_ai_layout_caps_horizontal_rankings_at_half_width() -> None:
    configs = _apply_operational_layout(
        [
            {"id": "revenue", "type": "kpi"},
            {"id": "backlog", "type": "kpi"},
            {
                "id": "ranking",
                "type": "bar",
                "chartSubtype": "horizontal_bar",
                "visualizationOptions": {"barLayout": "horizontal"},
            },
        ]
    )
    ranking = next(item for item in configs if item["id"] == "ranking")
    assert ranking["gridW"] <= 6
    assert _requested_axis_scale({"valueFormat": "Thousands"}) == "thousands"


async def test_widget_configs_carry_the_requested_currency_symbol(monkeypatch) -> None:
    """Every AI-designer widget's visualizationOptions must carry the
    dashboard's selected currencySymbol so charts and KPI cards render in
    that currency -- default "USD" maps to "$", "EUR" maps to "€"."""
    import app.services.dashboard_widget as dashboard_widget
    from app.routes.ai_proxy_dashboard_designer import _widget_configs

    class _FakeQuery:
        id = 1

    async def fake_find_or_create(*args, **kwargs):
        return _FakeQuery()

    monkeypatch.setattr(dashboard_widget, "find_or_create_saved_query", fake_find_or_create)

    class _FakeContext:
        tenant_id = 1
        user_id = 1

    class _FakeSession:
        async def scalars(self, *args, **kwargs):
            return []  # no allowed_tables -- irrelevant to currencySymbol

    suggestion = {"widgets": [_combo_widget("Monthly Revenue vs Backlog")]}

    default_configs = await _widget_configs(
        session=_FakeSession(), context=_FakeContext(), project_id=1, suggestion=suggestion, start_index=0,
    )
    assert default_configs[0]["visualizationOptions"]["currencySymbol"] == "$"

    eur_configs = await _widget_configs(
        session=_FakeSession(), context=_FakeContext(), project_id=1, suggestion=suggestion,
        start_index=0, currency="EUR",
    )
    assert eur_configs[0]["visualizationOptions"]["currencySymbol"] == "€"


def test_discover_primary_dimensions_flags_a_kpi_missing_the_shared_field() -> None:
    suggestion = {
        "widgets": [
            _dimension_widget("Revenue by Unit", with_dimension=True),
            _dimension_widget("Backlog by Unit", with_dimension=True),
            _dimension_widget("Total Revenue", with_dimension=False, kpi=True),
        ]
    }
    candidates = _discover_primary_dimensions(suggestion)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["field"] == "business_unit"
    assert candidate["label"] == "Business Unit"
    assert candidate["fullCoverage"] is False
    assert candidate["compatibleCount"] == 2
    assert candidate["totalCount"] == 3
    assert candidate["incompatibleWidgets"] == [{"title": "Total Revenue"}]
    assert set(candidate["compatibleWidgets"]) == {"Revenue by Unit", "Backlog by Unit"}


def test_discover_primary_dimensions_reaches_full_coverage_once_the_kpi_is_removed() -> None:
    suggestion = {
        "widgets": [
            _dimension_widget("Revenue by Unit", with_dimension=True),
            _dimension_widget("Backlog by Unit", with_dimension=True),
        ]
    }
    candidates = _discover_primary_dimensions(suggestion)
    assert len(candidates) == 1
    assert candidates[0]["fullCoverage"] is True
    assert candidates[0]["incompatibleWidgets"] == []


def test_discover_primary_dimensions_requires_the_field_in_at_least_two_widgets() -> None:
    suggestion = {"widgets": [_dimension_widget("Revenue by Unit", with_dimension=True)]}
    assert _discover_primary_dimensions(suggestion) == []


def test_discover_primary_dimensions_finds_nothing_without_a_shared_categorical_field() -> None:
    suggestion = {
        "widgets": [
            _dimension_widget("Total Revenue", with_dimension=False, kpi=True),
            _dimension_widget("Total Backlog", with_dimension=False, kpi=True),
        ]
    }
    assert _discover_primary_dimensions(suggestion) == []


async def test_apply_primary_dimension_selection_rejects_a_still_partial_candidate() -> None:
    """The server must recompute coverage against the FINAL widget list --
    trusting a client's stale review-step coverage would let a partial
    dimension get silently applied instead of rejected with 409."""
    from fastapi import HTTPException

    suggestion = {
        "widgets": [
            _dimension_widget("Revenue by Unit", with_dimension=True),
            _dimension_widget("Backlog by Unit", with_dimension=True),
            _dimension_widget("Total Revenue", with_dimension=False, kpi=True),
        ]
    }

    class _FakeContext:
        tenant_id = 1
        user_id = 1

    with pytest.raises(HTTPException) as exc_info:
        await _apply_primary_dimension_selection(
            session=None,  # never reached -- rejected before any DB access
            context=_FakeContext(),
            project_id=1,
            dashboard_id=1,
            suggestion=suggestion,
            configs=[],
            selection=PrimaryDimensionSelection(field="business_unit", label="Business Unit"),
            default_period="1_year",
        )
    assert exc_info.value.status_code == 409


async def test_apply_primary_dimension_selection_persists_and_reuses_the_dimension(
    client, service_headers, db_session,
) -> None:
    """A full-coverage selection must be persisted across the three new
    tables, reused (not duplicated) on a second dashboard in the same
    project, and produce dimension_parameters pointing at a real
    distinct-values query -- the same valueSource: "query" contract
    DashboardViewer.tsx already hydrates for a manually-picked dimension.

    find_or_create_saved_query does only DB work (no Teiid/AI-server call),
    so it runs for real here rather than being mocked -- a mock that returns
    a query id with no backing row would silently hide whether
    _dimension_parameters' own SavedQuery lookup actually succeeds.
    """
    from sqlalchemy import select

    from app.models.dashboard import Dashboard
    from app.models.dashboard_primary_dimension import (
        DashboardPrimaryDimension,
        DashboardPrimaryDimensionAssignment,
        DashboardPrimaryDimensionBinding,
    )

    _tenant, project, _headers = await _tenant_project(client, service_headers, "dd-primary-dim")

    class _Context:
        tenant_id = _tenant["id"]
        user_id = 1

    dashboard = Dashboard(
        project_id=project["id"],
        tenant_id=_Context.tenant_id,
        owner_id=None,
        name="Revenue Dashboard",
        status="published",
        config={},
        ai_generated=True,
    )
    db_session.add(dashboard)
    await db_session.flush()

    suggestion = {
        "widgets": [
            _dimension_widget("Revenue by Unit", with_dimension=True),
            _dimension_widget("Backlog by Unit", with_dimension=True),
        ]
    }
    configs = [
        {"id": "w1", "title": "Revenue by Unit"},
        {"id": "w2", "title": "Backlog by Unit"},
    ]

    parameters = await _apply_primary_dimension_selection(
        db_session,
        context=_Context(),
        project_id=project["id"],
        dashboard_id=dashboard.id,
        suggestion=suggestion,
        configs=configs,
        selection=PrimaryDimensionSelection(field="business_unit", label="Business Unit"),
        default_period="1_year",
    )
    await db_session.flush()

    assert parameters["valueSource"] == "query"
    assert parameters["dimensionLabel"] == "Business Unit"

    dimensions = list(await db_session.scalars(select(DashboardPrimaryDimension)))
    assert len(dimensions) == 1
    assert dimensions[0].field == "business_unit"
    assert dimensions[0].source_view == "revenue_by_unit"

    assignments = list(await db_session.scalars(select(DashboardPrimaryDimensionAssignment)))
    assert len(assignments) == 1
    assert assignments[0].dashboard_id == dashboard.id
    assert assignments[0].is_active is True

    bindings = list(await db_session.scalars(select(DashboardPrimaryDimensionBinding)))
    assert {b.widget_id for b in bindings} == {"w1", "w2"}

    # A second dashboard discovering the SAME field on the SAME source view
    # must reuse the existing DashboardPrimaryDimension row, not duplicate it.
    dashboard_2 = Dashboard(
        project_id=project["id"],
        tenant_id=_Context.tenant_id,
        owner_id=None,
        name="Backlog Dashboard",
        status="published",
        config={},
        ai_generated=True,
    )
    db_session.add(dashboard_2)
    await db_session.flush()

    await _apply_primary_dimension_selection(
        db_session,
        context=_Context(),
        project_id=project["id"],
        dashboard_id=dashboard_2.id,
        suggestion=suggestion,
        configs=configs,
        selection=PrimaryDimensionSelection(field="business_unit", label="Unit"),
        default_period="1_year",
    )
    await db_session.flush()

    dimensions_after = list(await db_session.scalars(select(DashboardPrimaryDimension)))
    assert len(dimensions_after) == 1  # reused, not duplicated
    assignments_after = list(await db_session.scalars(select(DashboardPrimaryDimensionAssignment)))
    assert len(assignments_after) == 2  # one per dashboard


async def test_apply_primary_dimension_selection_keeps_exactly_one_assignment_active(
    client, service_headers, db_session,
) -> None:
    """A dashboard with two full-coverage dimension candidates -- the header
    switch icon's premise -- must end up with exactly one active
    assignment: the first one applied, when later selections pass
    make_active=False (as the apply endpoint does for every entry in
    primary_dimensions after the first)."""
    from sqlalchemy import select

    from app.models.dashboard import Dashboard
    from app.models.dashboard_primary_dimension import DashboardPrimaryDimensionAssignment

    _tenant, project, _headers = await _tenant_project(client, service_headers, "dd-primary-dim-2")

    class _Context:
        tenant_id = _tenant["id"]
        user_id = 1

    dashboard = Dashboard(
        project_id=project["id"], tenant_id=_Context.tenant_id, owner_id=None,
        name="Two Dimensions", status="published", config={}, ai_generated=True,
    )
    db_session.add(dashboard)
    await db_session.flush()

    def _widget(title: str) -> dict:
        # Both dimensions are present on every widget, so both independently
        # reach full coverage -- the scenario the header switch icon exists
        # for (pick which of two equally-valid dimensions is active).
        return {
            "title": title,
            "status": "valid",
            "sql": f'SELECT * FROM "revenue_by_unit" -- {title}',
            "chartType": "bar",
            "previewData": {
                "columns": ["business_unit", "customer_segment", "revenue"],
                "rows": [
                    {"business_unit": bu, "customer_segment": cs, "revenue": 100 + i}
                    for i, (bu, cs) in enumerate(zip(["A", "B", "C"], ["X", "Y", "Z"], strict=True))
                ],
            },
        }

    suggestion = {"widgets": [_widget("Revenue by Unit"), _widget("Backlog by Unit")]}
    configs = [
        {"id": "w1", "title": "Revenue by Unit"},
        {"id": "w2", "title": "Backlog by Unit"},
    ]

    for index, selection in enumerate([
        PrimaryDimensionSelection(field="business_unit", label="Business Unit"),
        PrimaryDimensionSelection(field="customer_segment", label="Customer Segment"),
    ]):
        await _apply_primary_dimension_selection(
            db_session,
            context=_Context(),
            project_id=project["id"],
            dashboard_id=dashboard.id,
            suggestion=suggestion,
            configs=configs,
            selection=selection,
            default_period="1_year",
            make_active=(index == 0),
        )
    await db_session.flush()

    assignments = list(await db_session.scalars(select(DashboardPrimaryDimensionAssignment)))
    assert len(assignments) == 2
    active = [a for a in assignments if a.is_active]
    assert len(active) == 1
    assert active[0].label == "Business Unit"


async def test_primary_dimension_switch_endpoints_activate_and_isolate_by_tenant(
    client, service_headers, db_session,
) -> None:
    """The header switch icon's backend: listing a dashboard's assigned
    dimensions and activating one reloads dimension_parameters at real
    distinct values -- and a user from a different tenant can neither see
    nor activate another tenant's dimension assignments (production
    acceptance check 8)."""
    from app.models.dashboard import Dashboard

    tenant, project, headers = await _tenant_project(client, service_headers, "dd-switch")

    class _Context:
        tenant_id = tenant["id"]
        user_id = 1

    dashboard = Dashboard(
        project_id=project["id"],
        tenant_id=_Context.tenant_id,
        owner_id=None,
        name="Two Dimensions",
        status="published",
        config={
            "presentation": "operational_insight",
            "dashboardTemplate": {"parameters": {"defaultPeriod": "1_year"}},
        },
        ai_generated=True,
    )
    db_session.add(dashboard)
    await db_session.flush()

    def _widget(title: str) -> dict:
        return {
            "title": title,
            "status": "valid",
            "sql": f'SELECT * FROM "revenue_by_unit" -- {title}',
            "chartType": "bar",
            "previewData": {
                "columns": ["business_unit", "customer_segment", "revenue"],
                "rows": [
                    {"business_unit": bu, "customer_segment": cs, "revenue": 100 + i}
                    for i, (bu, cs) in enumerate(zip(["A", "B", "C"], ["X", "Y", "Z"], strict=True))
                ],
            },
        }

    suggestion = {"widgets": [_widget("Revenue by Unit"), _widget("Backlog by Unit")]}
    configs = [
        {"id": "w1", "title": "Revenue by Unit"},
        {"id": "w2", "title": "Backlog by Unit"},
    ]

    for index, selection in enumerate([
        PrimaryDimensionSelection(field="business_unit", label="Business Unit"),
        PrimaryDimensionSelection(field="customer_segment", label="Customer Segment"),
    ]):
        await _apply_primary_dimension_selection(
            db_session,
            context=_Context(),
            project_id=project["id"],
            dashboard_id=dashboard.id,
            suggestion=suggestion,
            configs=configs,
            selection=selection,
            default_period="1_year",
            make_active=(index == 0),
        )
    await db_session.commit()

    r = await client.get(
        f"/api/projects/{project['id']}/dashboards/{dashboard.id}/primary-dimensions",
        headers=headers,
    )
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    active_row = next(row for row in rows if row["is_active"])
    inactive_row = next(row for row in rows if not row["is_active"])
    assert active_row["label"] == "Business Unit"
    assert inactive_row["label"] == "Customer Segment"

    r = await client.post(
        f"/api/projects/{project['id']}/dashboards/{dashboard.id}"
        f"/primary-dimensions/{inactive_row['id']}/activate",
        headers=headers,
    )
    assert r.status_code == 200
    updated = r.json()
    parameters = updated["config"]["dashboardTemplate"]["parameters"]
    assert parameters["dimensionLabel"] == "Customer Segment"
    assert parameters["valueSource"] == "query"

    r = await client.get(
        f"/api/projects/{project['id']}/dashboards/{dashboard.id}/primary-dimensions",
        headers=headers,
    )
    rows_after = r.json()
    assert next(row for row in rows_after if row["id"] == inactive_row["id"])["is_active"] is True
    assert next(row for row in rows_after if row["id"] == active_row["id"])["is_active"] is False

    # A user from a DIFFERENT tenant must not see or reuse these dimension
    # records: the project lookup is tenant-scoped, so both endpoints 404
    # rather than leaking cross-tenant data.
    _other_tenant, _other_project, other_headers = await _tenant_project(
        client, service_headers, "dd-switch-other-tenant",
    )

    r = await client.get(
        f"/api/projects/{project['id']}/dashboards/{dashboard.id}/primary-dimensions",
        headers=other_headers,
    )
    assert r.status_code in (403, 404)

    r = await client.post(
        f"/api/projects/{project['id']}/dashboards/{dashboard.id}"
        f"/primary-dimensions/{active_row['id']}/activate",
        headers=other_headers,
    )
    assert r.status_code in (403, 404)
