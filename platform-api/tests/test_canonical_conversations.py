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


async def test_project_insights_never_widens_to_another_project(
    client, db_session, service_headers, monkeypatch
):
    """Project Insights is scoped to the project the user picked -- a card
    that only lives in a different project the user can also access must
    never be offered as the answer, even though AI Assistant and Business
    Insights would happily widen the search to find it."""
    from app.models.business_insight_result import BusinessInsightResult

    tenant, _, project, headers = await _setup(client, service_headers, "pi-no-widen")

    other_r = await client.post(
        "/api/projects",
        json={"name": "Other Project", "description": "x", "is_shared": False},
        headers=headers,
    )
    assert other_r.status_code == 201
    other_project = other_r.json()

    db_session.add(
        BusinessInsightResult(
            tenant_id=tenant["id"],
            project_id=other_project["id"],
            granularity=3,
            payload={
                "insights": [
                    {
                        "insightId": "other-001",
                        "projectName": "Other Project",
                        "title": "Some other analysis",
                        "summary": "...",
                        "chart": {"type": "line", "data": {"rows": []}},
                        "severity": "info",
                    }
                ]
            },
        )
    )
    await db_session.commit()

    async def _fake_generation_error(*args, **kwargs):
        return {"status": "generation_error", "sql": "", "error": "no source matched"}

    async def _fake_no_prose(*args, **kwargs):
        return ""

    monkeypatch.setattr(
        "app.services.conversational_analytics._ask_and_run_core",
        _fake_generation_error,
    )
    monkeypatch.setattr(
        "app.services.conversational_analytics._forward_prose_answer",
        _fake_no_prose,
    )

    from app.services import insight_card_match as icm

    calls: list[list[str]] = []

    async def _fake_select(*, candidates, **kwargs):
        calls.append([c["insight_id"] for c in candidates])
        return {"insight_id": "other-001", "confidence": 0.9, "reason": "eager"}

    monkeypatch.setattr(icm.ai_intelligence_client, "is_enabled", lambda: True)
    monkeypatch.setattr(icm.ai_intelligence_client, "select_matching_insight_card", _fake_select)

    r = await client.post(
        "/api/conversational-analytics/canonical-turns",
        json={
            "surface": "project_insights",
            "project_id": project["id"],
            "message": "Why is this changing?",
            "client_request_id": "req-1",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    turn = r.json()["turn"]
    assert turn["matched_insight"] is None
    # `project` (the surface's own project) has no cards at all, so with
    # widening disabled there is nothing to offer -- the selector must never
    # even be called for the widen pass into `other_project`.
    assert calls == []


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


async def test_project_workspace_appends_to_one_conversation_per_project(client, service_headers):
    _, _, project, headers = await _setup(client, service_headers, "pw-canonical")

    r1 = await client.post(
        "/api/conversational-analytics/canonical-turns",
        json={
            "surface": "project_workspace",
            "project_id": project["id"],
            "message": "first",
            "client_request_id": "req-1",
        },
        headers=headers,
    )
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1["surface"] == "project_workspace"
    assert body1["project_id"] == project["id"]
    assert body1["conversation_created"] is True

    r2 = await client.post(
        "/api/conversational-analytics/canonical-turns",
        json={
            "surface": "project_workspace",
            "project_id": project["id"],
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


async def test_project_workspace_never_re_resolves_to_another_project(
    client, service_headers, monkeypatch
):
    """Live incident: a project_workspace conversation titled "Workspace —
    Sales" answered "Show my top performers" from an unrelated project's data
    (a movies dataset) because the per-turn cross-project resolver was being
    consulted for this surface at all. project_workspace's own
    canonical_scope_key() requires and keys on a project_id exactly like
    project_insights -- the resolver must never even run for it, regardless
    of how confidently it would point elsewhere."""
    _, _, project, headers = await _setup(client, service_headers, "pw-no-resolve")

    other_r = await client.post(
        "/api/projects",
        json={"name": "Other Project", "description": "x", "is_shared": False},
        headers=headers,
    )
    assert other_r.status_code == 201
    other_project = other_r.json()

    calls: list[str] = []

    async def _fake_resolver(*args, **kwargs):
        calls.append("called")
        from app.services.business_insight_project_resolver import ProjectResolveResult

        return ProjectResolveResult(
            status="resolved",
            project_id=other_project["id"],
            project_name="Other Project",
            confidence=0.99,
            reason="eager wrong guess",
        )

    monkeypatch.setattr(
        "app.services.conversational_analytics.resolve_business_insight_project",
        _fake_resolver,
    )

    r = await client.post(
        "/api/conversational-analytics/canonical-turns",
        json={
            "surface": "project_workspace",
            "project_id": project["id"],
            "message": "Show my top performers",
            "client_request_id": "req-1",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Must stay pinned to the project this workspace conversation belongs to
    # -- never silently swapped to the resolver's (wrong) guess.
    assert body["project_id"] == project["id"]
    assert calls == []


async def test_project_workspace_never_widens_insight_cards_to_another_project(
    client, service_headers, monkeypatch
):
    """Same guarantee as test_project_insights_never_widens_to_another_project,
    for project_workspace -- "Workspace — Sales" must never even look at
    another project's (e.g. IT's) cached Insight Cards as candidates, even
    though AI Assistant and Business Insights would happily widen the
    search.

    Spies on `_cards_for_projects` (the function `allow_cross_project`
    actually gates a second call to) rather than the LLM selector: the real
    call site passes `use_llm=False`, so the LLM path this file's sibling
    project_insights test mocks is never reached regardless of widening.
    Also deliberately does NOT mock `_ask_and_run_core` into a
    "generation_error" the way that sibling test does -- `execute_turn`
    returns early on any non-"success" status (before ever reaching the
    insight-matching block at all), which would make an assertion here pass
    vacuously the same way the LLM-mock one did. The autouse `_fake_ask`'s
    successful "month"/"amount"/"sales" result has zero term overlap with
    this question, which is what actually drops the live-result score below
    the 0.95 threshold that gates whether insight-card matching runs.
    """
    _, _, project, headers = await _setup(client, service_headers, "pw-no-widen")

    other_r = await client.post(
        "/api/projects",
        json={"name": "Other Project", "description": "x", "is_shared": False},
        headers=headers,
    )
    assert other_r.status_code == 201
    other_project = other_r.json()

    from app.services import insight_card_match as icm

    calls: list[list[int]] = []
    real_cards_for_projects = icm._cards_for_projects

    async def _spy_cards_for_projects(session, *, tenant_id, project_ids, user_id=None):
        calls.append(list(project_ids))
        return await real_cards_for_projects(
            session, tenant_id=tenant_id, project_ids=project_ids, user_id=user_id
        )

    monkeypatch.setattr(icm, "_cards_for_projects", _spy_cards_for_projects)

    r = await client.post(
        "/api/conversational-analytics/canonical-turns",
        json={
            "surface": "project_workspace",
            "project_id": project["id"],
            "message": "Show my top performers",
            "client_request_id": "req-1",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    # Candidate gathering must only ever be called for this workspace's own
    # project -- never for `other_project`, which is what widening would do.
    assert calls == [[project["id"]]]
    assert other_project["id"] not in [pid for call in calls for pid in call]


async def test_project_workspace_grounds_on_active_table(
    client, db_session, service_headers, monkeypatch
):
    _, _, project, headers = await _setup(client, service_headers, "pw-grounding")

    from app.models import SavedQuery

    query = SavedQuery(
        project_id=project["id"],
        name="Monthly Revenue",
        description="Revenue by month",
        sql_text='SELECT * FROM "sales"',
    )
    db_session.add(query)
    await db_session.commit()
    await db_session.refresh(query)

    captured: dict = {}

    async def _fake_capture(*args, **kwargs):
        captured["question"] = kwargs.get("question", "")
        return {
            "question": kwargs.get("question", ""),
            "sql": "SELECT 1",
            "columns": ["x"],
            "rows": [{"x": 1}],
            "suggestedVisualization": {"type": "bar", "title": "x"},
            "explanation": "ok",
            "dataSourcesUsed": ["sales"],
            "status": "success",
            "error": None,
        }

    monkeypatch.setattr(
        "app.services.conversational_analytics._ask_and_run_core", _fake_capture
    )

    r = await client.post(
        "/api/conversational-analytics/canonical-turns",
        json={
            "surface": "project_workspace",
            "project_id": project["id"],
            "message": "How is this trending?",
            "client_request_id": "req-1",
            "active_resource_type": "table",
            "active_resource_id": query.id,
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert "Monthly Revenue" in captured["question"]
    assert "Active workspace item" in captured["question"]


async def test_project_workspace_grounds_on_multiple_active_resources(
    client, db_session, service_headers, monkeypatch
):
    tenant, _, project, headers = await _setup(client, service_headers, "pw-multi")

    from app.models import Dashboard, SavedQuery

    query = SavedQuery(
        project_id=project["id"],
        name="Monthly Revenue",
        description="Revenue by month",
        sql_text='SELECT * FROM "sales"',
    )
    dashboard = Dashboard(
        project_id=project["id"],
        tenant_id=tenant["id"],
        name="Exec Overview",
        config={"widgets": []},
    )
    db_session.add_all([query, dashboard])
    await db_session.commit()
    await db_session.refresh(query)
    await db_session.refresh(dashboard)

    captured: dict = {}

    async def _fake_capture(*args, **kwargs):
        captured["question"] = kwargs.get("question", "")
        return {
            "question": kwargs.get("question", ""),
            "sql": "SELECT 1",
            "columns": ["x"],
            "rows": [{"x": 1}],
            "suggestedVisualization": {"type": "bar", "title": "x"},
            "explanation": "ok",
            "dataSourcesUsed": [],
            "status": "success",
            "error": None,
        }

    monkeypatch.setattr(
        "app.services.conversational_analytics._ask_and_run_core", _fake_capture
    )

    r = await client.post(
        "/api/conversational-analytics/canonical-turns",
        json={
            "surface": "project_workspace",
            "project_id": project["id"],
            "message": "Summarize my workspace",
            "client_request_id": "req-multi",
            "active_resources": [
                {"resource_type": "table", "resource_id": query.id},
                {"resource_type": "dashboard", "resource_id": dashboard.id},
            ],
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert "Monthly Revenue" in captured["question"]
    assert "Exec Overview" in captured["question"]


async def test_project_workspace_active_resource_from_another_project_is_ignored(
    client, db_session, service_headers, monkeypatch
):
    """A dashboard id from a project the user isn't currently working in must
    never leak its name/config into another project's workspace grounding."""
    tenant, _, project, headers = await _setup(client, service_headers, "pw-cross-project")

    other_r = await client.post(
        "/api/projects",
        json={"name": "Other Secret Project", "description": "x", "is_shared": False},
        headers=headers,
    )
    assert other_r.status_code == 201
    other_project = other_r.json()

    from app.models import Dashboard

    other_dashboard = Dashboard(
        project_id=other_project["id"],
        tenant_id=tenant["id"],
        name="Secret Executive Dashboard",
        config={"widgets": []},
    )
    db_session.add(other_dashboard)
    await db_session.commit()
    await db_session.refresh(other_dashboard)

    captured: dict = {}

    async def _fake_capture(*args, **kwargs):
        captured["question"] = kwargs.get("question", "")
        return {
            "question": kwargs.get("question", ""),
            "sql": "SELECT 1",
            "columns": ["x"],
            "rows": [{"x": 1}],
            "suggestedVisualization": {"type": "bar", "title": "x"},
            "explanation": "ok",
            "dataSourcesUsed": [],
            "status": "success",
            "error": None,
        }

    monkeypatch.setattr(
        "app.services.conversational_analytics._ask_and_run_core", _fake_capture
    )

    r = await client.post(
        "/api/conversational-analytics/canonical-turns",
        json={
            "surface": "project_workspace",
            "project_id": project["id"],
            "message": "What's on this dashboard?",
            "client_request_id": "req-1",
            "active_resource_type": "dashboard",
            "active_resource_id": other_dashboard.id,
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert "Secret Executive Dashboard" not in captured["question"]
    assert "Active workspace item" not in captured["question"]


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
