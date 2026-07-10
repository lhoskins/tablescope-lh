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
from app.routes.ai_proxy import (
    _ai_generation_error,
    _apply_row_limit,
    _ask_data_first,
    _is_read_only_select,
    _requested_chart,
    _shield_prose_from_sql,
    _suggest_visualization,
)
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


# ── Requested chart type ──────────────────────────────────────────────────


def test_requested_chart_extracts_horizontal_bar():
    assert (
        _requested_chart("incident category and count as a horizontal bar chart")
        == "horizontal_bar"
    )


def test_requested_chart_extracts_donut():
    assert _requested_chart("show a donut of spend by vendor") == "donut"


def test_requested_chart_none_when_unspecified():
    assert _requested_chart("how many incidents by category") is None
    assert _requested_chart(None) is None


def test_suggest_visualization_honors_horizontal_bar_style():
    viz = _suggest_visualization(
        ["category", "count"],
        [{"category": "A", "count": 3}, {"category": "B", "count": 5}],
        "incident count by category as a horizontal bar chart",
    )
    assert viz["type"] == "bar"
    assert viz["style"] == "horizontal_bar"
    assert viz["xField"] == "category"
    assert viz["yField"] == "count"


def test_suggest_visualization_ignores_shape_invalid_donut_request():
    # A donut over many categories is shape-invalid; the engine corrects to a
    # ranking bar and the donut style is not applied.
    rows = [{"category": f"C{i}", "count": i + 1} for i in range(40)]
    viz = _suggest_visualization(["category", "count"], rows, "show a donut")
    assert viz["type"] == "bar"
    assert viz.get("style") != "donut"


# ── Prose SQL shield ──────────────────────────────────────────────────────


def test_shield_prose_from_sql_replaces_sql_fenced_answer():
    out = _shield_prose_from_sql("```sql\nSELECT * FROM incidents\n```")
    assert "SELECT" not in out
    assert "rephrasing" in out.lower()


def test_shield_prose_from_sql_replaces_leading_select():
    out = _shield_prose_from_sql("SELECT category, count(*) FROM incidents")
    assert "SELECT" not in out


def test_shield_prose_from_sql_passes_ordinary_prose_through():
    prose = "The safety policy requires quarterly audits per document Policy-12."
    assert _shield_prose_from_sql(prose) == prose


async def test_ask_data_first_returns_structured_for_zero_row_success(monkeypatch):
    async def fake_core(*args, **kwargs):
        return {
            "status": "success",
            "sql": "SELECT category FROM incidents WHERE 1=0",
            "columns": ["category"],
            "rows": [],
            "presentation": {"mode": "data"},
            "envelope": {"mode": "data"},
        }

    monkeypatch.setattr(ai_proxy, "_ask_and_run_core", fake_core)
    out = await _ask_data_first(
        None, None, project_id=1, question="incidents last month"
    )
    assert out is not None
    assert out["model_used"] == "tablescope-data"


# ── Endpoint behaviour ────────────────────────────────────────────────────

async def test_ask_and_run_success(client, service_headers, monkeypatch):
    _, _, project, headers = await _setup(client, service_headers, "askok")

    async def fake_generate(session, context, project_id, question, **kwargs):
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

    async def fake_generate(session, context, project_id, question, **kwargs):
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
    # Friendly user-facing message; raw detail only in expandable details.
    assert body["error"] == "We could not safely build a query for this question."
    assert "unreachable" in body["errorDetails"]["validationError"]
    assert body["sql"] == ""


