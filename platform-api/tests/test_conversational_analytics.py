"""Tests for the conversational analytics API."""

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
            "display_name": "Conv User",
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
        json={"name": "Conv Project", "description": "x", "is_shared": False},
        headers=headers,
    )
    assert r.status_code == 201
    project = r.json()
    return tenant, user, project, headers


def _fake_ask_and_run_core_result(question: str) -> dict:
    return {
        "question": question,
        "sql": 'SELECT "month", "amount" FROM "sales" ORDER BY "month"',
        "columns": ["month", "amount"],
        "rows": [{"month": "2024-01", "amount": 100}, {"month": "2024-02", "amount": 200}],
        "suggestedVisualization": {"type": "bar", "title": "Sales by month"},
        "explanation": "Sales trend over two months.",
        "dataSourcesUsed": ["sales"],
        "status": "success",
        "error": None,
    }


async def test_create_conversation_with_initial_message(client, service_headers, monkeypatch):
    _, _, project, headers = await _setup(client, service_headers, "conv-create")

    async def _fake(*args, **kwargs):
        return _fake_ask_and_run_core_result(kwargs.get("question", "sales"))

    monkeypatch.setattr(
        "app.services.conversational_analytics._ask_and_run_core",
        _fake,
    )

    r = await client.post(
        "/api/conversational-analytics/conversations",
        json={
            "project_id": project["id"],
            "initial_message": "Show me sales by month",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["project_id"] == project["id"]
    assert body["title"] == "Show me sales by month"
    assert len(body["turns"]) == 1
    assert body["turns"][0]["status"] == "success"
    assert body["turns"][0]["sql"]
    assert body["turns"][0]["result"]["columns"] == ["month", "amount"]
    assert body["turns"][0]["chart_config"]["type"] == "bar"


async def test_generation_error_surfaces_matching_insight_card_over_prose(
    client, db_session, service_headers, monkeypatch
):
    """A question the fresh SQL path can't answer, but that an existing
    Insight Card already answered, must point back to that card — chart and
    breadcrumb id included — instead of degrading to unattributed KG prose."""
    from app.models.business_insight_result import BusinessInsightResult

    tenant, _, project, headers = await _setup(client, service_headers, "conv-insight-match")

    db_session.add(
        BusinessInsightResult(
            tenant_id=tenant["id"],
            project_id=project["id"],
            granularity=3,
            payload={
                "insights": [
                    {
                        "insightId": "mat-cost-001",
                        "projectName": "Conv Project",
                        "title": "Material cost on the rise",
                        "summary": "Weekly material cost has increased steadily since January 2026.",
                        "chart": {"type": "line", "data": {"rows": []}},
                        "severity": "warning",
                    }
                ]
            },
        )
    )
    await db_session.commit()

    async def _fake_generation_error(*args, **kwargs):
        return {"status": "generation_error", "sql": "", "error": "no source matched"}

    async def _fail_if_called(*args, **kwargs):
        raise AssertionError("prose fallback must not run when a card matches")

    async def _fake_select(**kwargs):
        return {"insight_id": "mat-cost-001", "confidence": 0.9, "reason": "on topic"}

    monkeypatch.setattr(
        "app.services.conversational_analytics._ask_and_run_core",
        _fake_generation_error,
    )
    monkeypatch.setattr(
        "app.services.conversational_analytics._forward_prose_answer",
        _fail_if_called,
    )
    from app.services import insight_card_match as icm

    monkeypatch.setattr(icm.ai_intelligence_client, "is_enabled", lambda: True)
    monkeypatch.setattr(icm.ai_intelligence_client, "select_matching_insight_card", _fake_select)

    r = await client.post(
        "/api/conversational-analytics/conversations",
        json={
            "project_id": project["id"],
            "initial_message": "Why is material cost increasing?",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    turn = r.json()["turns"][0]
    assert turn["status"] == "success"
    assert turn["matched_insight"]["insightId"] == "mat-cost-001"
    assert turn["matched_insight"]["title"] == "Material cost on the rise"
    assert turn["matched_insight"]["chart"] == {"type": "line", "data": {"rows": []}}
    assert "Material cost on the rise" in turn["assistant_message"]
    assert turn["sql"] is None
    assert turn["chart_config"] is None

    # The message must say plainly that this is a fallback from a failed
    # live attempt -- "I found an existing analysis that answers this" reads
    # as the deliberate primary answer and hides that live SQL generation
    # just failed, which is itself important information (especially for a
    # question simple enough that it should never fail to begin with).
    assert "couldn't build a live query" in turn["assistant_message"]
    assert turn["error_code"] == "live_query_fallback_generation_error"


async def test_matched_insight_fallback_surfaces_ai_server_unavailable_detail(
    client, db_session, service_headers, monkeypatch
):
    """_ai_generation_error()'s "friendly" message defaults to a generic
    string in exactly the AI-server-unavailable case -- the real reason only
    ever lands in errorDetails.validationError. That must reach the visible
    message, not just a DB column nobody reads, or an outage looks identical
    to "no relevant source" and is impossible to tell apart from the UI."""
    from app.models.business_insight_result import BusinessInsightResult

    tenant, _, project, headers = await _setup(client, service_headers, "conv-ai-down")

    db_session.add(
        BusinessInsightResult(
            tenant_id=tenant["id"],
            project_id=project["id"],
            granularity=3,
            payload={
                "insights": [
                    {
                        "insightId": "backup-001",
                        "projectName": "Conv Project",
                        "title": "Backup Jobs by System",
                        "summary": "Backup job counts grouped by system.",
                        "chart": {"type": "bar", "data": {"rows": []}},
                        "severity": "info",
                    }
                ]
            },
        )
    )
    await db_session.commit()

    async def _fake_ai_server_down(*args, **kwargs):
        return {
            "status": "generation_error",
            "sql": "",
            "error": "We could not safely build a query for this question.",
            "errorDetails": {"validationError": "AI server is unavailable"},
        }

    async def _fake_select(**kwargs):
        return {"insight_id": "backup-001", "confidence": 0.9, "reason": "on topic"}

    monkeypatch.setattr(
        "app.services.conversational_analytics._ask_and_run_core",
        _fake_ai_server_down,
    )
    from app.services import insight_card_match as icm

    monkeypatch.setattr(icm.ai_intelligence_client, "is_enabled", lambda: True)
    monkeypatch.setattr(icm.ai_intelligence_client, "select_matching_insight_card", _fake_select)

    r = await client.post(
        "/api/conversational-analytics/conversations",
        json={
            "project_id": project["id"],
            "initial_message": "Show me IT backup jobs by system",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    turn = r.json()["turns"][0]
    assert turn["status"] == "success"
    assert "AI server is unavailable" in turn["assistant_message"]
    assert turn["matched_insight"]["insightId"] == "backup-001"


async def test_list_and_get_conversations(client, service_headers, monkeypatch):
    _, _, project, headers = await _setup(client, service_headers, "conv-list")

    async def _fake(*args, **kwargs):
        return _fake_ask_and_run_core_result(kwargs.get("question", ""))

    monkeypatch.setattr(
        "app.services.conversational_analytics._ask_and_run_core",
        _fake,
    )

    r = await client.post(
        "/api/conversational-analytics/conversations",
        json={"project_id": project["id"], "initial_message": "sales"},
        headers=headers,
    )
    conversation = r.json()

    r = await client.get("/api/conversational-anversations/conversations", headers=headers)
    # Intentional misspelling above; the route is /conversational-analytics/conversations
    assert r.status_code == 404

    r = await client.get("/api/conversational-analytics/conversations", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["title"] == "sales"

    r = await client.get(
        f"/api/conversational-analytics/conversations/{conversation['id']}",
        headers=headers,
    )
    assert r.status_code == 200
    detail = r.json()
    assert detail["id"] == conversation["id"]
    assert len(detail["turns"]) == 1


async def test_chart_only_change(client, service_headers, monkeypatch):
    _, _, project, headers = await _setup(client, service_headers, "conv-chart")

    async def _fake(*args, **kwargs):
        return _fake_ask_and_run_core_result(kwargs.get("question", ""))

    monkeypatch.setattr(
        "app.services.conversational_analytics._ask_and_run_core",
        _fake,
    )

    r = await client.post(
        "/api/conversational-analytics/conversations",
        json={"project_id": project["id"], "initial_message": "sales by month"},
        headers=headers,
    )
    conversation = r.json()
    assert conversation["turns"][0]["chart_config"]["type"] == "bar"

    r = await client.post(
        f"/api/conversational-analytics/conversations/{conversation['id']}/turns",
        json={"message": "change it to a line chart"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    turn = r.json()["turn"]
    assert turn["status"] == "success"
    assert turn["intent_type"] == "chart_change"
    assert turn["chart_config"]["type"] == "line"
    assert turn["result"]["columns"] == ["month", "amount"]


async def test_chart_change_via_llm_classifier(client, service_headers, monkeypatch):
    """When the AI classifier is enabled, its structured decision drives the
    chart change — no phrase matching on the platform."""
    _, _, project, headers = await _setup(client, service_headers, "conv-llm")

    async def _fake(*args, **kwargs):
        return _fake_ask_and_run_core_result(kwargs.get("question", ""))

    monkeypatch.setattr(
        "app.services.conversational_analytics._ask_and_run_core",
        _fake,
    )

    r = await client.post(
        "/api/conversational-analytics/conversations",
        json={"project_id": project["id"], "initial_message": "sales by month"},
        headers=headers,
    )
    conversation = r.json()

    from app.services import conversational_analytics as ca

    monkeypatch.setattr(ca.ai_intelligence_client, "is_enabled", lambda: True)

    captured: dict = {}

    async def _fake_classify(**kwargs):
        captured.update(kwargs)
        return {
            "intent": "chart_change",
            "chart": {"type": "pie", "subtype": "donut"},
            "confidence": 0.95,
            "reason": "presentation only",
        }

    monkeypatch.setattr(
        ca.ai_intelligence_client, "classify_conversation_turn", _fake_classify
    )

    r = await client.post(
        f"/api/conversational-analytics/conversations/{conversation['id']}/turns",
        json={"message": "please present that in the ring-style format"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    turn = r.json()["turn"]
    assert turn["intent_type"] == "chart_change"
    assert turn["chart_config"]["type"] == "pie"
    assert turn["chart_config"]["subtype"] == "donut"
    # The classifier received the grounded state, not just the message.
    assert captured["has_prior_result"] is True
    assert captured["result_columns"] == ["month", "amount"]
    assert captured["prior_sql"]


async def test_fallback_chart_change_horizontal_bar(client, service_headers, monkeypatch):
    """Degraded mode (AI off) still handles explicit chart-format phrases."""
    _, _, project, headers = await _setup(client, service_headers, "conv-fb")

    async def _fake(*args, **kwargs):
        return _fake_ask_and_run_core_result(kwargs.get("question", ""))

    monkeypatch.setattr(
        "app.services.conversational_analytics._ask_and_run_core",
        _fake,
    )

    r = await client.post(
        "/api/conversational-analytics/conversations",
        json={"project_id": project["id"], "initial_message": "sales by month"},
        headers=headers,
    )
    conversation = r.json()

    r = await client.post(
        f"/api/conversational-analytics/conversations/{conversation['id']}/turns",
        json={"message": "run this query using horizontal bar format"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    turn = r.json()["turn"]
    assert turn["intent_type"] == "chart_change"
    assert turn["chart_config"]["type"] == "bar"
    assert turn["chart_config"]["subtype"] == "horizontal_bar"


def test_grounded_data_question_rejects_parroted_rewrites():
    from app.services.conversational_analytics import _grounded_data_question

    # A faithful rewrite shares the user's subject words.
    assert (
        _grounded_data_question(
            "Show backup jobs as horizontal", "Count of backup jobs grouped by Result"
        )
        == "Count of backup jobs grouped by Result"
    )
    # A parroted example about a different subject is discarded.
    assert (
        _grounded_data_question(
            "top suppliers by spend", "Count of IT backup jobs grouped by Result"
        )
        is None
    )
    assert _grounded_data_question("anything", None) is None
    assert _grounded_data_question("anything", "   ") is None


def test_strip_model_markup_removes_code_fences():
    from app.routes.ai_proxy import _strip_model_markup

    raw = (
        "To create a donut chart, I'll need to modify the query.\n\n"
        "```sql\nSELECT 1;\n```\n\nLet me know if that helps."
    )
    cleaned = _strip_model_markup(raw)
    assert "```" not in cleaned
    assert "SELECT 1" not in cleaned
    assert "donut chart" in cleaned
    # Unterminated fences are removed too.
    assert "```" not in _strip_model_markup("Here you go:\n```sql\nSELECT 2;")


def test_apply_chart_patch_validates_columns():
    from app.services.conversational_analytics import apply_chart_patch

    config = {"type": "bar", "labelColumn": "month", "valueColumns": ["amount"]}
    result = {"columns": ["month", "amount"]}

    new_config, msg = apply_chart_patch(config, result, {"labelColumn": "region"})
    assert new_config == config
    assert "region" in msg and "not in this result" in msg

    new_config, msg = apply_chart_patch(
        config, result, {"type": "pie", "subtype": "donut"}
    )
    assert new_config["type"] == "pie"
    assert new_config["subtype"] == "donut"
    assert "donut" in msg


def test_apply_chart_patch_type_change_clears_stale_subtype():
    from app.services.conversational_analytics import apply_chart_patch

    config = {
        "type": "bar",
        "subtype": "horizontal_bar",
        "labelColumn": "month",
        "valueColumns": ["amount"],
    }
    result = {"columns": ["month", "amount"]}
    new_config, _ = apply_chart_patch(config, result, {"type": "bar"})
    assert new_config["type"] == "bar"
    assert "subtype" not in new_config


async def test_retry_failed_turn(client, service_headers, monkeypatch):
    _, _, project, headers = await _setup(client, service_headers, "conv-retry")

    async def _fake(*args, **kwargs):
        return _fake_ask_and_run_core_result(kwargs.get("question", ""))

    monkeypatch.setattr(
        "app.services.conversational_analytics._ask_and_run_core",
        _fake,
    )

    r = await client.post(
        "/api/conversational-analytics/conversations",
        json={"project_id": project["id"]},
        headers=headers,
    )
    conversation = r.json()

    r = await client.post(
        f"/api/conversational-analytics/conversations/{conversation['id']}/turns",
        json={"message": "some question"},
        headers=headers,
    )
    turn = r.json()["turn"]

    r = await client.post(
        f"/api/conversational-analytics/conversations/{conversation['id']}/turns/{turn['id']}/retry",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    retry = r.json()["turn"]
    assert retry["id"] == turn["id"]
    assert retry["status"] == "success"


async def test_rename_and_delete_conversation(client, service_headers):
    _, _, project, headers = await _setup(client, service_headers, "conv-crud")

    r = await client.post(
        "/api/conversational-analytics/conversations",
        json={"project_id": project["id"], "title": "Original"},
        headers=headers,
    )
    conversation = r.json()

    r = await client.patch(
        f"/api/conversational-analytics/conversations/{conversation['id']}",
        json={"title": "Renamed"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Renamed"

    r = await client.delete(
        f"/api/conversational-analytics/conversations/{conversation['id']}",
        headers=headers,
    )
    assert r.status_code == 204, r.text

    r = await client.get(
        f"/api/conversational-analytics/conversations/{conversation['id']}",
        headers=headers,
    )
    assert r.status_code == 404


async def test_other_user_cannot_access_conversation(client, service_headers):
    _, _user_a, project_a, headers_a = await _setup(client, service_headers, "conv-a")
    _tenant_b, _user_b, _project_b, headers_b = await _setup(client, service_headers, "conv-b")

    r = await client.post(
        "/api/conversational-analytics/conversations",
        json={"project_id": project_a["id"], "title": "Private"},
        headers=headers_a,
    )
    conversation = r.json()

    r = await client.get(
        f"/api/conversational-analytics/conversations/{conversation['id']}",
        headers=headers_b,
    )
    assert r.status_code == 404


async def test_new_analysis_with_requested_chart_type(client, service_headers, monkeypatch):
    """A brand-new question that names a chart type gets that initial chart."""
    _, _, project, headers = await _setup(client, service_headers, "conv-new-chart")

    async def _fake(*args, **kwargs):
        return _fake_ask_and_run_core_result(kwargs.get("question", ""))

    monkeypatch.setattr(
        "app.services.conversational_analytics._ask_and_run_core",
        _fake,
    )

    from app.services import conversational_analytics as ca

    monkeypatch.setattr(ca.ai_intelligence_client, "is_enabled", lambda: True)

    async def _fake_classify(**kwargs):
        return {
            "intent": "new_analysis",
            "chart": {"type": "bar", "subtype": "horizontal_bar"},
            "confidence": 0.95,
            "reason": "New data question with requested horizontal bar chart.",
        }

    monkeypatch.setattr(
        ca.ai_intelligence_client, "classify_conversation_turn", _fake_classify
    )

    r = await client.post(
        "/api/conversational-analytics/conversations",
        json={"project_id": project["id"], "initial_message": "Run IT backup jobs with a horizontal bar chart"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    turn = r.json()["turns"][0]
    assert turn["status"] == "success"
    assert turn["intent_type"] == "new_analysis"
    assert turn["chart_config"]["type"] == "bar"
    assert turn["chart_config"]["subtype"] == "horizontal_bar"


async def test_new_analysis_when_llm_returns_empty_chart_uses_suggested_viz(client, service_headers, monkeypatch):
    """If the LLM returns new_analysis with an empty chart patch, the platform
    uses the SQL engine's suggested visualization rather than applying a
    hardcoded phrase fallback. The LLM is the sole source of chart intent."""
    _, _, project, headers = await _setup(client, service_headers, "conv-extract")

    async def _fake(*args, **kwargs):
        return _fake_ask_and_run_core_result(kwargs.get("question", ""))

    monkeypatch.setattr(
        "app.services.conversational_analytics._ask_and_run_core",
        _fake,
    )

    from app.services import conversational_analytics as ca

    monkeypatch.setattr(ca.ai_intelligence_client, "is_enabled", lambda: True)

    async def _fake_classify(**kwargs):
        return {
            "intent": "new_analysis",
            "chart": {},
            "data_question": "Show me sales by month",
            "confidence": 0.9,
            "reason": "New data question.",
        }

    monkeypatch.setattr(
        ca.ai_intelligence_client, "classify_conversation_turn", _fake_classify
    )

    r = await client.post(
        "/api/conversational-analytics/conversations",
        json={"project_id": project["id"], "initial_message": "Show me sales by month as a donut chart"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    turn = r.json()["turns"][0]
    assert turn["status"] == "success"
    assert turn["intent_type"] == "new_analysis"
    assert turn["chart_config"]["type"] == "bar"


async def test_fallback_new_analysis_with_chart_type(client, service_headers, monkeypatch):
    """Degraded mode (AI off) also honors a chart type in a new question."""
    _, _, project, headers = await _setup(client, service_headers, "conv-fb-new-chart")

    async def _fake(*args, **kwargs):
        return _fake_ask_and_run_core_result(kwargs.get("question", ""))

    monkeypatch.setattr(
        "app.services.conversational_analytics._ask_and_run_core",
        _fake,
    )

    from app.services import conversational_analytics as ca

    monkeypatch.setattr(ca.ai_intelligence_client, "is_enabled", lambda: False)

    r = await client.post(
        "/api/conversational-analytics/conversations",
        json={"project_id": project["id"], "initial_message": "Show me sales by month as a donut chart"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    turn = r.json()["turns"][0]
    assert turn["status"] == "success"
    assert turn["intent_type"] == "new_analysis"
    assert turn["chart_config"]["type"] == "pie"
    assert turn["chart_config"]["subtype"] == "donut"
