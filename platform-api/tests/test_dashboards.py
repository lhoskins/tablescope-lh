"""Dashboard CRUD tests via the HTTP API."""

from __future__ import annotations

import pytest

from app.auth.jwt import create_access_token
from app.services.supabase_auth_service import SupabaseAuthService, SupabaseUser


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
    async def send_transactional_email(self, *, to, template, variables, subject=None, reply_to=None) -> bool:
        return True


@pytest.fixture(autouse=True)
def _mock_supabase(monkeypatch):
    import app.routes.tenants_users as tenants_module

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)


def _editor_headers(tenant_id: int = 1, user_id: int = 1) -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role="editor"
    )
    return {"Authorization": f"Bearer {token}"}


async def _setup_tenant_and_project(client, service_headers):
    r = await client.post(
        "/api/tenants",
        json={"slug": "dash-tenant", "name": "Dashboard Tenant"},
        headers=service_headers,
    )
    assert r.status_code == 201
    tenant = r.json()

    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": "dash@test.com",
            "display_name": "Dash User",
            "role": "editor",
            "external_id": "ext-dash",
        },
        headers=service_headers,
    )
    assert r.status_code == 201
    user = r.json()

    headers = _editor_headers(tenant_id=tenant["id"], user_id=user["id"])
    r = await client.post(
        "/api/projects",
        json={"name": "Sales Project", "description": "test", "is_shared": False},
        headers=headers,
    )
    assert r.status_code == 201
    project = r.json()
    return tenant, user, project, headers