async def test_ask_and_run_falls_back_to_prose_when_no_source(
    client, service_headers, monkeypatch
):
    # Analytical/document questions that don't map to a single SQL source
    # (generation_error) fall back to the documents/knowledge-graph prose answer
    # instead of showing a "couldn't match a source" error.
    _, _, project, headers = await _setup(client, service_headers, "askprose")

    async def fake_generate(session, context, project_id, question, **kwargs):
        raise HTTPException(
            status_code=422,
            detail="Could not match part of your request to an authorized "
            "project source",
        )

    async def fake_forward(path, payload):
        assert path == "/ai/ask"
        return {"answer": "Late deliveries stem from port congestion..."}

    monkeypatch.setattr(ai_proxy, "_generate_sql_for_question", fake_generate)
    monkeypatch.setattr(ai_proxy, "_forward_to_ai", fake_forward)

    r = await client.post(
        "/api/ai/actions/ask-and-run",
        json={
            "project_id": project["id"],
            "question": "What are the key factors contributing to late "
            "deliveries?",
        },
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success"
    assert body["answerType"] == "text"
    assert "port congestion" in body["explanation"]
    assert body["sql"] == ""
    assert body["rows"] == []
    # A prose fallback presents as the conversational mode (no forced chart).
    assert body["presentation"]["mode"] == "conversational"
    assert "chart" not in body["presentation"]["sections"]
    # Envelope: prose maps `explanation` -> `answer`, carries no chart/columns.
    env = body["envelope"]
    assert env["mode"] == "conversational"
    assert env["answer"] == body["explanation"]
    assert "summary" not in env
    assert "chart" not in env
    assert "columns" not in env


async def test_ask_and_run_success_attaches_intent_metadata(
    client, service_headers, monkeypatch
):
    """The declared Intent Engine hint rides along as ``intent`` metadata."""
    _, _, project, headers = await _setup(client, service_headers, "askintent")

    async def fake_generate(session, context, project_id, question, **kwargs):
        return {"sql": "SELECT supplier, defects FROM q", "explanation": ""}

    async def fake_execute(session, context, project_id, sql):
        return {
            "columns": ["supplier", "defects"],
            "rows": [{"supplier": "A", "defects": 3}],
        }

    monkeypatch.setattr(ai_proxy, "_generate_sql_for_question", fake_generate)
    monkeypatch.setattr(ai_proxy, "_execute_project_sql", fake_execute)

    r = await client.post(
        "/api/ai/actions/ask-and-run",
        json={"project_id": project["id"], "question": "total defects by supplier?"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    intent = body["intent"]
    assert intent["responseMode"] == "structured_data"
    assert intent["requiresSql"] is True
    assert 0.0 <= intent["confidence"] <= 1.0
    # Shared presentation descriptor (M4): an executed result is `structured`.
    assert body["presentation"]["mode"] == "structured"
    assert "chart" in body["presentation"]["sections"]
    assert "show_sql" in body["presentation"]["sections"]
    # M4 fast-follow pilot: the surface emits a unified ResponseEnvelope.
    env = body["envelope"]
    assert env["mode"] == "structured"
    assert env["sections"] == body["presentation"]["sections"]
    assert env["sql"] == body["sql"]
    assert env["columns"] == body["columns"]
    assert env["rows"] == body["rows"]
    assert env["chart"] == body["suggestedVisualization"]
    assert env["intent"] == body["intent"]
    # A structured result is not prose — no `answer` field.
    assert "answer" not in env


def test_build_ask_and_run_envelope_hybrid_maps_executive_summary():
    """Hybrid: the prose becomes the executive summary and the method envelope
    + drivers ride the unified contract (M4 fast-follow mapping)."""
    from app.services.presentation_engine import PresentationMode

    response = {
        "status": "success",
        "explanation": "Late shipments concentrate in two carriers.",
        "sql": "SELECT carrier, late FROM q",
        "columns": ["carrier", "late"],
        "rows": [{"carrier": "A", "late": 9}],
        "suggestedVisualization": {"type": "bar"},
        "analyticalMethod": {"method": "neg_binomial", "n": 42},
        "dataSourcesUsed": ["shipments"],
        "intent": {"responseMode": "structured_data"},
    }
    env = ai_proxy._build_ask_and_run_envelope(
        response, PresentationMode.HYBRID
    )
    assert env["mode"] == "hybrid"
    assert "method_envelope" in env["sections"]
    assert env["executive_summary"] == response["explanation"]
    assert env["summary"] == response["explanation"]
    assert env["method_envelope"] == response["analyticalMethod"]
    assert env["sources"] == ["shipments"]
    # Hybrid is data-backed, not a prose answer.
    assert "answer" not in env


async def test_intent_classification_never_forces_hard_failure(
    client, service_headers, monkeypatch
):
    """Hard constraint (ASK §5 / plan §6.3): a ``structured_data`` classification
    that hits resolver ``no_match`` (generation_error) must still fall back to
    prose, never a hard failure — a misclassification can only degrade safely."""
    from app.services.intent_engine import ResponseMode, classify_intent

    _, _, project, headers = await _setup(client, service_headers, "askhard")

    question = "How many late shipments per supplier last quarter?"
    # Pre-condition: this question is genuinely classified data-first.
    assert classify_intent(question).response_mode is ResponseMode.STRUCTURED_DATA

    async def fake_generate(session, context, project_id, question, **kwargs):
        raise HTTPException(
            status_code=422,
            detail="Could not match part of your request to an authorized "
            "project source",
        )

    async def fake_forward(path, payload):
        return {"answer": "Late shipments cluster around two carriers..."}

    monkeypatch.setattr(ai_proxy, "_generate_sql_for_question", fake_generate)
    monkeypatch.setattr(ai_proxy, "_forward_to_ai", fake_forward)

    r = await client.post(
        "/api/ai/actions/ask-and-run",
        json={"project_id": project["id"], "question": question},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    # Despite the data-first classification, no source -> safe prose fallback.
    assert body["status"] == "success"
    assert body["answerType"] == "text"
    assert "carriers" in body["explanation"]


async def test_ask_and_run_execution_error_reveals_sql(
    client, service_headers, monkeypatch
):
    _, _, project, headers = await _setup(client, service_headers, "askexec")

    async def fake_generate(session, context, project_id, question, **kwargs):
        return {"sql": "SELECT * FROM broken", "explanation": ""}

    async def fake_execute(session, context, project_id, sql):
        raise HTTPException(status_code=502, detail="Query failed: bad column")

    async def fake_fix(**kwargs):
        return None  # repair declines -> honest execution error

    import app.services.ai_intelligence_client as aic

    monkeypatch.setattr(ai_proxy, "_generate_sql_for_question", fake_generate)
    monkeypatch.setattr(ai_proxy, "_execute_project_sql", fake_execute)
    monkeypatch.setattr(aic, "fix_sql", fake_fix)

    r = await client.post(
        "/api/ai/actions/ask-and-run",
        json={"project_id": project["id"], "question": "x?"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "execution_error"
    assert body["sql"] == "SELECT * FROM broken"
    assert body["error"] == (
        "We could not run this query against the project's data."
    )
    assert "bad column" in body["errorDetails"]["executionError"]
    assert body["errorDetails"]["sql"] == "SELECT * FROM broken"


async def test_ask_and_run_repairs_execution_error_then_succeeds(
    client, service_headers, monkeypatch
):
    """A Teiid error (e.g. DATEDIFF) is fed back to the AI and the repaired
    SQL re-runs successfully — the same self-heal the dashboard path uses."""
    _, _, project, headers = await _setup(client, service_headers, "askfix")

    bad = "SELECT AVG(DATEDIFF(DeliveryDate, ShipDate)) AS x FROM LOG_Shipments_CSV"
    good = (
        "SELECT AVG(TIMESTAMPDIFF(SQL_TSI_DAY, CAST(ShipDate AS timestamp), "
        "CAST(DeliveryDate AS timestamp))) AS x FROM LOG_Shipments_CSV"
    )

    async def fake_generate(session, context, project_id, question, **kwargs):
        return {"sql": bad, "explanation": ""}

    calls = {"n": 0}

    async def fake_execute(session, context, project_id, sql):
        calls["n"] += 1
        if "DATEDIFF" in sql:
            raise HTTPException(
                status_code=502,
                detail="TEIID30068 The function 'DATEDIFF' is an unknown form.",
            )
        return {"columns": ["x"], "rows": [{"x": 5}]}

    async def fake_fix(**kwargs):
        assert "DATEDIFF" in kwargs["error"]
        return good

    import app.services.ai_intelligence_client as aic

    monkeypatch.setattr(ai_proxy, "_generate_sql_for_question", fake_generate)
    monkeypatch.setattr(ai_proxy, "_execute_project_sql", fake_execute)
    monkeypatch.setattr(aic, "fix_sql", fake_fix)

    r = await client.post(
        "/api/ai/actions/ask-and-run",
        json={"project_id": project["id"], "question": "avg days late?"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success"
    assert "TIMESTAMPDIFF" in body["sql"]
    assert "DATEDIFF" not in body["sql"]
    assert body["rows"] == [{"x": 5}]
    assert calls["n"] == 2  # failed once, succeeded after repair


async def test_ask_and_run_blocks_prose_before_execution(
    client, service_headers, monkeypatch
):
    """Prose returned as SQL must never reach Teiid — return a clean error."""
    _, _, project, headers = await _setup(client, service_headers, "askprose")

    async def fake_generate(session, context, project_id, question, **kwargs):
        return {
            "sql": "To calculate the defect rate we group by supplier.",
            "explanation": "",
        }

    executed: list[str] = []

    async def fake_execute(session, context, project_id, sql):
        executed.append(sql)
        return {"columns": [], "rows": []}

    monkeypatch.setattr(ai_proxy, "_generate_sql_for_question", fake_generate)
    monkeypatch.setattr(ai_proxy, "_execute_project_sql", fake_execute)

    r = await client.post(
        "/api/ai/actions/ask-and-run",
        json={"project_id": project["id"], "question": "x?"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "generation_error"
    assert executed == []  # prose was never executed
    assert body["error"] == "We could not safely build a query for this question."


async def test_ask_and_run_clarification_surfaces_matched_sources(
    client, service_headers, monkeypatch
):
    """AI-server 422 clarification maps to a friendly message + matched sources."""
    _, _, project, headers = await _setup(client, service_headers, "askclar")

    async def fake_generate(session, context, project_id, question, **kwargs):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "needs_clarification",
                "message": (
                    "Could not match part of your request to an authorized "
                    "project source."
                ),
                "reason": "Unauthorized table reference: Sales",
                "suggested_sources": ["SUP_Suppliers_CSV", "LOG_Shipments_CSV"],
            },
        )

    monkeypatch.setattr(ai_proxy, "_generate_sql_for_question", fake_generate)

    r = await client.post(
        "/api/ai/actions/ask-and-run",
        json={"project_id": project["id"], "question": "sales?"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "generation_error"
    assert "authorized project source" in body["error"]
    assert body["errorDetails"]["matchedSources"] == [
        "SUP_Suppliers_CSV",
        "LOG_Shipments_CSV",
    ]
    assert "Sales" in body["errorDetails"]["validationError"]


async def test_ask_and_run_auto_selects_top_source(
    client, service_headers, monkeypatch
):
    """The resolver auto-picks one source and ask-and-run runs it — no prompt.

    Even when several sources score closely the resolver returns a single
    ``resolved`` source; ask-and-run proceeds to generation with that source's
    ``preferred_sources`` and never asks the user to choose.
    """
    _, _, project, headers = await _setup(client, service_headers, "askamb")

    from app.services.project_source_resolver import (
        ResolverCandidate,
        ResolverResult,
    )

    passed_preferred: list[str] = []

    async def fake_resolve(session, context, **kwargs):
        return ResolverResult(
            status="resolved",
            preferred_sources=["SUP_A_CSV"],
            relevant_columns=["SupplierID"],
            candidates=[
                ResolverCandidate("SUP_A_CSV", 45.0, ["SupplierID"], "entity"),
                ResolverCandidate("SUP_B_CSV", 44.0, ["SupplierID"], "entity"),
            ],
        )

    async def fake_generate(session, context, project_id, question, **kwargs):
        passed_preferred.extend(kwargs.get("preferred_sources") or [])
        return {"sql": "SELECT supplier FROM q", "explanation": ""}

    async def fake_execute(session, context, project_id, sql):
        return {"columns": ["supplier"], "rows": [{"supplier": "A"}]}

    monkeypatch.setattr(ai_proxy, "_resolve_action_sources", fake_resolve)
    monkeypatch.setattr(ai_proxy, "_generate_sql_for_question", fake_generate)
    monkeypatch.setattr(ai_proxy, "_execute_project_sql", fake_execute)

    r = await client.post(
        "/api/ai/actions/ask-and-run",
        json={"project_id": project["id"], "question": "suppliers?"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] != "needs_clarification"
    assert body["status"] == "success"
    assert passed_preferred == ["SUP_A_CSV"]  # auto-selected top source


async def test_ask_and_run_passes_preferred_sources_to_generator(
    client, service_headers, monkeypatch
):
    """A resolved source + columns are forwarded to SQL generation."""
    _, _, project, headers = await _setup(client, service_headers, "askpref")

    from app.services.project_source_resolver import ResolverResult

    async def fake_resolve(session, context, **kwargs):
        return ResolverResult(
            status="resolved",
            preferred_sources=["SUP_Quality_Inspections_CSV"],
            relevant_columns=["SupplierID", "DefectRate"],
            confidence=0.9,
        )

    seen: dict = {}

    async def fake_generate(session, context, project_id, question, **kwargs):
        seen.update(kwargs)
        return {"sql": "SELECT SupplierID, DefectRate FROM q", "explanation": ""}

    async def fake_execute(session, context, project_id, sql):
        return {"columns": ["SupplierID"], "rows": []}

    monkeypatch.setattr(ai_proxy, "_resolve_action_sources", fake_resolve)
    monkeypatch.setattr(ai_proxy, "_generate_sql_for_question", fake_generate)
    monkeypatch.setattr(ai_proxy, "_execute_project_sql", fake_execute)

    r = await client.post(
        "/api/ai/actions/ask-and-run",
        json={"project_id": project["id"], "question": "defect rate?"},
        headers=headers,
    )
    assert r.status_code == 200
    assert seen["preferred_sources"] == ["SUP_Quality_Inspections_CSV"]
    assert seen["relevant_columns"] == ["SupplierID", "DefectRate"]


def test_is_read_only_select_accepts_select_with_and_comments():
    assert _is_read_only_select("SELECT a FROM t")
    assert _is_read_only_select("  with cte as (select 1) select * from cte")
    assert _is_read_only_select("-- note\nSELECT a FROM t")


def test_is_read_only_select_rejects_prose_and_writes():
    assert not _is_read_only_select("To calculate the rate, SELECT a FROM t")
    assert not _is_read_only_select("DELETE FROM t")
    assert not _is_read_only_select("")


def test_ai_generation_error_from_string_detail():
    friendly, details = _ai_generation_error(
        HTTPException(status_code=503, detail="AI server unreachable")
    )
    assert friendly == "We could not safely build a query for this question."
    assert details["validationError"] == "AI server unreachable"


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

    async def fake_generate(session, context, project_id, question, **kwargs):
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

    # M4 fast-follow: an executed preview is a structured result carrying the
    # shared ResponseEnvelope so the modal renders via the ResponsePresenter.
    assert body["presentation"]["mode"] == "structured"
    env = body["envelope"]
    assert env["mode"] == "structured"
    assert env["sections"] == body["presentation"]["sections"]
    assert env["sql"] == "SELECT month, revenue FROM q"
    assert env["columns"] == ["month", "revenue"]
    assert env["rows"][0]["revenue"] == 10
    assert env["chart"]["type"] == "line"


def _admin_headers(tenant_id: int = 1, user_id: int = 1) -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role="admin"
    )
    return {"Authorization": f"Bearer {token}"}


async def test_ai_status_reports_engine_mode_and_catalog(client):
    """/api/ai/status surfaces the resolved Analytical Method Engine mode plus
    whether an ``approved+active`` catalog version exists.

    When no catalog is active, hybrid analysis silently produces nothing — this
    field turns that silent gap into a diagnosable signal (Issue 1.2).
    """
    r = await client.get("/api/ai/status", headers=_admin_headers())
    assert r.status_code == 200, r.text
    analytical = r.json()["analytical"]
    # Default resolves to readonly so hybrid classification runs (Issue 1.1).
    assert analytical["engineMode"] == "readonly"
    # No seeded catalog in the unit DB → not active (the silent-gap signal).
    assert analytical["catalog"]["active"] is False
    assert analytical["catalog"]["version_id"] is None
