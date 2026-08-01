"""Tests for the project recent AI Assistant conversations endpoint."""

from __future__ import annotations

import pytest

from app.auth.jwt import create_access_token
from app.services.conversation_previews import (
    NO_RESULT_PREVIEW,
    question_preview,
    result_preview,
    to_plain_text,
)

pytestmark = pytest.mark.anyio


def _headers(tenant_id: int, user_id: int, role: str = "editor") -> dict:
    token = create_access_token(sub="u", tenant_id=tenant_id, user_id=user_id, role=role)
    return {"Authorization": f"Bearer {token}"}


def _fake_result(question: str) -> dict:
    return {
        "question": question,
        "sql": 'SELECT "month", "amount" FROM "sales"',
        "columns": ["month", "amount"],
        "rows": [{"month": "2024-01", "amount": 100}],
        "suggestedVisualization": {"type": "bar", "title": "Sales by month"},
        "explanation": "**ERP-PROD** accounted for `62%` of failures.",
        "dataSourcesUsed": ["sales"],
        "status": "success",
        "error": None,
    }


async def _create_user(client, service_headers, tenant_id: int, slug: str, role: str) -> dict:
    r = await client.post(
        f"/api/tenants/{tenant_id}/users",
        json={
            "email": f"{slug}@test.com",
            "display_name": slug,
            "role": role,
            "external_id": f"ext-{slug}",
        },
        headers=service_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _setup(client, service_headers, slug: str):
    r = await client.post(
        "/api/tenants",
        json={"slug": slug, "name": f"{slug} tenant"},
        headers=service_headers,
    )
    assert r.status_code == 201
    tenant = r.json()

    user = await _create_user(client, service_headers, tenant["id"], slug, "editor")
    headers = _headers(tenant["id"], user["id"])

    r = await client.post(
        "/api/projects",
        json={"name": "Recent Conv Project", "description": "x", "is_shared": False},
        headers=headers,
    )
    assert r.status_code == 201
    project = r.json()
    return tenant, user, project, headers


@pytest.fixture(autouse=True)
def _mock_supabase(monkeypatch):
    import app.routes.tenants as tenants_module
    from app.services.supabase_auth_service import SupabaseAuthService, SupabaseUser

    class _FakeSupabase(SupabaseAuthService):
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def create_or_invite_user(self, email, **kwargs):
            return SupabaseUser(
                id=f"supa-{email}",
                email=email,
                created=True,
                action_link=f"https://invite/{email}",
            )

    class _FakeEmail:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def send_transactional_email(self, **kwargs) -> bool:
            return True

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)


@pytest.fixture(autouse=True)
def _fake_ask(monkeypatch):
    async def _fake(*args, **kwargs):
        return _fake_result(kwargs.get("question", "q"))

    monkeypatch.setattr(
        "app.services.conversational_analytics._ask_and_run_core", _fake
    )