async def test_dashboard_crud_lifecycle(client, service_headers) -> None:
    _tenant, _user, project, headers = await _setup_tenant_and_project(
        client, service_headers
    )
    pid = project["id"]

    # List empty
    r = await client.get(f"/api/projects/{pid}/dashboards", headers=headers)
    assert r.status_code == 200
    assert r.json() == []

    # Create
    config = {
        "widgets": [
            {
                "id": "w1",
                "type": "line",
                "title": "Revenue Trend",
                "dataSource": {"kind": "query", "queryId": 1},
                "xKey": "month",
                "yKey": "revenue",
                "colSpan": 6,
                "position": 0,
            }
        ]
    }
    r = await client.post(
        f"/api/projects/{pid}/dashboards",
        json={"name": "Q1 Overview", "description": "test dash", "config": config},
        headers=headers,
    )
    assert r.status_code == 201
    dash = r.json()
    assert dash["name"] == "Q1 Overview"
    assert dash["status"] == "draft"
    assert dash["config"]["widgets"][0]["type"] == "line"
    dash_id = dash["id"]

    # Get
    r = await client.get(
        f"/api/projects/{pid}/dashboards/{dash_id}", headers=headers
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Q1 Overview"

    # Update
    r = await client.put(
        f"/api/projects/{pid}/dashboards/{dash_id}",
        json={"name": "Q1 Revenue Dashboard", "status": "live"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Q1 Revenue Dashboard"
    assert r.json()["status"] == "live"

    # List
    r = await client.get(f"/api/projects/{pid}/dashboards", headers=headers)
    assert r.status_code == 200
    assert len(r.json()) == 1

    # Delete
    r = await client.delete(
        f"/api/projects/{pid}/dashboards/{dash_id}", headers=headers
    )
    assert r.status_code == 204

    # Verify gone
    r = await client.get(f"/api/projects/{pid}/dashboards", headers=headers)
    assert r.status_code == 200
    assert r.json() == []


async def test_dashboard_workspace_metadata(client, service_headers) -> None:
    """ai_generated / view_count surface on dashboards for the workspace UI."""
    _, _, project, headers = await _setup_tenant_and_project(
        client, service_headers
    )
    pid = project["id"]

    # Default create: ai_generated False, view_count 0.
    r = await client.post(
        f"/api/projects/{pid}/dashboards",
        json={"name": "Manual Board"},
        headers=headers,
    )
    assert r.status_code == 201
    manual = r.json()
    assert manual["ai_generated"] is False
    assert manual["view_count"] == 0

    # AI-generated create round-trips.
    r = await client.post(
        f"/api/projects/{pid}/dashboards",
        json={"name": "AI Board", "ai_generated": True, "status": "published"},
        headers=headers,
    )
    assert r.status_code == 201
    ai = r.json()
    assert ai["ai_generated"] is True

    # Update can flip ai_generated.
    r = await client.put(
        f"/api/projects/{pid}/dashboards/{manual['id']}",
        json={"ai_generated": True},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["ai_generated"] is True


async def test_suggest_dashboards_returns_min_three(
    client, service_headers, monkeypatch
) -> None:
    """The Dashboard-page AI flow returns >= 3 shaped suggestions (no save)."""
    _, _, project, headers = await _setup_tenant_and_project(
        client, service_headers
    )
    pid = project["id"]

    async def _fake_forward(path: str, payload: dict):
        assert path == "/ai/dashboard/suggest-multi"
        assert payload["desired_count"] >= 3
        return {
            "model_used": "test-model",
            "suggestions": [
                {
                    "title": f"Dashboard {i}",
                    "description": f"desc {i}",
                    "business_purpose": "drive a decision",
                    "audience": "executive",
                    "widgets": [
                        {
                            "title": "Widget",
                            "chart_type": "bar",
                            "business_question": "q?",
                        }
                    ],
                    "kpis": ["defect_rate"],
                    # An invalid / hallucinated table must be dropped.
                    "data_sources": ["NW_Sales_CSV", "Made_Up_Table"],
                    "confidence": 0.8,
                    "quality_score": 90,
                }
                for i in range(3)
            ],
        }

    import app.routes.ai_proxy as ai_proxy

    monkeypatch.setattr(ai_proxy, "_forward_to_ai", _fake_forward)

    r = await client.post(
        "/api/ai/actions/suggest-dashboards",
        json={"project_id": pid, "prompt": "supplier quality", "desired_count": 3},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action"] == "suggest_dashboards"
    suggestions = body["suggestions"]
    assert len(suggestions) >= 3
    first = suggestions[0]
    assert first["id"] == "suggestion-1"
    assert first["title"] == "Dashboard 0"
    assert first["widgets"][0]["chartType"] == "bar"
    # Hallucinated table dropped; project has no datasources here so none survive.
    assert "Made_Up_Table" not in first["dataSources"]
    assert first["qualityScore"] == 90


async def test_save_dashboard_suggestion_persists_with_url(
    client, service_headers, monkeypatch
) -> None:
    """Saving a previewed suggestion runs the strict pipeline and returns a URL."""
    _, _, project, headers = await _setup_tenant_and_project(
        client, service_headers
    )
    pid = project["id"]

    async def _fake_forward(path: str, payload: dict):
        # The save stage drives the single strict generate-and-save pipeline.
        assert path == "/ai/dashboard/suggest"
        return {
            "model_used": "test-model",
            "suggestions": [
                {
                    "title": "Supplier Quality",
                    "widgets": [
                        {
                            "title": "Defects by supplier",
                            "type": "bar",
                            "sql": "SELECT supplier, defects FROM q",
                            "priority_score": 0.9,
                        },
                        {
                            "title": "On-time delivery",
                            "type": "bar",
                            "sql": "SELECT supplier, ontime FROM q2",
                            "priority_score": 0.8,
                        },
                    ],
                }
            ],
        }

    import app.routes.ai_proxy as ai_proxy

    monkeypatch.setattr(ai_proxy, "_forward_to_ai", _fake_forward)

    r = await client.post(
        "/api/ai/actions/save-dashboard-suggestion",
        json={
            "project_id": pid,
            "suggestionId": "suggestion-1",
            "suggestion": {
                "title": "Supplier Quality",
                "description": "supplier overview",
                "businessPurpose": "track supplier risk",
                "audience": "executive",
                "widgets": [
                    {"title": "Defects by supplier", "chartType": "bar",
                     "businessQuestion": "which suppliers?"},
                ],
                "kpis": ["defect_rate"],
                "dataSources": [],
            },
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action"] == "save_dashboard_suggestion"
    assert body["suggestion_id"] == "suggestion-1"
    assert body["status"] == "saved"
    dash_id = body["dashboard_id"]
    assert body["dashboard_url"] == f"/projects/{pid}/dashboards/{dash_id}"


async def test_save_dashboard_keeps_widget_that_fails_to_execute(
    client, service_headers, monkeypatch
) -> None:
    """A widget whose validation SQL fails must be kept (flagged), not dropped.

    Previously the save raised "needed 2, got 1" when widget queries failed to
    execute. The dashboard should now save with the widget present and flagged.
    """
    _, _, project, headers = await _setup_tenant_and_project(
        client, service_headers
    )
    pid = project["id"]

    async def _fake_forward(path: str, payload: dict):
        return {
            "model_used": "test-model",
            "suggestions": [
                {
                    "title": "Supplier Quality",
                    "widgets": [
                        {
                            "title": "Top 10 Suppliers by Defect Rate",
                            "type": "bar",
                            "sql": "SELECT supplier, defect_rate FROM q",
                            "priority_score": 0.9,
                        },
                    ],
                }
            ],
        }

    import app.routes.ai_proxy as ai_proxy
    import app.routes.query as query_module
    import app.services.tenant_teiid_resolver as ttr

    class _Endpoint:
        pg_host = "teiid"
        pg_port = 35432

    class _FakeResolver:
        def __init__(self, _session) -> None:
            pass

        async def resolve_for_org(self, _tenant_id):
            return _Endpoint()

    async def _fake_resolve_vdb(*, session, context, project_id):
        return "vdb_db"

    async def _fail_run_sql(**_kwargs):
        raise RuntimeError("teiid says no")

    monkeypatch.setattr(ai_proxy, "_forward_to_ai", _fake_forward)
    monkeypatch.setattr(ttr, "TenantTeiidResolver", _FakeResolver)
    monkeypatch.setattr(query_module, "_resolve_vdb_database", _fake_resolve_vdb)
    monkeypatch.setattr(query_module, "_run_sql", _fail_run_sql)

    r = await client.post(
        "/api/ai/actions/save-dashboard-suggestion",
        json={
            "project_id": pid,
            "suggestionId": "suggestion-1",
            "suggestion": {
                "title": "Supplier Quality",
                "widgets": [
                    {"title": "Top 10 Suppliers by Defect Rate",
                     "chartType": "bar", "businessQuestion": "which suppliers?"},
                ],
                "kpis": [],
                "dataSources": [],
            },
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "saved"
    assert body["widgets_created"] == 1
    flagged = body.get("widgets_flagged", [])
    assert any(f["reason"] == "query failed to execute" for f in flagged)


async def test_save_dashboard_suggestion_requires_editor(
    client, service_headers
) -> None:
    _, _, project, _ = await _setup_tenant_and_project(client, service_headers)
    pid = project["id"]
    viewer = create_access_token(sub="v", tenant_id=1, user_id=999, role="viewer")
    r = await client.post(
        "/api/ai/actions/save-dashboard-suggestion",
        json={"project_id": pid, "suggestion": {"title": "x"}},
        headers={"Authorization": f"Bearer {viewer}"},
    )
    assert r.status_code == 403


async def test_suggest_dashboards_requires_editor(client, service_headers) -> None:
    _, _, project, _ = await _setup_tenant_and_project(client, service_headers)
    pid = project["id"]
    viewer = create_access_token(
        sub="v", tenant_id=1, user_id=999, role="viewer"
    )
    r = await client.post(
        "/api/ai/actions/suggest-dashboards",
        json={"project_id": pid},
        headers={"Authorization": f"Bearer {viewer}"},
    )
    assert r.status_code == 403


async def test_dashboard_not_found(client, service_headers) -> None:
    _, _, project, headers = await _setup_tenant_and_project(client, service_headers)
    pid = project["id"]

    r = await client.get(f"/api/projects/{pid}/dashboards/9999", headers=headers)
    assert r.status_code == 404


async def test_widget_query_rejects_foreign_view(client, service_headers) -> None:
    """A widget querying a view that is not one of the project's datasources
    (e.g. an AI-hallucinated table from another tenant) must be rejected."""
    _, _, project, headers = await _setup_tenant_and_project(client, service_headers)
    pid = project["id"]

    r = await client.post(
        f"/api/projects/{pid}/dashboards/widget-query",
        json={
            "view_name": "NW_Products_CSV",
            "x_column": "category",
            "y_column": "revenue",
            "aggregation": "sum",
        },
        headers=headers,
    )
    assert r.status_code == 403
    assert "not a datasource" in r.json()["detail"]
