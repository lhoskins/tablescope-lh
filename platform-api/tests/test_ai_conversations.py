"""Tests for AI conversations: live messaging + conversation branching."""

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
    async def send_transactional_email(
        self, *, to, template, variables, subject=None, reply_to=None
    ) -> bool:
        return True


@pytest.fixture(autouse=True)
def _mock_externals(monkeypatch):
    import app.routes.ai_proxy as ai_proxy
    import app.routes.tenants as tenants_module

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)

    async def _fake_forward(path, payload):
        if path == "/ai/ask":
            return {"answer": f"Echo: {payload.get('question')}"}
        return {}

    monkeypatch.setattr(ai_proxy, "_forward_to_ai", _fake_forward)


async def _setup(client, service_headers):
    r = await client.post(
        "/api/tenants",
        json={"slug": "convo-tenant", "name": "Convo Tenant"},
        headers=service_headers,
    )
    assert r.status_code == 201
    tenant = r.json()
    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": "c@test.com",
            "display_name": "Convo User",
            "role": "editor",
            "external_id": "ext-c",
        },
        headers=service_headers,
    )
    assert r.status_code == 201
    user = r.json()
    headers = {
        "Authorization": "Bearer "
        + create_access_token(
            sub="ext-c",
            tenant_id=tenant["id"],
            user_id=user["id"],
            role="editor",
        )
    }
    r = await client.post(
        "/api/projects",
        json={"name": "P", "description": "d", "is_shared": False},
        headers=headers,
    )
    assert r.status_code == 201
    project = r.json()
    return tenant, user, project, headers


async def test_message_returns_updated_conversation_without_refresh(
    client, service_headers
) -> None:
    _t, _u, project, headers = await _setup(client, service_headers)

    convo = (
        await client.post("/api/ai/conversations", json={}, headers=headers)
    ).json()

    r = await client.post(
        f"/api/ai/conversations/{convo['id']}/messages",
        json={"question": "What is revenue?", "project_id": project["id"]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # The POST response carries the full updated thread (user + assistant),
    # so the client can render it without a separate refresh.
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["user", "assistant"]
    assert body["messages"][1]["content"] == "Echo: What is revenue?"
    # First user message becomes the title.
    assert body["title"] == "What is revenue?"


async def test_branch_conversation_copies_history_to_point(
    client, service_headers
) -> None:
    _t, _u, project, headers = await _setup(client, service_headers)
    convo = (
        await client.post("/api/ai/conversations", json={}, headers=headers)
    ).json()

    for q in ("first", "second", "third"):
        r = await client.post(
            f"/api/ai/conversations/{convo['id']}/messages",
            json={"question": q, "project_id": project["id"]},
            headers=headers,
        )
        assert r.status_code == 200
    full = r.json()
    # Branch from the assistant reply to "second" (4th message, index 3).
    branch_point = full["messages"][3]

    r = await client.post(
        f"/api/ai/conversations/{convo['id']}/branch",
        json={"message_id": branch_point["id"]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    branch = r.json()
    assert branch["id"] != convo["id"]
    assert branch["parentConversationId"] == convo["id"]
    assert branch["branchedFromMessageId"] == branch_point["id"]
    # Copied messages stop at the branch point (4 of the 6 originals).
    assert len(branch["messages"]) == 4
    assert [m["content"] for m in branch["messages"]] == [
        "first",
        "Echo: first",
        "second",
        "Echo: second",
    ]
    # The original thread is untouched.
    orig = (
        await client.get(
            f"/api/ai/conversations/{convo['id']}", headers=headers
        )
    ).json()
    assert len(orig["messages"]) == 6


async def test_branch_without_message_id_forks_from_last(
    client, service_headers
) -> None:
    _t, _u, project, headers = await _setup(client, service_headers)
    convo = (
        await client.post("/api/ai/conversations", json={}, headers=headers)
    ).json()
    for q in ("first", "second"):
        await client.post(
            f"/api/ai/conversations/{convo['id']}/messages",
            json={"question": q, "project_id": project["id"]},
            headers=headers,
        )

    # Omitting message_id branches from the tail (the whole thread).
    r = await client.post(
        f"/api/ai/conversations/{convo['id']}/branch",
        json={},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    branch = r.json()
    assert branch["parentConversationId"] == convo["id"]
    assert len(branch["messages"]) == 4


async def test_branch_empty_conversation_400(client, service_headers) -> None:
    _t, _u, _project, headers = await _setup(client, service_headers)
    convo = (
        await client.post("/api/ai/conversations", json={}, headers=headers)
    ).json()
    r = await client.post(
        f"/api/ai/conversations/{convo['id']}/branch",
        json={},
        headers=headers,
    )
    assert r.status_code == 400


async def test_branch_unknown_message_404(client, service_headers) -> None:
    _t, _u, _project, headers = await _setup(client, service_headers)
    convo = (
        await client.post("/api/ai/conversations", json={}, headers=headers)
    ).json()
    r = await client.post(
        f"/api/ai/conversations/{convo['id']}/branch",
        json={"message_id": 999999},
        headers=headers,
    )
    assert r.status_code == 404


async def test_branch_other_tenant_conversation_404(
    client_strict, service_headers
) -> None:
    _t, _u, project, headers = await _setup(client_strict, service_headers)
    convo = (
        await client_strict.post(
            "/api/ai/conversations", json={}, headers=headers
        )
    ).json()
    await client_strict.post(
        f"/api/ai/conversations/{convo['id']}/messages",
        json={"question": "hi", "project_id": project["id"]},
        headers=headers,
    )
    # A different tenant/user cannot branch someone else's conversation.
    other = {
        "Authorization": "Bearer "
        + create_access_token(
            sub="x", tenant_id=99999, user_id=99999, role="editor"
        )
    }
    r = await client_strict.post(
        f"/api/ai/conversations/{convo['id']}/branch",
        json={"message_id": 1},
        headers=other,
    )
    # Non-member tokens are rejected by membership enforcement before reaching
    # the conversation lookup.
    assert r.status_code == 403