async def _ask(client, headers, project_id: int, message: str, surface: str = "project_insights"):
    r = await client.post(
        "/api/conversational-analytics/conversations",
        json={"project_id": project_id, "initial_message": message, "surface": surface},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    conversation = r.json()
    if len(conversation["turns"]) > 1:
        return conversation
    return conversation


async def _follow_up(client, headers, conversation_id: int, message: str):
    r = await client.post(
        f"/api/conversational-analytics/conversations/{conversation_id}/turns",
        json={"message": message},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _recent(client, headers, project_id: int, limit: int | None = None):
    qs = f"?limit={limit}" if limit is not None else ""
    r = await client.get(
        f"/api/conversational-analytics/projects/{project_id}/recent-conversations{qs}",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_returns_recent_successful_turns_newest_first(client, service_headers):
    _, _, project, headers = await _setup(client, service_headers, "recent-order")

    conversation = await _ask(client, headers, project["id"], "first question")
    for message in ("second question", "third question"):
        await _follow_up(client, headers, conversation["id"], message)

    body = await _recent(client, headers, project["id"])
    assert body["project_id"] == project["id"]
    questions = [i["question_preview"] for i in body["items"]]
    assert questions == ["third question", "second question", "first question"]
    assert all(i["conversation_id"] == conversation["id"] for i in body["items"])
    assert all(i["turn_id"] > 0 for i in body["items"])
    assert body["items"][0]["result_type"] == "chart"


async def test_limit_defaults_to_four(client, service_headers):
    _, _, project, headers = await _setup(client, service_headers, "recent-limit")

    conversation = await _ask(client, headers, project["id"], "question 1")
    for n in range(2, 7):
        await _follow_up(client, headers, conversation["id"], f"question {n}")

    body = await _recent(client, headers, project["id"])
    assert len(body["items"]) == 4
    assert body["items"][0]["question_preview"] == "question 6"

    body = await _recent(client, headers, project["id"], limit=2)
    assert len(body["items"]) == 2


async def test_excludes_other_projects_and_business_insight_surface(client, service_headers):
    _, _, project, headers = await _setup(client, service_headers, "recent-surface")

    await _ask(client, headers, project["id"], "project question")
    await _ask(
        client, headers, project["id"], "business question", surface="business_insights"
    )

    r = await client.post(
        "/api/projects",
        json={"name": "Other", "description": "x", "is_shared": False},
        headers=headers,
    )
    other = r.json()
    await _ask(client, headers, other["id"], "other project question")

    body = await _recent(client, headers, project["id"])
    questions = [i["question_preview"] for i in body["items"]]
    assert questions == ["project question"]


async def test_excludes_another_users_private_conversation(client, service_headers):
    tenant, _, project, headers = await _setup(client, service_headers, "recent-privacy")
    await _ask(client, headers, project["id"], "owner only question")

    admin = await _create_user(
        client, service_headers, tenant["id"], "recent-privacy-admin", "admin"
    )
    admin_headers = _headers(tenant["id"], admin["id"], role="admin")

    body = await _recent(client, admin_headers, project["id"])
    assert body["items"] == []


async def test_excludes_failed_turns_and_archived_conversations(client, service_headers, monkeypatch):
    _, _, project, headers = await _setup(client, service_headers, "recent-failed")

    conversation = await _ask(client, headers, project["id"], "good question")

    async def _boom(*args, **kwargs):
        return {
            "question": kwargs.get("question", ""),
            "sql": None,
            "columns": [],
            "rows": [],
            "suggestedVisualization": None,
            "explanation": None,
            "dataSourcesUsed": [],
            "status": "error",
            "error": "engine down",
        }

    monkeypatch.setattr(
        "app.services.conversational_analytics._ask_and_run_core", _boom
    )
    await _follow_up(client, headers, conversation["id"], "failing question")

    body = await _recent(client, headers, project["id"])
    assert [i["question_preview"] for i in body["items"]] == ["good question"]

    r = await client.delete(
        f"/api/conversational-analytics/conversations/{conversation['id']}",
        headers=headers,
    )
    assert r.status_code in (200, 204)
    body = await _recent(client, headers, project["id"])
    assert body["items"] == []


async def test_response_excludes_sql_and_internal_fields(client, service_headers):
    _, _, project, headers = await _setup(client, service_headers, "recent-safe")
    await _ask(client, headers, project["id"], "safe preview question")

    body = await _recent(client, headers, project["id"])
    item = body["items"][0]
    assert set(item) == {
        "conversation_id",
        "turn_id",
        "surface",
        "question_preview",
        "result_preview",
        "result_type",
        "completed_at",
    }
    assert "SELECT" not in item["result_preview"]
    assert "**" not in item["result_preview"]


async def test_requires_project_access(client, service_headers):
    _, _, project, _ = await _setup(client, service_headers, "recent-access")
    _, _, _, other_headers = await _setup(client, service_headers, "recent-access-2")

    r = await client.get(
        f"/api/conversational-analytics/projects/{project['id']}/recent-conversations",
        headers=other_headers,
    )
    assert r.status_code == 404


def test_preview_sanitization():
    assert to_plain_text("# Title\n\n**bold** and `code`") == "Title bold and code"
    assert to_plain_text("<script>alert(1)</script>ok") == "alert(1) ok"
    assert question_preview("  What   changed?  ") == "What changed?"
    assert result_preview(None, None, None) == NO_RESULT_PREVIEW
    assert result_preview(None, {"summary": "Sales rose 12%"}) == "Sales rose 12%"
    assert result_preview(None, None, {"type": "bar", "title": "Sales"}) == "Sales"
    assert question_preview("x" * 400).endswith("…")
