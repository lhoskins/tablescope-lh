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


async def test_ask_attaches_conversational_envelope(
    client, service_headers
) -> None:
    # The /ask chat surface stamps the shared ResponseEnvelope (M4 fast-follow)
    # so the frontend renders it through the same ResponsePresenter as every
    # other migrated surface. Additive — the legacy `answer` field is untouched.
    _t, _u, project, headers = await _setup(client, service_headers)

    r = await client.post(
        "/api/ai/ask",
        json={"question": "what does this project contain?", "project_id": project["id"]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"] == "Echo: what does this project contain?"

    env = body["envelope"]
    assert env["mode"] == "conversational"
    assert env["sections"] == body["presentation"]["sections"]
    assert env["sections"][0] == "prose_answer"
    # Prose answer carries the answer text; no chart/grid/SQL for a chat reply.
    assert env["answer"] == body["answer"]
    assert "chart" not in env
    assert "sql" not in env
    assert "columns" not in env


async def test_data_question_executes_and_returns_data(
    client, service_headers, monkeypatch
) -> None:
    # When the question grounds on a source, the assistant answers like the
    # Project Insight page: it executes SQL and returns the real result (rows +
    # suggested chart) attached to the message, not just prose.
    import app.routes.ai_proxy as ai_proxy

    async def _fake_core(session, context, **kwargs):
        return {
            "question": kwargs["question"],
            "sql": "SELECT Carrier, AVG(x) AS avg_days FROM LOG_Shipments_CSV",
            "columns": ["Carrier", "avg_days"],
            "rows": [
                {"Carrier": "DHL", "avg_days": 4.2},
                {"Carrier": "FedEx", "avg_days": 4.25},
            ],
            "suggestedVisualization": {"type": "bar"},
            "explanation": "Average days late per carrier.",
            "dataSourcesUsed": ["LOG_Shipments_CSV"],
            "status": "success",
            "error": None,
        }

    monkeypatch.setattr(ai_proxy, "_ask_and_run_core", _fake_core)

    _t, _u, project, headers = await _setup(client, service_headers)
    convo = (
        await client.post("/api/ai/conversations", json={}, headers=headers)
    ).json()
    r = await client.post(
        f"/api/ai/conversations/{convo['id']}/messages",
        json={
            "question": "average days late by carrier",
            "project_id": project["id"],
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    msg = r.json()["messages"][1]
    assert msg["role"] == "assistant"
    # Data-grounded answer text (explanation), not an "Echo:" AI-server reply.
    assert "Echo:" not in msg["content"]
    assert "Average days late per carrier." in msg["content"]
    # The executed result is attached for the chat to render a table/chart.
    assert msg["data"] is not None
    assert msg["data"]["columns"] == ["Carrier", "avg_days"]
    assert len(msg["data"]["rows"]) == 2
    assert msg["data"]["suggestedVisualization"]["type"] == "bar"


async def test_ask_data_question_returns_structured_envelope(
    client, service_headers, monkeypatch
) -> None:
    # The stateless /ask surface (AI Assistant screen) must answer a data
    # question with an executed result — chart + grid + hidden SQL under the
    # shared envelope — instead of a prose answer that prints SQL. This mirrors
    # the conversations chat and fixes the "assistant returned SQL text" bug.
    import app.routes.ai_proxy as ai_proxy

    async def _fake_core(session, context, **kwargs):
        run = {
            "question": kwargs["question"],
            "sql": 'SELECT "Dept", COUNT(*) AS n FROM assets GROUP BY "Dept"',
            "columns": ["Dept", "n"],
            "rows": [{"Dept": "IT", "n": 12}, {"Dept": "HR", "n": 4}],
            "suggestedVisualization": {"type": "bar"},
            "explanation": "Assets per department.",
            "dataSourcesUsed": ["assets_CSV"],
            "status": "success",
            "error": None,
        }
        ai_proxy._attach_presentation(run)
        return run

    monkeypatch.setattr(ai_proxy, "_ask_and_run_core", _fake_core)

    _t, _u, project, headers = await _setup(client, service_headers)
    r = await client.post(
        "/api/ai/ask",
        json={
            "question": "how many assets per department",
            "project_id": project["id"],
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Grounded on data, not an "Echo:" prose reply.
    assert "Echo:" not in body["answer"]
    env = body["envelope"]
    assert env["mode"] == "structured"
    assert "chart" in env["sections"]
    assert "grid" in env["sections"]
    assert "show_sql" in env["sections"]
    assert env["columns"] == ["Dept", "n"]
    assert env["sql"].startswith("SELECT")


async def test_ask_non_data_question_falls_back_to_prose(
    client, service_headers, monkeypatch
) -> None:
    # A question the resolver can't ground on data falls through to the prose
    # documents/knowledge-graph answer (conversational envelope), unchanged.
    import app.routes.ai_proxy as ai_proxy

    async def _fake_core(session, context, **kwargs):
        return {
            "question": kwargs["question"],
            "sql": "",
            "columns": [],
            "rows": [],
            "suggestedVisualization": {"type": "table"},
            "explanation": "",
            "dataSourcesUsed": [],
            "status": "generation_error",
            "error": "no source",
        }

    monkeypatch.setattr(ai_proxy, "_ask_and_run_core", _fake_core)

    _t, _u, project, headers = await _setup(client, service_headers)
    r = await client.post(
        "/api/ai/ask",
        json={
            "question": "summarize the project policies",
            "project_id": project["id"],
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"] == "Echo: summarize the project policies"
    assert body["envelope"]["mode"] == "conversational"


async def test_non_data_question_falls_back_to_prose(
    client, service_headers, monkeypatch
) -> None:
    # When the question can't be grounded on a source, we fall back to the
    # free-text AI answer and attach no structured data.
    import app.routes.ai_proxy as ai_proxy

    async def _fake_core(session, context, **kwargs):
        return {
            "question": kwargs["question"],
            "sql": "",
            "columns": [],
            "rows": [],
            "suggestedVisualization": {"type": "table"},
            "explanation": "",
            "dataSourcesUsed": [],
            "status": "generation_error",
            "error": "no source",
        }

    monkeypatch.setattr(ai_proxy, "_ask_and_run_core", _fake_core)

    _t, _u, project, headers = await _setup(client, service_headers)
    convo = (
        await client.post("/api/ai/conversations", json={}, headers=headers)
    ).json()
    r = await client.post(
        f"/api/ai/conversations/{convo['id']}/messages",
        json={
            "question": "summarize my project documents",
            "project_id": project["id"],
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    msg = r.json()["messages"][1]
    assert msg["content"] == "Echo: summarize my project documents"
    assert msg["data"] is None


async def test_query_summary_intent_answered_from_db(
    client, service_headers
) -> None:
    # "summary of my queries" is answered directly from the DB (no AI server),
    # so it never hits the signature path and reflects real authorized queries.
    _t, _u, project, headers = await _setup(client, service_headers)
    for name in ("Revenue by Month", "Top Vendors"):
        r = await client.post(
            f"/api/projects/{project['id']}/queries",
            json={"name": name, "left_datasource": "sales_CSV"},
            headers=headers,
        )
        assert r.status_code == 201

    convo = (
        await client.post("/api/ai/conversations", json={}, headers=headers)
    ).json()
    r = await client.post(
        f"/api/ai/conversations/{convo['id']}/messages",
        json={
            "question": "Can you give me a summary of my queries?",
            "project_id": project["id"],
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    answer = r.json()["messages"][1]["content"]
    # Real summary — not the mocked "Echo:" AI-server reply.
    assert "Echo:" not in answer
    assert "2 active queries" in answer
    assert project["name"] in answer


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
