from __future__ import annotations

import pytest

from app.auth.jwt import create_access_token
from app.models.file_source_meta import FileSourceMeta
from app.routes.ai_proxy_dashboard_designer import (
    ChartOverride,
    _apply_chart_overrides,
    _apply_operational_layout,
    _chart_recommendations,
    _concept_supported,
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
