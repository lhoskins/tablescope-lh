"""Canonical Business and Project Insight conversation tests."""

from __future__ import annotations

import pytest

from app.auth.jwt import create_access_token
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


@pytest.fixture(autouse=True)
def _fake_ask(monkeypatch):
    async def _fake(*args, **kwargs):
        question = kwargs.get("question", "q")
        return {
            "question": question,
            "sql": 'SELECT "month", "amount" FROM "sales"',
            "columns": ["month", "amount"],
            "rows": [{"month": "2024-01", "amount": 100}],
            "suggestedVisualization": {"type": "bar", "title": question},
            "explanation": "ok",
            "dataSourcesUsed": ["sales"],
            "status": "success",
            "error": None,
        }

    monkeypatch.setattr(
        "app.services.conversational_analytics._ask_and_run_core",
        _fake,
    )


def _headers(tenant_id: int, user_id: int, role: str = "editor") -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role=role
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
            "display_name": "Canonical User",
            "role": "editor",
            "external_id": f"ext-{slug}",
        },
        headers=service_headers,
    )
    assert r.status_code == 201
    user = r.json()
    headers = _headers(tenant["id"], user["id"])

    r = await client.post(
        "/api/projects",
        json={"name": "Canonical Project", "description": "x", "is_shared": False},
        headers=headers,
    )
    assert r.status_code == 201
    project = r.json()
    return tenant, user, project, headers


async def test_business_insights_appends_to_one_conversation(client, service_headers):
    _, _, _, headers = await _setup(client, service_headers, "bi-canonical")

    r1 = await client.post(
        "/api/conversational-analytics/canonical-turns",
        json={
            "surface": "business_insights",
            "message": "first",
            "client_request_id": "req-1",
        },
        headers=headers,
    )
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1["surface"] == "business_insights"
    assert body1["project_id"] is None
    assert body1["conversation_created"] is True
    assert body1["turn"]["sequence"] == 1

    r2 = await client.post(
        "/api/conversational-analytics/canonical-turns",
        json={
            "surface": "business_insights",
            "message": "second",
            "client_request_id": "req-2",
        },
        headers=headers,
    )
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["conversation_id"] == body1["conversation_id"]
    assert body2["conversation_created"] is False
    assert body2["turn"]["sequence"] == 2


async def test_project_insights_appends_to_one_conversation_per_project(client, service_headers):
    _, _, project, headers = await _setup(client, service_headers, "pi-canonical")

    r1 = await client.post(
        "/api/conversational-analytics/canonical-turns",
        json={
            "surface": "project_insights",
            "project_id": project["id"],
            "message": "first",
            "client_request_id": "req-1",
        },
        headers=headers,
    )
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1["project_id"] == project["id"]
    assert body1["conversation_created"] is True

    r2 = await client.post(
        "/api/conversational-analytics/canonical-turns",
        json={
            "surface": "project_insights",
            "project_id": project["id"],
            "message": "second",
            "client_request_id": "req-2",
        },
        headers=headers,
    )
    body2 = r2.json()
    assert body2["conversation_id"] == body1["conversation_id"]
    assert body2["turn"]["sequence"] == 2


async def test_canonical_turns_are_idempotent_by_client_request_id(client, service_headers):
    _, _, _, headers = await _setup(client, service_headers, "bi-idempotent")

    r1 = await client.post(
        "/api/conversational-analytics/canonical-turns",
        json={
            "surface": "business_insights",
            "message": "first",
            "client_request_id": "same-req",
        },
        headers=headers,
    )
    assert r1.status_code == 200
    body1 = r1.json()

    r2 = await client.post(
        "/api/conversational-analytics/canonical-turns",
        json={
            "surface": "business_insights",
            "message": "different",
            "client_request_id": "same-req",
        },
        headers=headers,
    )
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["turn"]["id"] == body1["turn"]["id"]
    assert body2["turn"]["user_message"] == "first"


async def test_manual_ai_assistant_conversations_remain_independent(client, service_headers):
    _, _, _, headers = await _setup(client, service_headers, "manual-create")

    r1 = await client.post(
        "/api/conversational-analytics/conversations",
        json={"initial_message": "first manual"},
        headers=headers,
    )
    assert r1.status_code == 200, r1.text
    c1 = r1.json()

    r2 = await client.post(
        "/api/conversational-analytics/conversations",
        json={"initial_message": "second manual"},
        headers=headers,
    )
    assert r2.status_code == 200, r2.text
    c2 = r2.json()

    assert c1["id"] != c2["id"]
    assert c1["canonical_key"] is None
    assert c2["canonical_key"] is None


async def test_list_conversations_excludes_merged_rows(client, service_headers, db_session):
    _, _, project, headers = await _setup(client, service_headers, "merged-list")

    r = await client.post(
        "/api/conversational-analytics/canonical-turns",
        json={
            "surface": "project_insights",
            "project_id": project["id"],
            "message": "q",
            "client_request_id": "m-1",
        },
        headers=headers,
    )
    assert r.status_code == 200
    canonical_id = r.json()["conversation_id"]

    # Simulate an alias by marking the canonical as merged; list should hide it.
    from app.models import AnalyticsConversation

    conv = await db_session.get(AnalyticsConversation, canonical_id)
    if conv:
        conv.status = "merged"
        await db_session.commit()

    rlist = await client.get(
        "/api/conversational-analytics/conversations",
        headers=headers,
    )
    assert rlist.status_code == 200
    ids = {c["id"] for c in rlist.json()}
    assert canonical_id not in ids
