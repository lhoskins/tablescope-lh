from __future__ import annotations

import pytest

from app.auth.jwt import create_access_token
from app.models.file_source_meta import FileSourceMeta
from app.routes.ai_proxy_dashboard_designer import (
    _chart_recommendations,
    _grounded_chart_selection,
    _infer_domain,
    _missing_concepts,
    _support_status,
    _validated_chart_recommendations,
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

    chart_type, label_column, value_column = _grounded_chart_selection(widget)

    assert chart_type != "kpi"
    assert label_column == "region"
    assert value_column == "incident_count"


def test_grounded_chart_selection_falls_back_without_preview_data() -> None:
    """A widget with no executed preview (e.g. narrative, or the query
    failed) has nothing to ground against -- keep the LLM's raw fields
    rather than guessing from nothing."""
    widget = {"chartType": "line", "labelColumn": "month", "valueColumn": "revenue"}

    assert _grounded_chart_selection(widget) == ("line", "month", "revenue")


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

    chart_type, label_column, _value_column = _grounded_chart_selection(widget)

    assert chart_type == "bar"
    assert label_column == "note"


def test_executed_preview_can_validate_a_chart_when_profile_metadata_is_sparse() -> None:
    recommendations = _validated_chart_recommendations(
        [],
        {
            "widgets": [
                {
                    "status": "valid",
                    "sql": 'SELECT "site", COUNT(*) AS "count" FROM "incidents" GROUP BY "site"',
                    "chartType": "bar",
                }
            ]
        },
    )
    horizontal = next(item for item in recommendations if item["chartType"] == "horizontal_bar")
    assert horizontal["compatible"] is True
    assert "executing" in horizontal["reason"]


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
