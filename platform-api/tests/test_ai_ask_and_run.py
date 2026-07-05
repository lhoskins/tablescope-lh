"""Tests for the AI Question modal endpoints (ask-and-run + query preview).

These endpoints generate SQL for a question, execute it against the project's
VDB, and return the rows so the inline modal can render results. They must never
raise on a generation/execution failure — instead they return a structured
``status`` so the modal shows an inline error (and reveals the SQL) rather than
navigating the user away.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.auth.jwt import create_access_token
from app.routes import ai_proxy
from app.routes.ai_proxy import _apply_row_limit, _suggest_visualization
from app.services.supabase_auth_service import SupabaseAuthService, SupabaseUser


class _FakeSupabase(SupabaseAuthService):
    def __init__(self) -> None:
        pass

    async def create_or_invite_user(
        self, email, *, first_name=None, last_name=None, redirect_to=None
    ) -> SupabaseUser:
        return SupabaseUser(
            id=f"supa-{email}", email=email, created=True, action_link="x"
        )


class _FakeEmail:
    async def send_transactional_email(self, **kwargs) -> bool:
        return True


@pytest.fixture(autouse=True)
def _mock_supabase(monkeypatch):
    import app.routes.tenants as tenants_module

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)


def _editor_headers(tenant_id: int, user_id: int) -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role="editor"
    )
    return {"Authorization": f"Bearer {token}"}


async def _setup(client, service_headers, slug: str):
    r = await client.post(
        "/api/tenants",
        json={"slug": slug, "name": f"{slug} tenant"},
        headers=service_headers,
    )
    assert r.status_code == 201
    tenant = r.json()
    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": f"{slug}@test.com",
            "display_name": "Ask User",
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
        json={"name": "Ask Project", "description": "x", "is_shared": False},
        headers=headers,
    )
    assert r.status_code == 201
    return tenant, user, r.json(), headers


# ── Pure helpers ──────────────────────────────────────────────────────────

def test_apply_row_limit_appends_when_missing():
    assert _apply_row_limit("SELECT * FROM t", 200) == "SELECT * FROM t LIMIT 200"
    assert _apply_row_limit("SELECT * FROM t;", 50) == "SELECT * FROM t LIMIT 50"


def test_apply_row_limit_preserves_existing_limit():
    assert _apply_row_limit("SELECT * FROM t LIMIT 10", 200) == (
        "SELECT * FROM t LIMIT 10"
    )


def test_suggest_visualization_kpi_for_single_numeric_cell():
    viz = _suggest_visualization(["total"], [{"total": 42}])
    assert viz["type"] == "kpi"
    assert viz["metricField"] == "total"


def test_suggest_visualization_bar_for_category_and_numeric():
    viz = _suggest_visualization(
        ["supplier", "defects"],
        [{"supplier": "A", "defects": 3}, {"supplier": "B", "defects": 5}],
    )
    assert viz["type"] == "bar"
    assert viz["xField"] == "supplier"
    assert viz["yField"] == "defects"


def test_suggest_visualization_line_for_time_and_numeric():
    viz = _suggest_visualization(
        ["month", "revenue"],
        [{"month": "2024-01", "revenue": 10}, {"month": "2024-02", "revenue": 20}],
    )
    assert viz["type"] == "line"
    assert viz["xField"] == "month"


def test_suggest_visualization_table_when_no_rows():
    assert _suggest_visualization(["a"], [])["type"] == "table"


# ── Endpoint behaviour ────────────────────────────────────────────────────

async def test_ask_and_run_success(client, service_headers, monkeypatch):
    _, _, project, headers = await _setup(client, service_headers, "askok")

    async def fake_generate(session, context, project_id, question):
        return {"sql": "SELECT supplier, defects FROM q", "explanation": "why"}

    async def fake_execute(session, context, project_id, sql):
        return {
            "columns": ["supplier", "defects"],
            "rows": [{"supplier": "A", "defects": 3}],
        }

    monkeypatch.setattr(ai_proxy, "_generate_sql_for_question", fake_generate)
    monkeypatch.setattr(ai_proxy, "_execute_project_sql", fake_execute)

    r = await client.post(
        "/api/ai/actions/ask-and-run",
        json={"project_id": project["id"], "question": "defects by supplier?"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success"
    assert body["sql"] == "SELECT supplier, defects FROM q"
    assert body["rows"] == [{"supplier": "A", "defects": 3}]
    assert body["suggestedVisualization"]["type"] == "bar"


async def test_ask_and_run_generation_error_is_structured(
    client, service_headers, monkeypatch
):
    _, _, project, headers = await _setup(client, service_headers, "askgen")

    async def fake_generate(session, context, project_id, question):
        raise HTTPException(status_code=503, detail="AI server unreachable")

    monkeypatch.setattr(ai_proxy, "_generate_sql_for_question", fake_generate)

    r = await client.post(
        "/api/ai/actions/ask-and-run",
        json={"project_id": project["id"], "question": "x?"},
        headers=headers,
    )
    # 200 with a structured error — the modal must not navigate away.
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "generation_error"
    assert "unreachable" in body["error"]
    assert body["sql"] == ""


async def test_ask_and_run_execution_error_reveals_sql(
    client, service_headers, monkeypatch
):
    _, _, project, headers = await _setup(client, service_headers, "askexec")

    async def fake_generate(session, context, project_id, question):
        return {"sql": "SELECT * FROM broken", "explanation": ""}

    async def fake_execute(session, context, project_id, sql):
        raise HTTPException(status_code=502, detail="Query failed: bad column")

    monkeypatch.setattr(ai_proxy, "_generate_sql_for_question", fake_generate)
    monkeypatch.setattr(ai_proxy, "_execute_project_sql", fake_execute)

    r = await client.post(
        "/api/ai/actions/ask-and-run",
        json={"project_id": project["id"], "question": "x?"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "execution_error"
    assert body["sql"] == "SELECT * FROM broken"
    assert "bad column" in body["error"]


async def test_ask_and_run_rejects_other_tenant(client, service_headers):
    _, _, project, _ = await _setup(client, service_headers, "aska")
    _, _, _, other_headers = await _setup(client, service_headers, "askb")

    r = await client.post(
        "/api/ai/actions/ask-and-run",
        json={"project_id": project["id"], "question": "x?"},
        headers=other_headers,
    )
    assert r.status_code == 404


async def test_generate_query_preview_success(
    client, service_headers, monkeypatch
):
    _, _, project, headers = await _setup(client, service_headers, "prev")

    async def fake_generate(session, context, project_id, question):
        return {"sql": "SELECT month, revenue FROM q", "explanation": "e"}

    async def fake_execute(session, context, project_id, sql):
        return {
            "columns": ["month", "revenue"],
            "rows": [{"month": "2024-01", "revenue": 10}],
        }

    monkeypatch.setattr(ai_proxy, "_generate_sql_for_question", fake_generate)
    monkeypatch.setattr(ai_proxy, "_execute_project_sql", fake_execute)

    r = await client.post(
        "/api/ai/actions/generate-query-preview",
        json={
            "project_id": project["id"],
            "question": "monthly revenue",
            "title": "Monthly Revenue",
        },
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success"
    assert body["title"] == "Monthly Revenue"
    assert body["suggestedVisualization"]["type"] == "line"
    assert body["rows"][0]["revenue"] == 10
