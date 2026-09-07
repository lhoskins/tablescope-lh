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


async def test_investigative_question_runs_multi_step_investigation(
    client, service_headers, monkeypatch
):
    """A root-cause ('why') question runs the investigation agent: targeted
    sub-questions through the existing ask-and-run core, then a synthesized
    answer given the full trail -- not just the last sub-query in isolation."""
    _, _, project, headers = await _setup(client, service_headers, "conv-investigate")

    async def _fake_ask_and_run(session, context, *, project_id, question, **kwargs):
        if "by supplier" in question:
            return {
                "sql": 'SELECT "Supplier", AVG(CAST("DefectRate" AS double)) AS r '
                'FROM "t" GROUP BY "Supplier"',
                "columns": ["Supplier", "r"],
                "rows": [
                    {"Supplier": "Acme", "r": 0.31},
                    {"Supplier": "Globex", "r": 0.05},
                ],
                "suggestedVisualization": {"type": "bar"},
                "explanation": "",
                "dataSourcesUsed": ["t"],
                "status": "success",
                "error": None,
            }
        return _fake_ask_and_run_core_result(question)

    monkeypatch.setattr(
        "app.services.conversational_analytics._ask_and_run_core",
        _fake_ask_and_run,
    )

    from app.services import conversational_analytics as ca

    decisions = iter(
        [
            {"action": "query", "sub_question": "Defect rate by supplier?"},
            {"action": "finish", "sub_question": ""},
        ]
    )
    investigate_calls: list[dict] = []

    async def _fake_investigate_step(**kwargs):
        # Snapshot -- kwargs["steps"] is the live list _run_investigation
        # keeps mutating, so capture a copy or later calls would retroactively
        # change what an earlier call appears to have seen.
        investigate_calls.append({**kwargs, "steps": list(kwargs["steps"])})
        return next(decisions)

    monkeypatch.setattr(
        ca.ai_intelligence_client, "investigate_step", _fake_investigate_step
    )

    synthesize_calls: list[dict] = []

    async def _fake_ask(*, question, **kwargs):
        synthesize_calls.append(kwargs)
        return {
            "answer": "Defect rate is rising because Acme's rate (31%) is far "
            "above Globex's (5%)."
        }

    monkeypatch.setattr(ca.ai_intelligence_client, "ask", _fake_ask)

    r = await client.post(
        "/api/conversational-analytics/conversations",
        json={
            "project_id": project["id"],
            "initial_message": "Why is the defect rate rising?",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    turn = r.json()["turns"][0]
    assert turn["status"] == "success"
    assert "Acme" in turn["assistant_message"]
    assert turn["result"]["columns"] == ["Supplier", "r"]

    # Two planning calls: the first with no evidence yet, the second knowing
    # what the first sub-query found.
    assert len(investigate_calls) == 2
    assert investigate_calls[0]["steps"] == []
    assert investigate_calls[0]["steps_remaining"] == 3
    assert investigate_calls[1]["steps_remaining"] == 2
    assert investigate_calls[1]["steps"][0]["sub_question"] == "Defect rate by supplier?"

    # The synthesizer saw the full investigation trail, not just the final result.
    assert (
        synthesize_calls[0]["data_result"]["steps"][0]["sub_question"]
        == "Defect rate by supplier?"
    )

    # The trace is persisted for audit, not just used transiently.
    steps = turn["result_metadata"]["investigation"]["steps"]
    assert len(steps) == 1
    assert steps[0]["sub_question"] == "Defect rate by supplier?"
    assert steps[0]["row_count"] == 2


async def test_investigative_question_survives_classifier_rewrite(
    client, service_headers, monkeypatch
):
    """The conversation-turn classifier rewrites a 'why' question into a
    focused, presentation-free data_question for SQL generation (e.g. 'why
    is the backup failure rate rising' -> 'backup job failure rate trend
    over time') -- wording that strips the investigative signal. The
    investigation-trigger check, and the question handed to the
    investigation agent's own root-cause planning, must use the user's
    original message, not that rewrite, or a genuine root-cause question
    silently falls back to a single query the classifier itself decided
    needs a rewrite it can't produce."""
    _, _, project, headers = await _setup(client, service_headers, "conv-investigate-rewrite")

    async def _fake_ask_and_run(session, context, *, project_id, question, **kwargs):
        return _fake_ask_and_run_core_result(question)

    monkeypatch.setattr(
        "app.services.conversational_analytics._ask_and_run_core",
        _fake_ask_and_run,
    )

    from app.services import conversational_analytics as ca

    monkeypatch.setattr(ca.ai_intelligence_client, "is_enabled", lambda: True)

    async def _fake_classify(**kwargs):
        return {
            "intent": "query_change",
            "confidence": 0.78,
            "reason": "requires a time-based trend rather than the current single aggregate",
            "data_question": "backup job failure rate trend over time",
        }

    monkeypatch.setattr(
        ca.ai_intelligence_client, "classify_conversation_turn", _fake_classify
    )

    investigate_calls: list[dict] = []

    async def _fake_investigate_step(**kwargs):
        investigate_calls.append(kwargs)
        return {"action": "finish", "sub_question": ""}

    monkeypatch.setattr(
        ca.ai_intelligence_client, "investigate_step", _fake_investigate_step
    )

    r = await client.post(
        "/api/conversational-analytics/conversations",
        json={
            "project_id": project["id"],
            "initial_message": "Why is the backup job failure rate rising?",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["turns"][0]["status"] == "success"

    # The investigation agent ran at all (the rewrite alone must not skip it)...
    assert len(investigate_calls) == 1
    # ...and it planned against the user's actual "why" question, not the
    # classifier's trend-phrased data_question.
    assert investigate_calls[0]["question"] == "Why is the backup job failure rate rising?"


async def test_investigative_question_survives_explain_misclassification(
    client, service_headers, monkeypatch
):
    """As a follow-up turn (a prior successful result already exists), the
    conversation-turn classifier can read a 'why' question as a request to
    explain that prior result rather than a root-cause question -- the
    presence of a prior result nudges it toward EXPLAIN. The EXPLAIN branch
    returns immediately with the prior turn's SQL/result, before the
    investigation-trigger check further down ever runs, so left uncorrected
    this silently skips the investigation agent on every such follow-up."""
    _, _, project, headers = await _setup(client, service_headers, "conv-investigate-explain")

    async def _fake_ask_and_run(session, context, *, project_id, question, **kwargs):
        return _fake_ask_and_run_core_result(question)

    monkeypatch.setattr(
        "app.services.conversational_analytics._ask_and_run_core",
        _fake_ask_and_run,
    )

    from app.services import conversational_analytics as ca

    monkeypatch.setattr(ca.ai_intelligence_client, "is_enabled", lambda: True)

    r = await client.post(
        "/api/conversational-analytics/conversations",
        json={"project_id": project["id"], "initial_message": "backup failure rate"},
        headers=headers,
    )
    conversation = r.json()

    async def _fake_classify(**kwargs):
        return {
            "intent": "explain",
            "confidence": 0.85,
            "reason": "User asks why the failure rate is rising, requesting "
            "explanation of the current result.",
        }

    monkeypatch.setattr(
        ca.ai_intelligence_client, "classify_conversation_turn", _fake_classify
    )

    investigate_calls: list[dict] = []

    async def _fake_investigate_step(**kwargs):
        investigate_calls.append(kwargs)
        return {"action": "finish", "sub_question": ""}

    monkeypatch.setattr(
        ca.ai_intelligence_client, "investigate_step", _fake_investigate_step
    )

    r = await client.post(
        f"/api/conversational-analytics/conversations/{conversation['id']}/turns",
        json={"message": "Why is the backup job failure rate rising?"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    turn = r.json()["turn"]
    assert turn["status"] == "success"

    # The investigation agent ran instead of the turn short-circuiting into
    # a canned "this result came from SQL X" explanation of the prior turn.
    assert len(investigate_calls) == 1
    assert investigate_calls[0]["question"] == "Why is the backup job failure rate rising?"
    assert turn["intent_type"] == "new_analysis"


async def test_investigative_question_falls_back_to_single_query_when_agent_declines(
    client, service_headers, monkeypatch
):
    """If the investigation agent has nothing useful to add and declines on
    its very first decision, the turn must still succeed via the normal
    single-query path -- an investigative-sounding question is never worse
    off than the standard path."""
    _, _, project, headers = await _setup(client, service_headers, "conv-investigate-decline")

    async def _fake_ask_and_run(session, context, *, project_id, question, **kwargs):
        return _fake_ask_and_run_core_result(question)

    monkeypatch.setattr(
        "app.services.conversational_analytics._ask_and_run_core",
        _fake_ask_and_run,
    )

    from app.services import conversational_analytics as ca

    async def _fake_investigate_step(**kwargs):
        return {"action": "finish", "sub_question": ""}

    monkeypatch.setattr(
        ca.ai_intelligence_client, "investigate_step", _fake_investigate_step
    )

    r = await client.post(
        "/api/conversational-analytics/conversations",
        json={
            "project_id": project["id"],
            "initial_message": "Why is the defect rate rising?",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    turn = r.json()["turns"][0]
    assert turn["status"] == "success"
    assert turn["result"]["columns"] == ["month", "amount"]
    # No investigation actually ran, so no trace is attached.
    assert (turn["result_metadata"] or {}).get("investigation") is None


async def test_plain_question_never_triggers_the_investigation_agent(
    client, service_headers, monkeypatch
):
    """A plain factual question must never pay for the investigation
    decision call -- only a genuine root-cause question does."""
    _, _, project, headers = await _setup(client, service_headers, "conv-no-investigate")

    async def _fake_ask_and_run(session, context, *, project_id, question, **kwargs):
        return _fake_ask_and_run_core_result(question)

    monkeypatch.setattr(
        "app.services.conversational_analytics._ask_and_run_core",
        _fake_ask_and_run,
    )

    from app.services import conversational_analytics as ca

    async def _fail_if_called(**kwargs):
        raise AssertionError("investigate_step must not run for a plain factual question")

    monkeypatch.setattr(
        ca.ai_intelligence_client, "investigate_step", _fail_if_called
    )

    r = await client.post(
        "/api/conversational-analytics/conversations",
        json={
            "project_id": project["id"],
            "initial_message": "What is total revenue this quarter?",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["turns"][0]["status"] == "success"


async def test_generation_error_reports_the_real_reason_not_a_matched_card(
    client, db_session, service_headers, monkeypatch
):
    """A question the fresh SQL path can't answer must surface *why* --
    not stand in an unrelated but topically-similar Insight Card and mark
    the turn a success. Matching a card here made a failed live query look
    like a working answer, and hid the real reason the user asked for."""
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
        return {
            "status": "generation_error",
            "sql": "",
            "error": "Model did not return a runnable SQL query.",
            "errorDetails": {"validationError": "empty completion"},
        }

    async def _fail_if_called(*args, **kwargs):
        raise AssertionError(
            "insight-card and prose fallback must not run for a generation_error -- "
            "the real reason must be reported instead of a substitute answer"
        )

    monkeypatch.setattr(
        "app.services.conversational_analytics._ask_and_run_core",
        _fake_generation_error,
    )
    monkeypatch.setattr(
        "app.services.conversational_analytics._forward_prose_answer",
        _fail_if_called,
    )
    monkeypatch.setattr(
        "app.services.conversational_analytics.find_matching_insight_cards",
        _fail_if_called,
    )

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
    assert turn["status"] == "error"
    assert turn["matched_insight"] is None
    assert turn["assistant_message"] == "Model did not return a runnable SQL query."
    assert turn["sql"] is None
    assert turn["chart_config"] is None
    assert turn["error_code"] == "generation_error"
    assert turn["result_metadata"]["errorDetails"] == {"validationError": "empty completion"}


async def test_ai_unavailable_hard_errors_instead_of_matching_an_insight_card(
    client, db_session, service_headers, monkeypatch
):
    """An AI-server outage must surface as a plain error, never a matched
    Insight Card standing in for it.

    Previously any generation/execution failure -- including the AI service
    itself being unreachable -- fell back to a matched Insight Card and
    returned status="success", making an outage look identical to a working
    (if unrelated) answer. _ask_and_run_core now returns a distinct
    "ai_unavailable" status for exactly this case, and execute_turn must
    short-circuit to a hard error before ever calling the insight-card
    matcher, rather than silently degrading."""
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
            "status": "ai_unavailable",
            "sql": "",
            "error": "The AI service is currently unavailable. Please try again shortly.",
            "errorDetails": {"aiError": "AI server is unavailable; retry shortly."},
        }

    async def _fake_select(**kwargs):
        raise AssertionError(
            "insight-card matching must not run when the AI is unavailable"
        )

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
    assert turn["status"] == "error"
    assert turn["matched_insight"] is None
    assert "unavailable" in turn["assistant_message"].lower()


async def test_document_question_hard_errors_when_ai_is_unavailable(
    client, service_headers, monkeypatch
):
    """The document-Q&A path bypasses SQL generation entirely, but it must
    apply the same rule: an AI outage is a hard error, not a "no relevant
    document found" success -- those read identically to the user otherwise,
    hiding a real outage behind what looks like a completed (empty) search.
    """
    _, _, project, headers = await _setup(client, service_headers, "conv-doc-ai-down")

    async def _fake_ai_unavailable(*args, **kwargs):
        return {"ai_unavailable": True}

    monkeypatch.setattr(
        "app.services.conversational_analytics._forward_prose_answer",
        _fake_ai_unavailable,
    )

    r = await client.post(
        "/api/conversational-analytics/conversations",
        json={
            "project_id": project["id"],
            "initial_message": "Show me our compliance documents",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    turn = r.json()["turns"][0]
    assert turn["status"] == "error"
    assert "unavailable" in turn["assistant_message"].lower()
    assert "couldn't find a relevant document" not in turn["assistant_message"].lower()


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


async def test_create_query_intent_returns_confirmation_then_saves_once(
    client, service_headers, monkeypatch
):
    """A chat command proposes an executed query but does not persist it
    until the editor explicitly accepts the confirmation card."""
    _, _, project, headers = await _setup(client, service_headers, "conv-query-artifact")

    async def _fake(*args, **kwargs):
        return _fake_ask_and_run_core_result(kwargs.get("question", "sales"))

    monkeypatch.setattr(
        "app.services.conversational_analytics._ask_and_run_core",
        _fake,
    )

    created = await client.post(
        "/api/conversational-analytics/conversations",
        json={
            "project_id": project["id"],
            "initial_message": "Create a query showing sales by month",
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    conversation = created.json()
    turn = conversation["turns"][0]
    assert turn["intent_type"] == "create_query"
    assert turn["artifact_proposal"]["kind"] == "query"
    assert turn["artifact_proposal"]["status"] == "pending"
    assert turn["artifact_proposal"]["assetId"] is None

    before = await client.get(
        f"/api/projects/{project['id']}/queries", headers=headers
    )
    assert before.status_code == 200
    assert before.json() == []

    decision_url = (
        f"/api/conversational-analytics/conversations/{conversation['id']}"
        f"/turns/{turn['id']}/artifact-decision"
    )
    accepted = await client.post(
        decision_url,
        json={"decision": "accept", "artifact_kind": "query"},
        headers=headers,
    )
    assert accepted.status_code == 200, accepted.text
    proposal = accepted.json()["turn"]["artifact_proposal"]
    assert proposal["status"] == "accepted"
    assert proposal["assetId"] is not None
    assert proposal["assetUrl"] == f"/projects/{project['id']}/queries"

    # Confirmation is idempotent; a double click/retry cannot duplicate it.
    accepted_again = await client.post(
        decision_url,
        json={"decision": "accept", "artifact_kind": "query"},
        headers=headers,
    )
    assert accepted_again.status_code == 200
    assert (
        accepted_again.json()["turn"]["artifact_proposal"]["assetId"]
        == proposal["assetId"]
    )
    after = await client.get(
        f"/api/projects/{project['id']}/queries", headers=headers
    )
    assert after.status_code == 200
    assert len(after.json()) == 1


async def test_create_dashboard_intent_is_non_destructive_until_review(
    client, service_headers, monkeypatch
):
    """Chat persists only a dashboard proposal; the existing designer owns
    review, query validation, preview and final creation."""
    _, _, project, headers = await _setup(client, service_headers, "conv-dashboard-artifact")
    analytical_calls = 0

    async def _must_not_run(*args, **kwargs):
        nonlocal analytical_calls
        analytical_calls += 1
        return _fake_ask_and_run_core_result(kwargs.get("question", ""))

    monkeypatch.setattr(
        "app.services.conversational_analytics._ask_and_run_core",
        _must_not_run,
    )

    created = await client.post(
        "/api/conversational-analytics/conversations",
        json={
            "project_id": project["id"],
            "initial_message": "Please create a dashboard for revenue and backlog trends",
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    conversation = created.json()
    turn = conversation["turns"][0]
    assert analytical_calls == 0
    assert turn["intent_type"] == "create_dashboard"
    assert turn["result"] is None
    assert turn["artifact_proposal"]["kind"] == "dashboard"
    assert turn["artifact_proposal"]["status"] == "pending"

    rejected = await client.post(
        (
            f"/api/conversational-analytics/conversations/{conversation['id']}"
            f"/turns/{turn['id']}/artifact-decision"
        ),
        json={"decision": "reject", "artifact_kind": "dashboard"},
        headers=headers,
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["turn"]["artifact_proposal"]["status"] == "rejected"


async def test_accept_dashboard_proposal_records_the_designer_created_dashboard(
    client, db_session, service_headers, monkeypatch
):
    """Dashboard acceptance never builds a dashboard itself -- it only
    records the id the existing (separately governed) designer already
    created, and rejects an id from another project."""
    from app.models.dashboard import Dashboard

    tenant, _, project, headers = await _setup(client, service_headers, "conv-dashboard-accept")

    async def _must_not_run(*args, **kwargs):
        raise AssertionError("dashboard proposals must not trigger SQL generation")

    monkeypatch.setattr(
        "app.services.conversational_analytics._ask_and_run_core",
        _must_not_run,
    )

    created = await client.post(
        "/api/conversational-analytics/conversations",
        json={
            "project_id": project["id"],
            "initial_message": "Please build a dashboard for revenue trends",
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    conversation = created.json()
    turn = conversation["turns"][0]
    decision_url = (
        f"/api/conversational-analytics/conversations/{conversation['id']}"
        f"/turns/{turn['id']}/artifact-decision"
    )

    other_r = await client.post(
        "/api/projects",
        json={"name": "Other Project", "description": "x", "is_shared": False},
        headers=headers,
    )
    assert other_r.status_code == 201
    other_project = other_r.json()
    other_dashboard = Dashboard(
        project_id=other_project["id"],
        tenant_id=tenant["id"],
        name="Wrong project dashboard",
    )
    db_session.add(other_dashboard)
    await db_session.commit()
    await db_session.refresh(other_dashboard)

    wrong_project = await client.post(
        decision_url,
        json={"decision": "accept", "artifact_kind": "dashboard", "asset_id": other_dashboard.id},
        headers=headers,
    )
    assert wrong_project.status_code == 404

    dashboard = Dashboard(
        project_id=project["id"],
        tenant_id=tenant["id"],
        name="Revenue trends",
    )
    db_session.add(dashboard)
    await db_session.commit()
    await db_session.refresh(dashboard)

    accepted = await client.post(
        decision_url,
        json={"decision": "accept", "artifact_kind": "dashboard", "asset_id": dashboard.id},
        headers=headers,
    )
    assert accepted.status_code == 200, accepted.text
    proposal = accepted.json()["turn"]["artifact_proposal"]
    assert proposal["status"] == "accepted"
    assert proposal["assetId"] == dashboard.id
    assert proposal["assetUrl"] == f"/projects/{project['id']}/dashboards/{dashboard.id}"


async def test_artifact_decision_rejects_kind_mismatch_and_missing_turn(
    client, service_headers, monkeypatch
):
    """Deciding with the wrong `artifact_kind` (or on a turn with no
    proposal at all) must be rejected, not silently accepted against the
    wrong proposal or a no-op."""
    _, _, project, headers = await _setup(client, service_headers, "conv-kind-mismatch")

    async def _fake(*args, **kwargs):
        return _fake_ask_and_run_core_result(kwargs.get("question", "sales"))

    monkeypatch.setattr(
        "app.services.conversational_analytics._ask_and_run_core",
        _fake,
    )

    created = await client.post(
        "/api/conversational-analytics/conversations",
        json={
            "project_id": project["id"],
            "initial_message": "Create a query showing sales by month",
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    conversation = created.json()
    turn = conversation["turns"][0]
    assert turn["artifact_proposal"]["kind"] == "query"

    mismatched = await client.post(
        (
            f"/api/conversational-analytics/conversations/{conversation['id']}"
            f"/turns/{turn['id']}/artifact-decision"
        ),
        json={"decision": "accept", "artifact_kind": "dashboard"},
        headers=headers,
    )
    assert mismatched.status_code == 409

    missing_turn = await client.post(
        (
            f"/api/conversational-analytics/conversations/{conversation['id']}"
            f"/turns/999999/artifact-decision"
        ),
        json={"decision": "accept", "artifact_kind": "query"},
        headers=headers,
    )
    assert missing_turn.status_code == 404


async def test_save_this_result_as_query_reuses_prior_validated_sql(
    client, service_headers, monkeypatch
):
    """"Save this as a query" must reuse the immediately preceding turn's
    already-executed SQL/result rather than asking the model to regenerate
    a query that could legitimately come back different."""
    _, _, project, headers = await _setup(client, service_headers, "conv-save-existing")

    calls: list[str] = []

    async def _fake(*args, **kwargs):
        question = kwargs.get("question", "")
        calls.append(question)
        return _fake_ask_and_run_core_result(question)

    monkeypatch.setattr(
        "app.services.conversational_analytics._ask_and_run_core",
        _fake,
    )

    created = await client.post(
        "/api/conversational-analytics/conversations",
        json={
            "project_id": project["id"],
            "initial_message": "Show sales by month",
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    conversation = created.json()
    first_turn = conversation["turns"][0]
    assert first_turn["artifact_proposal"] is None
    calls_after_first = len(calls)

    followup = await client.post(
        f"/api/conversational-analytics/conversations/{conversation['id']}/turns",
        json={"message": "Save this result as a query"},
        headers=headers,
    )
    assert followup.status_code == 200, followup.text
    second_turn = followup.json()["turn"]

    # The reuse path must not call the SQL generator a second time -- it
    # would defeat the entire point of "save THIS result" if the SQL could
    # silently differ from what the user just reviewed.
    assert len(calls) == calls_after_first
    assert second_turn["artifact_proposal"]["kind"] == "query"
    assert second_turn["artifact_proposal"]["status"] == "pending"
    assert second_turn["result"]["rows"] == first_turn["result"]["rows"]


def test_save_as_commands_recognize_demonstrative_plus_noun_phrasing() -> None:
    """"save this AS a query" and "the result" were both already recognized;
    "this result"/"that analysis" (demonstrative + noun together) was not,
    even though it is at least as natural a way to phrase the same request."""
    from app.services.conversational_analytics.intent_classification import (
        ConversationalIntent,
        artifact_intent,
        is_save_existing_query_request,
    )

    for phrase in (
        "Save this as a query",
        "Save this result as a query",
        "Save that analysis as a query",
        "Save the sql as a query",
        "Turn this result into a query",
    ):
        assert artifact_intent(phrase) == ConversationalIntent.CREATE_QUERY, phrase
        assert is_save_existing_query_request(phrase), phrase

    for phrase in (
        "Save this result as a dashboard",
        "Turn that analysis into a dashboard",
        "Add this to a dashboard",
    ):
        assert artifact_intent(phrase) == ConversationalIntent.CREATE_DASHBOARD, phrase
