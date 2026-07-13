"""Tests for the Home AI Intelligence suite, preferences, and reports."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.auth.jwt import create_access_token
from app.services import home_intelligence as hi


def _project(pid: int = 1, name: str = "Supply Chain"):
    return SimpleNamespace(id=pid, name=name)


def _table(view: str, columns: list[str]):
    return hi.TableInfo(
        view_name=view, columns=[(c, "string") for c in columns], kind="file"
    )


def _runner(rows_by_fragment: dict[str, list[dict]]):
    async def runner(sql: str) -> dict:
        for fragment, rows in rows_by_fragment.items():
            if fragment in sql:
                cols = list(rows[0].keys()) if rows else []
                return {"columns": cols, "rows": rows}
        return {"columns": [], "rows": []}

    return runner


# ─────────────────────────────── service ────────────────────────────────────

async def test_risk_sla_breach_detected() -> None:
    ctx = hi.ProjectContext(
        tables=[_table("shipments", ["month", "supplier", "lead_time"])],
        documents=[],
    )
    runner = _runner(
        {
            "GROUP BY": [
                {"period": "2024-01", "avg_lead": 12.0},
                {"period": "2024-02", "avg_lead": 22.0},
            ]
        }
    )
    cards = await hi.run_intelligence_suite(_project(), ctx, ["risk_sla"], runner)
    assert len(cards) == 1
    card = cards[0]
    assert card["insightType"] == "risk_sla"
    assert card["severity"] in {"urgent", "critical"}
    assert card["chart"]["type"] == "bar"
    assert "shipments" in card["sources"]["tables"]


async def test_risk_sla_skipped_without_lead_time_column() -> None:
    ctx = hi.ProjectContext(
        tables=[_table("orders", ["id", "name", "qty"])], documents=[]
    )
    cards = await hi.run_intelligence_suite(
        _project(), ctx, ["risk_sla"], _runner({})
    )
    assert cards == []


async def test_risk_expiry_lists_documents_within_90_days() -> None:
    soon = (date.today() + timedelta(days=20)).isoformat()
    far = (date.today() + timedelta(days=400)).isoformat()
    ctx = hi.ProjectContext(
        tables=[],
        documents=[
            hi.DocInfo(
                title="Boeing MSA",
                ai_summary=None,
                ai_metadata={"expiry_date": soon},
            ),
            hi.DocInfo(
                title="Old NDA", ai_summary=None, ai_metadata={"expiry_date": far}
            ),
        ],
    )
    cards = await hi.run_intelligence_suite(
        _project(), ctx, ["risk_expiry"], None
    )
    assert len(cards) == 1
    assert cards[0]["insightType"] == "risk_expiry"
    assert "Boeing MSA" in cards[0]["sources"]["documents"]
    assert "Old NDA" not in cards[0]["sources"]["documents"]
    assert cards[0]["severity"] == "urgent"


async def test_trend_spend_over_budget() -> None:
    ctx = hi.ProjectContext(
        tables=[_table("finance", ["month", "amount", "budget"])], documents=[]
    )
    runner = _runner(
        {
            '"amount"': [{"total": 120000.0}],
            '"budget"': [{"b": 100000.0}],
        }
    )
    cards = await hi.run_intelligence_suite(
        _project(), ctx, ["trend_spend"], runner
    )
    assert len(cards) == 1
    card = cards[0]
    assert card["chart"]["type"] == "kpi_grid"
    assert card["severity"] == "urgent"


async def test_opportunity_supplier_top_performers() -> None:
    ctx = hi.ProjectContext(
        tables=[_table("vendors", ["supplier", "on_time_rate"])], documents=[]
    )
    runner = _runner(
        {
            "GROUP BY": [
                {"supplier": "Acme", "metric": 98.0},
                {"supplier": "Globex", "metric": 91.0},
            ]
        }
    )
    cards = await hi.run_intelligence_suite(
        _project(), ctx, ["opportunity_supplier"], runner
    )
    assert len(cards) == 1
    assert cards[0]["insightType"] == "opportunity_supplier"
    assert cards[0]["callout"]["type"] == "opportunity"


async def test_synthesise_detects_shared_entity() -> None:
    summaries = [
        {
            "projectId": "1",
            "projectName": "Aerospace",
            "insightSummaries": ["Top performer is **Boeing** by far."],
        },
        {
            "projectId": "2",
            "projectName": "Defense",
            "insightSummaries": ["**Boeing** contract expires soon."],
        },
    ]
    result = hi.synthesise_cross_project(summaries)
    assert result is not None
    assert "Boeing" in result["body"]
    assert set(result["projectIds"]) == {"1", "2"}


# ──────────────────────── AI-driven analyst loop ────────────────────────────

def test_build_chart_bar_from_results() -> None:
    result = {
        "columns": ["supplier", "spend"],
        "rows": [
            {"supplier": "Acme", "spend": "1200"},
            {"supplier": "Globex", "spend": "800"},
        ],
    }
    chart = hi._build_chart("bar", "Spend by supplier", result, "supplier", "spend")
    assert chart is not None
    assert chart["type"] == "bar"
    assert chart["data"]["series"] == [
        {"label": "Acme", "value": 1200.0},
        {"label": "Globex", "value": 800.0},
    ]


def test_build_chart_kpi_grid_single_row() -> None:
    result = {
        "columns": ["total_spend", "order_count"],
        "rows": [{"total_spend": "2500000", "order_count": "1300"}],
    }
    chart = hi._build_chart("kpi_grid", "Headline", result, "", "")
    assert chart is not None
    assert chart["type"] == "kpi_grid"
    labels = {k["label"] for k in chart["data"]["kpis"]}
    assert labels == {"total_spend", "order_count"}


def test_build_chart_skips_when_no_numeric() -> None:
    result = {"columns": ["name"], "rows": [{"name": "abc"}]}
    assert hi._build_chart("bar", "t", result, "", "") is None


def test_build_chart_single_row_excludes_period_dimension() -> None:
    # A trend that collapsed to one period (single year) must not render the
    # grouped year as a "2.0K" KPI tile — only the real metric is a headline.
    result = {
        "columns": ["Period", "DefectRate"],
        "rows": [{"Period": "2026", "DefectRate": "0.34"}],
    }
    chart = hi._build_chart("line", "Defect rate trend", result, "Period", "DefectRate")
    assert chart is not None
    assert chart["type"] == "kpi_grid"
    labels = {k["label"] for k in chart["data"]["kpis"]}
    assert labels == {"DefectRate"}


def test_dimension_columns_detects_time_labels() -> None:
    cols = ["Period", "Month", "OnTimeRate", "SupplierID"]
    skip = hi._dimension_columns(cols, "SupplierID")
    assert skip == {"Period", "Month", "SupplierID"}


def test_tables_in_sql_detects_referenced_views() -> None:
    tables = [_table("shipments", ["a"]), _table("orders", ["b"])]
    sql = 'SELECT a FROM "shipments" GROUP BY a'
    assert hi._tables_in_sql(sql, tables) == ["shipments"]


async def test_run_ai_intelligence_executes_and_interprets(monkeypatch) -> None:
    from app.services import ai_intelligence_client as ai

    ctx = hi.ProjectContext(
        tables=[_table("spend", ["supplier", "amount"])], documents=[]
    )

    monkeypatch.setattr(ai, "is_enabled", lambda: True)

    async def fake_plan(**kwargs):
        return [
            {
                "id": "a1",
                "category": "trend",
                "title": "Spend by supplier",
                "rationale": "Concentration risk.",
                "sql": 'SELECT "supplier", SUM(CAST("amount" AS double)) AS spend '
                'FROM "spend" GROUP BY "supplier"',
                "chart_type": "bar",
                "label_column": "supplier",
                "value_column": "spend",
                "severity_hint": "watch",
            }
        ]

    async def fake_interpret(**kwargs):
        return {
            "a1": {
                "id": "a1",
                "title": "Spend concentrated in top vendor",
                "summary": "**Acme** accounts for the majority of spend.",
                "severity": "urgent",
                "callout_type": "risk",
                "callout_text": "Diversify suppliers.",
                "recommendation": "Add a second source.",
            }
        }

    monkeypatch.setattr(ai, "plan", fake_plan)
    monkeypatch.setattr(ai, "interpret", fake_interpret)

    runner = _runner(
        {"GROUP BY": [{"supplier": "Acme", "spend": 1200.0},
                      {"supplier": "Globex", "spend": 200.0}]}
    )
    cards = await hi.run_ai_intelligence(
        _project(), ctx, runner, tenant_id=1, user_id=1
    )
    assert cards is not None and len(cards) == 1
    card = cards[0]
    assert card["insightType"] == "trend_a1"
    assert card["severity"] == "urgent"
    assert card["chart"]["type"] == "bar"
    assert card["callout"]["type"] == "risk"
    assert "spend" in card["sources"]["tables"]


async def test_run_ai_intelligence_returns_none_when_disabled(monkeypatch) -> None:
    from app.services import ai_intelligence_client as ai

    monkeypatch.setattr(ai, "is_enabled", lambda: False)
    ctx = hi.ProjectContext(tables=[], documents=[])
    result = await hi.run_ai_intelligence(
        _project(), ctx, None, tenant_id=1, user_id=1
    )
    assert result is None


async def test_run_ai_intelligence_skips_empty_results(monkeypatch) -> None:
    from app.services import ai_intelligence_client as ai

    monkeypatch.setattr(ai, "is_enabled", lambda: True)

    async def fake_plan(**kwargs):
        return [
            {
                "id": "a1",
                "category": "risk",
                "title": "Empty",
                "sql": 'SELECT x FROM "spend"',
                "chart_type": "bar",
            }
        ]

    interpret_called = {"v": False}

    async def fake_interpret(**kwargs):
        interpret_called["v"] = True
        return {}

    monkeypatch.setattr(ai, "plan", fake_plan)
    monkeypatch.setattr(ai, "interpret", fake_interpret)

    ctx = hi.ProjectContext(tables=[_table("spend", ["x"])], documents=[])
    runner = _runner({})  # returns no rows
    cards = await hi.run_ai_intelligence(
        _project(), ctx, runner, tenant_id=1, user_id=1
    )
    assert cards == []
    assert interpret_called["v"] is False  # nothing to interpret


# ─────────────── Analytical Method Engine wiring (hybrid mode) ───────────────

def _method_plan_interpret(monkeypatch, *, summary_confidence=None) -> None:
    """Wire a minimal enabled AI plan/interpret producing one trend card."""
    from app.services import ai_intelligence_client as ai

    monkeypatch.setattr(ai, "is_enabled", lambda: True)

    async def fake_plan(**kwargs):
        return [
            {
                "id": "a1",
                "category": "trend",
                "title": "Spend by supplier",
                "rationale": "Concentration risk.",
                "sql": 'SELECT "supplier", SUM(CAST("amount" AS double)) AS spend '
                'FROM "spend" GROUP BY "supplier"',
                "chart_type": "bar",
                "label_column": "supplier",
                "value_column": "spend",
                "severity_hint": "watch",
            }
        ]

    async def fake_interpret(**kwargs):
        ins: dict = {
            "id": "a1",
            "title": "Spend concentrated",
            "summary": "**Acme** dominates spend.",
            "severity": "watch",
        }
        if summary_confidence is not None:
            ins["confidence"] = summary_confidence
        return {"a1": ins}

    monkeypatch.setattr(ai, "plan", fake_plan)
    monkeypatch.setattr(ai, "interpret", fake_interpret)


def _spend_ctx_runner():
    ctx = hi.ProjectContext(
        tables=[_table("spend", ["supplier", "amount"])], documents=[]
    )
    runner = _runner(
        {
            "GROUP BY": [
                {"supplier": "Acme", "spend": 1200.0},
                {"supplier": "Globex", "spend": 800.0},
                {"supplier": "Initech", "spend": 200.0},
            ]
        }
    )
    return ctx, runner


async def test_method_engine_hybrid_attaches_envelope(monkeypatch) -> None:
    _method_plan_interpret(monkeypatch)
    monkeypatch.setattr(hi, "get_engine_mode", lambda: hi.EngineMode.HYBRID)

    seen = {"question": None}

    async def fake_analyze(session, **kwargs):
        seen["question"] = kwargs.get("question")
        return {
            "status": "ok",
            "method": "pearson_correlation",
            "methodName": "Pearson Correlation",
            "quality": "reliable",
            "tier": 1,
            "n": 12,
            "usableN": 12,
        }

    monkeypatch.setattr(hi, "analyze_methods", fake_analyze)

    ctx, runner = _spend_ctx_runner()
    cards = await hi.run_ai_intelligence(
        _project(), ctx, runner, session=object(), tenant_id=1, user_id=1
    )
    assert cards is not None and len(cards) == 1
    card = cards[0]
    assert card["analyticalMethod"]["method"] == "pearson_correlation"
    # Real quality verdict replaces the row-count guess (0.75 -> 0.9).
    assert card["confidenceScore"] == 0.9
    # The declared trend intent is forwarded and the question is built.
    assert "Spend by supplier" in (seen["question"] or "")


async def test_method_engine_tentative_confidence(monkeypatch) -> None:
    _method_plan_interpret(monkeypatch)
    monkeypatch.setattr(hi, "get_engine_mode", lambda: hi.EngineMode.HYBRID)

    async def fake_analyze(session, **kwargs):
        return {
            "status": "ok",
            "method": "describe_numeric",
            "quality": "tentative",
        }

    monkeypatch.setattr(hi, "analyze_methods", fake_analyze)

    ctx, runner = _spend_ctx_runner()
    cards = await hi.run_ai_intelligence(
        _project(), ctx, runner, session=object(), tenant_id=1, user_id=1
    )
    assert cards[0]["confidenceScore"] == 0.6


async def test_method_engine_off_is_noop(monkeypatch) -> None:
    _method_plan_interpret(monkeypatch)
    monkeypatch.setattr(hi, "get_engine_mode", lambda: hi.EngineMode.OFF)

    called = {"v": False}

    async def fake_analyze(session, **kwargs):
        called["v"] = True
        return {"status": "ok", "method": "x", "quality": "reliable"}

    monkeypatch.setattr(hi, "analyze_methods", fake_analyze)

    ctx, runner = _spend_ctx_runner()
    cards = await hi.run_ai_intelligence(
        _project(), ctx, runner, session=object(), tenant_id=1, user_id=1
    )
    assert called["v"] is False
    assert "analyticalMethod" not in cards[0]
    assert cards[0]["confidenceScore"] == 0.75  # unchanged row-count guess


async def test_method_engine_failure_never_drops_card(monkeypatch) -> None:
    _method_plan_interpret(monkeypatch)
    monkeypatch.setattr(hi, "get_engine_mode", lambda: hi.EngineMode.HYBRID)

    async def boom(session, **kwargs):
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(hi, "analyze_methods", boom)

    ctx, runner = _spend_ctx_runner()
    cards = await hi.run_ai_intelligence(
        _project(), ctx, runner, session=object(), tenant_id=1, user_id=1
    )
    # 6->0 regression guard: the card still builds, just without an envelope.
    assert len(cards) == 1
    assert "analyticalMethod" not in cards[0]


async def test_method_engine_no_method_not_attached(monkeypatch) -> None:
    _method_plan_interpret(monkeypatch)
    monkeypatch.setattr(hi, "get_engine_mode", lambda: hi.EngineMode.HYBRID)

    async def fake_analyze(session, **kwargs):
        # Selector honestly rejected the shape — no method bound.
        return {"status": "no_method", "method": None, "quality": None}

    monkeypatch.setattr(hi, "analyze_methods", fake_analyze)

    ctx, runner = _spend_ctx_runner()
    cards = await hi.run_ai_intelligence(
        _project(), ctx, runner, session=object(), tenant_id=1, user_id=1
    )
    assert "analyticalMethod" not in cards[0]


async def test_method_engine_no_session_is_noop(monkeypatch) -> None:
    _method_plan_interpret(monkeypatch)
    monkeypatch.setattr(hi, "get_engine_mode", lambda: hi.EngineMode.HYBRID)

    called = {"v": False}

    async def fake_analyze(session, **kwargs):
        called["v"] = True
        return {"status": "ok", "method": "x", "quality": "reliable"}

    monkeypatch.setattr(hi, "analyze_methods", fake_analyze)

    ctx, runner = _spend_ctx_runner()
    cards = await hi.run_ai_intelligence(
        _project(), ctx, runner, tenant_id=1, user_id=1
    )
    assert called["v"] is False
    assert "analyticalMethod" not in cards[0]


# ───────────── insight-first methodology: helpers & metadata ─────────────────

def test_home_best_practices_reference_loads() -> None:
    text = hi.home_best_practices()
    assert text  # the markdown reference must be present and non-empty
    assert "insight" in text.lower()


def test_detect_entities_finds_entity_columns() -> None:
    tables = [
        _table("suppliers", ["SupplierID", "SupplierName", "Country"]),
        _table("metrics", ["month", "value"]),
    ]
    entities = hi.detect_entities(tables)
    assert "suppliers" in entities
    assert "SupplierID" in entities["suppliers"]
    # A table with no entity-named column is not listed.
    assert "metrics" not in entities


def test_find_relationship_candidates_requires_key_match() -> None:
    tables = [
        _table("suppliers", ["SupplierID", "SupplierName"]),
        _table("inspections", ["SupplierID", "DefectQty", "InspectionDate"]),
    ]
    cands = hi.find_relationship_candidates(tables)
    assert len(cands) == 1
    c = cands[0]
    assert {c["left_table"], c["right_table"]} == {"suppliers", "inspections"}
    assert c["left_join_key"] == "SupplierID"
    assert "exact key-name match" in c["confidence_reason"]


def test_find_relationship_candidates_rejects_weak_join() -> None:
    # Two tables share a plain non-key column name ("region") — that is not
    # join evidence, so no relationship should be inferred.
    tables = [
        _table("sales", ["region", "amount"]),
        _table("returns", ["region", "qty"]),
    ]
    assert hi.find_relationship_candidates(tables) == []


def test_normalize_severity_rejects_unknown_and_allows_warning() -> None:
    assert hi._normalize_severity("warning") == "warning"
    assert hi._normalize_severity("critical") == "critical"
    # An invented / inflated severity falls back to info, never up-leveled.
    assert hi._normalize_severity("catastrophic") == "info"
    assert hi._normalize_severity("") == "info"


def test_rank_and_dedupe_removes_duplicates() -> None:
    proj = _project()
    base = dict(
        projectId="1",
        insightType="risk_a",
        title="Supplier risk",
        sources={"tables": ["suppliers"], "documents": []},
        severity="urgent",
        chart=None,
    )
    cards = [dict(base), dict(base)]
    ranked = hi.rank_and_dedupe_cards(cards)
    assert len(ranked) == 1
    assert proj.id == 1  # sanity


def test_rank_and_dedupe_orders_by_severity() -> None:
    low = {
        "projectId": "1", "insightType": "trend_a", "title": "Minor",
        "severity": "info", "sources": {"tables": ["t1"], "documents": []},
    }
    high = {
        "projectId": "1", "insightType": "risk_b", "title": "Severe",
        "severity": "critical", "sources": {"tables": ["t2"], "documents": []},
    }
    ranked = hi.rank_and_dedupe_cards([low, high])
    assert [c["title"] for c in ranked] == ["Severe", "Minor"]


def test_rank_and_dedupe_caps_to_max() -> None:
    cards = [
        {
            "projectId": "1",
            "insightType": f"trend_{i}",
            "title": f"Insight {i}",
            "severity": "info",
            "sources": {"tables": [f"t{i}"], "documents": []},
        }
        for i in range(20)
    ]
    assert len(hi.rank_and_dedupe_cards(cards)) == 8


def test_rank_and_dedupe_exempts_multi_table_from_cap() -> None:
    single = [
        {
            "projectId": "1",
            "insightType": f"trend_{i}",
            "title": f"Single {i}",
            "severity": "info",
            "sources": {"tables": [f"t{i}"], "documents": []},
        }
        for i in range(10)
    ]
    multi = [
        {
            "projectId": "1",
            "insightType": f"relationship_{i}",
            "title": f"Join {i}",
            "severity": "info",
            "sources": {"tables": [f"a{i}", f"b{i}"], "documents": []},
            "relationshipMetadata": {"leftTable": f"a{i}"},
        }
        for i in range(4)
    ]
    ranked = hi.rank_and_dedupe_cards(single + multi)
    # 8 single-table (capped) + all 4 multi-table (uncapped) = 12.
    assert len(ranked) == 12
    surfaced_multi = [
        c for c in ranked if len(c["sources"]["tables"]) >= 2
    ]
    assert len(surfaced_multi) == 4


def test_rank_and_dedupe_collapses_duplicate_multi_table_cards() -> None:
    base = {
        "projectId": "1",
        "insightType": "relationship_a",
        "title": "Suppliers x Inspections",
        "severity": "warning",
        "sources": {"tables": ["suppliers", "inspections"], "documents": []},
        "relationshipMetadata": {"leftTable": "suppliers"},
    }
    ranked = hi.rank_and_dedupe_cards([dict(base), dict(base)])
    assert len(ranked) == 1


def test_card_priority_ranks_multi_table_above_single_at_equal_severity() -> None:
    single = {
        "severity": "warning",
        "confidenceScore": 0.75,
        "sources": {"tables": ["t1"], "documents": []},
    }
    multi = {
        "severity": "warning",
        "confidenceScore": 0.75,
        "sources": {"tables": ["a", "b"], "documents": []},
        "relationshipMetadata": {"leftTable": "a"},
    }
    assert hi._card_priority(multi) > hi._card_priority(single)


async def test_run_ai_intelligence_logs_multi_table_funnel(
    monkeypatch, caplog
) -> None:
    import logging

    from app.services import ai_intelligence_client as ai

    monkeypatch.setattr(ai, "is_enabled", lambda: True)

    async def fake_plan(**kwargs):
        return [
            {
                "id": "a1",
                "category": "trend",
                "title": "Spend by supplier",
                "rationale": "Concentration risk.",
                "sql": 'SELECT "supplier", SUM(CAST("amount" AS double)) AS spend '
                'FROM "spend" GROUP BY "supplier"',
                "chart_type": "bar",
                "label_column": "supplier",
                "value_column": "spend",
                "severity_hint": "watch",
            }
        ]

    async def fake_interpret(**kwargs):
        return {
            "a1": {
                "id": "a1",
                "title": "Spend concentrated",
                "summary": "**Acme** dominates spend.",
                "severity": "watch",
            }
        }

    monkeypatch.setattr(ai, "plan", fake_plan)
    monkeypatch.setattr(ai, "interpret", fake_interpret)

    ctx = hi.ProjectContext(
        tables=[_table("spend", ["supplier", "amount"])], documents=[]
    )
    runner = _runner(
        {
            "GROUP BY": [
                {"supplier": "Acme", "spend": 1200.0},
                {"supplier": "Globex", "spend": 800.0},
                {"supplier": "Initech", "spend": 200.0},
            ]
        }
    )

    with caplog.at_level(logging.INFO, logger="app.services.home_intelligence"):
        await hi.run_ai_intelligence(
            _project(), ctx, runner, tenant_id=1, user_id=1
        )

    funnel = [
        r.getMessage()
        for r in caplog.records
        if "multi-table funnel" in r.getMessage()
    ]
    assert len(funnel) == 1
    # Single-table plan → all four funnel counts are zero.
    assert "hints=0 planned=0 executed=0 surfaced=0" in funnel[0]


async def test_run_ai_intelligence_attaches_metadata(monkeypatch) -> None:
    from app.services import ai_intelligence_client as ai

    monkeypatch.setattr(ai, "is_enabled", lambda: True)

    async def fake_plan(**kwargs):
        return [
            {
                "id": "a1",
                "category": "trend",
                "title": "Spend by supplier",
                "rationale": "Concentration risk.",
                "sql": 'SELECT "supplier", SUM(CAST("amount" AS double)) AS spend '
                'FROM "spend" GROUP BY "supplier"',
                "chart_type": "bar",
                "label_column": "supplier",
                "value_column": "spend",
                "severity_hint": "watch",
            }
        ]

    async def fake_interpret(**kwargs):
        return {
            "a1": {
                "id": "a1",
                "title": "Spend concentrated",
                "summary": "**Acme** dominates spend.",
                "severity": "watch",
            }
        }

    monkeypatch.setattr(ai, "plan", fake_plan)
    monkeypatch.setattr(ai, "interpret", fake_interpret)

    ctx = hi.ProjectContext(
        tables=[_table("spend", ["supplier", "amount"])], documents=[]
    )
    runner = _runner(
        {
            "GROUP BY": [
                {"supplier": "Acme", "spend": 1200.0},
                {"supplier": "Globex", "spend": 800.0},
                {"supplier": "Initech", "spend": 200.0},
            ]
        }
    )
    cards = await hi.run_ai_intelligence(
        _project(), ctx, runner, tenant_id=1, user_id=1
    )
    assert cards is not None and len(cards) == 1
    card = cards[0]
    assert card["insightMethod"] == "llm_planned"
    assert card["confidenceScore"] == 0.75  # >=3 rows
    assert card["validation"]["rowCount"] == 3
    assert card["validation"]["nonNullMetricCount"] == 3
    # relationshipMetadata is omitted for a single-table card.
    assert "relationshipMetadata" not in card


async def test_run_ai_intelligence_multi_table_relationship(monkeypatch) -> None:
    from app.services import ai_intelligence_client as ai

    captured: dict = {}
    monkeypatch.setattr(ai, "is_enabled", lambda: True)

    async def fake_plan(**kwargs):
        captured.update(kwargs)
        return [
            {
                "id": "a1",
                "category": "relationship",
                "title": "High-spend suppliers with defects",
                "rationale": "Concentration + quality risk.",
                "sql": 'SELECT s."SupplierName", SUM(CAST(i."DefectQty" AS double)) '
                'AS defects FROM "suppliers" s JOIN "inspections" i '
                'ON s."SupplierID" = i."SupplierID" GROUP BY s."SupplierName"',
                "chart_type": "bar",
                "label_column": "SupplierName",
                "value_column": "defects",
                "severity_hint": "warning",
            }
        ]

    async def fake_interpret(**kwargs):
        return {
            "a1": {
                "id": "a1",
                "title": "Defects concentrated in top supplier",
                "summary": "**Acme** has the most defects.",
                "severity": "warning",
            }
        }

    monkeypatch.setattr(ai, "plan", fake_plan)
    monkeypatch.setattr(ai, "interpret", fake_interpret)

    ctx = hi.ProjectContext(
        tables=[
            _table("suppliers", ["SupplierID", "SupplierName"]),
            _table("inspections", ["SupplierID", "DefectQty"]),
        ],
        documents=[],
    )
    runner = _runner(
        {"JOIN": [{"SupplierName": "Acme", "defects": 40.0},
                  {"SupplierName": "Globex", "defects": 5.0}]}
    )
    cards = await hi.run_ai_intelligence(
        _project(), ctx, runner, tenant_id=1, user_id=1
    )
    # The planner received the evidence-backed relationship hints.
    assert captured["relationship_hints"]
    assert cards is not None and len(cards) == 1
    card = cards[0]
    assert card["severity"] == "warning"
    assert card["insightMethod"] == "relationship"
    rel = card["relationshipMetadata"]
    assert {rel["leftTable"], rel["rightTable"]} == {"suppliers", "inspections"}
    assert rel["leftJoinKey"] == "SupplierID"
    # Card keeps the existing required shape (frontend compatibility).
    for key in (
        "id", "projectId", "projectName", "projectColor", "insightType",
        "severity", "title", "summary", "chart", "callout", "sources",
        "executedAt",
    ):
        assert key in card


# ─────────────────────────── endpoints (via client) ─────────────────────────

def _editor_headers(tenant_id: int, user_id: int) -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role="editor"
    )
    return {"Authorization": f"Bearer {token}"}


async def _setup(client, service_headers):
    r = await client.post(
        "/api/tenants",
        json={"slug": "hi-tenant", "name": "HI Tenant"},
        headers=service_headers,
    )
    assert r.status_code == 201
    tenant = r.json()
    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": "hi@test.com",
            "display_name": "HI User",
            "role": "editor",
            "external_id": "ext-hi",
        },
        headers=service_headers,
    )
    assert r.status_code == 201
    user = r.json()
    return tenant, user, _editor_headers(tenant["id"], user["id"])


@pytest.fixture(autouse=True)
def _mock_supabase(monkeypatch):
    import app.routes.tenants as tenants_module
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
        async def send_transactional_email(self, *, to, template, variables, subject=None, reply_to=None) -> bool:
            return True

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)


async def test_preferences_defaults_and_persist(client, service_headers) -> None:
    _, _, headers = await _setup(client, service_headers)

    r = await client.get("/api/users/preferences", headers=headers)
    assert r.status_code == 200
    prefs = r.json()
    assert prefs["intelligence"]["run_on_load"] is True
    assert prefs["intelligence"]["email_digest"] is False

    r = await client.patch(
        "/api/users/preferences",
        json={"intelligence": {"email_digest": True, "run_on_load": False}},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["intelligence"]["email_digest"] is True

    r = await client.get("/api/users/preferences", headers=headers)
    assert r.json()["intelligence"]["email_digest"] is True
    assert r.json()["intelligence"]["run_on_load"] is False
    # Unspecified default preserved.
    assert r.json()["intelligence"]["cross_project"] is True


async def test_reports_create_get_list_delete(client, service_headers) -> None:
    _, _, headers = await _setup(client, service_headers)

    r = await client.post(
        "/api/reports",
        json={
            "title": "Q1 Risk Review",
            "sections": [{"type": "insight", "insightType": "risk_sla"}],
            "share_settings": {"isPublic": True},
        },
        headers=headers,
    )
    assert r.status_code == 200
    report = r.json()
    token = report["shareToken"]
    assert report["shareUrl"] == f"/reports/{token}"
    assert report["title"] == "Q1 Risk Review"

    r = await client.get(f"/api/reports/{token}", headers=headers)
    assert r.status_code == 200
    assert r.json()["sections"][0]["insightType"] == "risk_sla"

    r = await client.get("/api/reports", headers=headers)
    assert len(r.json()) == 1

    r = await client.delete(f"/api/reports/{token}", headers=headers)
    assert r.status_code == 204

    r = await client.get(f"/api/reports/{token}", headers=headers)
    assert r.status_code == 404


async def test_run_intelligence_suite_no_access(client, service_headers) -> None:
    _, _, headers = await _setup(client, service_headers)
    r = await client.post(
        "/api/ai/run-intelligence-suite",
        json={"project_id": 99999},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["error"] == "no_access"


async def test_project_dashboard_rejects_inaccessible_project(
    client, service_headers
) -> None:
    _, _, headers = await _setup(client, service_headers)
    r = await client.post(
        "/api/ai/home/project-dashboard",
        json={"project_id": 99999},
        headers=headers,
    )
    assert r.status_code == 404


async def test_project_dashboard_builds_real_chart_widgets(
    client, service_headers, monkeypatch
) -> None:
    _, _, headers = await _setup(client, service_headers)
    r = await client.post(
        "/api/projects",
        json={"name": "Dash P", "description": "x", "is_shared": False},
        headers=headers,
    )
    assert r.status_code == 201
    project_id = r.json()["id"]

    import app.routes.home_intelligence as hir

    async def fake_plan(session, context, project, *, max_analyses, granularity):
        return [
            {
                "title": "Spend by supplier",
                "sql": 'SELECT "supplier", SUM(CAST("amount" AS double)) AS spend '
                'FROM "SUP_Suppliers_CSV" GROUP BY "supplier"',
                "chart_type": "bar",
                "label_column": "supplier",
                "value_column": "spend",
            },
            # A widget whose SQL returns nothing is dropped, never "preview only".
            {"title": "Empty", "sql": 'SELECT "x" FROM "empty"', "chart_type": "bar"},
        ]

    def fake_make_runner(session, context, project_id):
        async def runner(sql: str) -> dict:
            if "SUP_Suppliers_CSV" in sql:
                return {
                    "columns": ["supplier", "spend"],
                    "rows": [
                        {"supplier": "Acme", "spend": 1200.0},
                        {"supplier": "Globex", "spend": 800.0},
                    ],
                }
            return {"columns": [], "rows": []}

        return runner

    monkeypatch.setattr(hir, "_plan_analyses", fake_plan)
    monkeypatch.setattr(hir, "_make_runner", fake_make_runner)

    r = await client.post(
        "/api/ai/home/project-dashboard",
        json={"project_id": project_id},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["dashboard"] is not None
    widgets = body["dashboard"]["widgets"]
    assert len(widgets) == 1  # the empty widget was dropped
    assert widgets[0]["title"] == "Spend by supplier"
    assert widgets[0]["chart"]["type"] == "bar"


# ─────────── no-project-skipped: deterministic floor + merge policy ──────────

def _floor_ctx(monkeypatch):
    """Patch context-gathering + runner so _run_for_project needs no DB/VDB."""
    import app.routes.home_intelligence as hir

    async def fake_gather(session, project):
        return hi.ProjectContext(tables=[], documents=[])

    monkeypatch.setattr(hi, "gather_project_context", fake_gather)
    monkeypatch.setattr(hir, "_make_runner", lambda *a, **k: None)
    return hir


def _ctx_obj():
    return SimpleNamespace(tenant_id=1, user_id=1)


@pytest.mark.parametrize("ai_result", [None, []])
async def test_run_for_project_falls_back_to_suite_on_empty(
    monkeypatch, ai_result
) -> None:
    hir = _floor_ctx(monkeypatch)

    async def ai_empty(*a, **k):
        return ai_result

    monkeypatch.setattr(hi, "run_ai_intelligence", ai_empty)

    called = {"v": False}

    async def fake_suite(project, ctx, prompt_types, runner):
        called["v"] = True
        return [{"title": "floor card", "insightType": "risk_sla"}]

    monkeypatch.setattr(hi, "run_intelligence_suite", fake_suite)

    cards = await hir._run_for_project(
        object(), _ctx_obj(), _project(), ["risk_sla"], write_audit=False
    )
    assert called["v"] is True
    assert cards == [{"title": "floor card", "insightType": "risk_sla"}]


async def test_run_for_project_keeps_ai_cards_no_fallback(monkeypatch) -> None:
    hir = _floor_ctx(monkeypatch)

    async def ai_cards(*a, **k):
        return [{"title": "ai card"}]

    monkeypatch.setattr(hi, "run_ai_intelligence", ai_cards)

    called = {"v": False}

    async def fake_suite(*a, **k):
        called["v"] = True
        return [{"title": "floor"}]

    monkeypatch.setattr(hi, "run_intelligence_suite", fake_suite)

    cards = await hir._run_for_project(
        object(), _ctx_obj(), _project(), ["risk_sla"], write_audit=False
    )
    assert called["v"] is False  # no fallback when AI produced cards
    assert cards == [{"title": "ai card"}]


async def test_run_for_project_still_raises_ai_unavailable(monkeypatch) -> None:
    from app.services.ai_intelligence_client import AIUnavailableError

    hir = _floor_ctx(monkeypatch)

    async def ai_busy(*a, **k):
        raise AIUnavailableError("busy")

    monkeypatch.setattr(hi, "run_ai_intelligence", ai_busy)

    called = {"v": False}

    async def fake_suite(*a, **k):
        called["v"] = True
        return [{"title": "floor"}]

    monkeypatch.setattr(hi, "run_intelligence_suite", fake_suite)

    with pytest.raises(AIUnavailableError):
        await hir._run_for_project(
            object(), _ctx_obj(), _project(), ["risk_sla"], write_audit=False
        )
    # Queue-retry contract intact: no deterministic fallback on transient busy.
    assert called["v"] is False


async def test_run_deterministic_for_project_fail_open(monkeypatch) -> None:
    import app.routes.home_intelligence as hir

    async def boom(session, project):
        raise RuntimeError("context gather failed")

    monkeypatch.setattr(hi, "gather_project_context", boom)
    cards = await hir.run_deterministic_for_project(
        object(), _ctx_obj(), _project()
    )
    assert cards == []  # floor must never raise


def test_merge_snapshot_success_empty_keeps_prior_non_empty() -> None:
    import app.routes.home_intelligence as hir

    prior = [{"projectId": "1", "insights": [{"t": "old"}]}]
    fresh_empty = [{"projectId": "1", "insights": []}]
    merged = hir._merge_snapshot_results(
        prior, fresh_empty, {"1"}, keep_prior_on_empty=True
    )
    assert merged == [{"projectId": "1", "insights": [{"t": "old"}]}]


def test_merge_snapshot_success_empty_overwrites_when_disabled() -> None:
    import app.routes.home_intelligence as hir

    prior = [{"projectId": "1", "insights": [{"t": "old"}]}]
    fresh_empty = [{"projectId": "1", "insights": []}]
    merged = hir._merge_snapshot_results(
        prior, fresh_empty, {"1"}, keep_prior_on_empty=False
    )
    assert merged == [{"projectId": "1", "insights": []}]


def test_merge_snapshot_fresh_nonempty_always_wins() -> None:
    import app.routes.home_intelligence as hir

    prior = [{"projectId": "1", "insights": [{"t": "old"}]}]
    fresh = [{"projectId": "1", "insights": [{"t": "new"}]}]
    merged = hir._merge_snapshot_results(
        prior, fresh, {"1"}, keep_prior_on_empty=True
    )
    assert merged == [{"projectId": "1", "insights": [{"t": "new"}]}]


def test_merge_snapshot_error_preserves_prior_behavior() -> None:
    # The empty-guard only shields *successful* empties. An errored fresh
    # result keeps the pre-change behavior (it overwrites), since it is not a
    # silent "AI came up empty" case — the worker's floor already tried to
    # supply grounded cards before recording a bare error.
    import app.routes.home_intelligence as hir

    prior = [{"projectId": "1", "insights": [{"t": "old"}]}]
    errored = [{"projectId": "1", "error": "analysis timed out"}]
    merged = hir._merge_snapshot_results(
        prior, errored, {"1"}, keep_prior_on_empty=True
    )
    assert merged == [{"projectId": "1", "error": "analysis timed out"}]


def test_merge_snapshot_scopes_to_current_ids() -> None:
    import app.routes.home_intelligence as hir

    prior = [
        {"projectId": "1", "insights": [{"t": "a"}]},
        {"projectId": "2", "insights": [{"t": "b"}]},
    ]
    merged = hir._merge_snapshot_results(
        prior, [], {"1"}, keep_prior_on_empty=True
    )
    assert merged == [{"projectId": "1", "insights": [{"t": "a"}]}]


# ───────────── multi-table enrichment: tiered relationship evidence ──────────

def _pair(cands, a, b):
    for c in cands:
        if {c["left_table"], c["right_table"]} == {a, b}:
            return c
    return None


def test_relationship_baseline_exact_name_no_samples() -> None:
    # No scopes, no samples: exact key-name matching survives unchanged.
    tables = [
        _table("suppliers", ["SupplierID", "SupplierName"]),
        _table("inspections", ["SupplierID", "DefectQty"]),
    ]
    cands = hi.find_relationship_candidates(tables)
    assert len(cands) == 1
    c = cands[0]
    assert c["join_confidence"] == 0.6
    assert "exact key-name match" in c["confidence_reason"]
    # Without measured evidence, cardinality/risk stay conservative.
    assert c["relationship_type"] == "unknown"
    assert c["row_multiplication_risk"] == "medium"


def test_relationship_scope_link_user_created_09() -> None:
    tables = [
        _table("orders", ["OrderRef", "Amount"]),
        _table("shipments", ["ShipRef", "Carrier"]),
    ]
    link = hi.ScopeLink(
        left_table="orders",
        right_table="shipments",
        left_column="OrderRef",
        right_column="ShipRef",
        created_by_ai=False,
    )
    cands = hi.find_relationship_candidates(tables, scope_links=[link])
    c = _pair(cands, "orders", "shipments")
    assert c is not None
    assert c["join_confidence"] == 0.9
    assert "curated scope relationship" in c["confidence_reason"]


def test_relationship_scope_link_ai_created_085() -> None:
    tables = [
        _table("orders", ["OrderRef", "Amount"]),
        _table("shipments", ["ShipRef", "Carrier"]),
    ]
    link = hi.ScopeLink(
        left_table="orders",
        right_table="shipments",
        left_column="OrderRef",
        right_column="ShipRef",
        created_by_ai=True,
    )
    cands = hi.find_relationship_candidates(tables, scope_links=[link])
    c = _pair(cands, "orders", "shipments")
    assert c is not None
    assert c["join_confidence"] == 0.85


def test_relationship_scope_link_ignored_when_view_absent() -> None:
    # A scope pointing at a view the project no longer exposes is dropped.
    tables = [_table("orders", ["OrderRef", "Amount"])]
    link = hi.ScopeLink(
        left_table="orders",
        right_table="gone_view",
        left_column="OrderRef",
        right_column="X",
        created_by_ai=False,
    )
    assert hi.find_relationship_candidates(tables, scope_links=[link]) == []


def test_relationship_value_overlap_differently_named_keys() -> None:
    # SupplierCode vs VendorCode: different names, but sampled values overlap
    # ≥30% → a Tier-4 candidate with measured confidence.
    tables = [
        _table("purchases", ["SupplierCode", "Amount"]),
        _table("vendors", ["VendorCode", "Name"]),
    ]
    key_values = {
        "purchases": {"suppliercode": {"A", "B", "C", "D"}},
        "vendors": {"vendorcode": {"A", "B", "C", "E"}},
    }
    cands = hi.find_relationship_candidates(tables, key_values=key_values)
    c = _pair(cands, "purchases", "vendors")
    assert c is not None
    assert "sampled value overlap" in c["confidence_reason"]
    assert c["join_confidence"] >= 0.3


def test_relationship_value_overlap_below_threshold_excluded() -> None:
    tables = [
        _table("purchases", ["SupplierCode", "Amount"]),
        _table("vendors", ["VendorCode", "Name"]),
    ]
    key_values = {
        "purchases": {"suppliercode": {"A", "B", "C", "D", "E"}},
        "vendors": {"vendorcode": {"A", "Z", "Y", "X", "W"}},
    }
    # Only 1/5 overlap (0.2) < 0.3 → no candidate.
    assert hi.find_relationship_candidates(tables, key_values=key_values) == []


def test_relationship_same_name_measured_upgrade() -> None:
    # Same-name key with high sampled containment upgrades a Tier-3 match from
    # 0.6/unknown/medium to a measured one_to_many/low at the overlap.
    tables = [
        _table("suppliers", ["SupplierID", "SupplierName"]),
        _table("inspections", ["SupplierID", "DefectQty"]),
    ]
    suppliers = {f"S{i}" for i in range(10)}  # size 10
    # inspections contains 9 of the 10 supplier ids (plus extras) → 0.9.
    inspections = {f"S{i}" for i in range(9)} | {f"X{i}" for i in range(5)}
    key_values = {
        "suppliers": {"supplierid": suppliers},
        "inspections": {"supplierid": inspections},
    }
    cands = hi.find_relationship_candidates(tables, key_values=key_values)
    c = _pair(cands, "suppliers", "inspections")
    assert c is not None
    assert c["join_confidence"] == 0.9  # measured containment upgrades 0.6
    assert c["relationship_type"] == "one_to_many"
    assert c["row_multiplication_risk"] == "low"


def test_detect_view_strict_rejects_ambiguous() -> None:
    allowed = ["orders_v", "shipments_v"]
    assert hi._detect_view_strict("SELECT * FROM orders_v", allowed) == "orders_v"
    # zero matches
    assert hi._detect_view_strict("SELECT * FROM other", allowed) is None
    # multiple matches → ambiguous
    assert (
        hi._detect_view_strict(
            "SELECT * FROM orders_v JOIN shipments_v", allowed
        )
        is None
    )
    assert hi._detect_view_strict(None, allowed) is None


async def test_resolve_scope_links_maps_enabled_only(monkeypatch) -> None:
    # Enabled scope → link; disabled scope → ignored; never fabricates from
    # allowed_tables[0]. Uses a fake session returning scopes then queries.
    enabled = SimpleNamespace(
        query_id=1,
        target_query_id=2,
        source_field="OrderRef",
        target_field="ShipRef",
        created_by_ai=False,
    )
    queries = [
        SimpleNamespace(id=1, sql_text="SELECT * FROM orders_v"),
        SimpleNamespace(id=2, sql_text="SELECT * FROM shipments_v"),
    ]

    class _Scalars:
        def __init__(self, items):
            self._items = items

        def all(self):
            return self._items

    class _FakeSession:
        def __init__(self):
            self._calls = 0

        async def scalars(self, _stmt):
            self._calls += 1
            return _Scalars([enabled] if self._calls == 1 else queries)

    links = await hi._resolve_scope_links(
        _FakeSession(),
        project_id=1,
        allowed_tables=["orders_v", "shipments_v"],
    )
    assert len(links) == 1
    lk = links[0]
    assert {lk.left_table, lk.right_table} == {"orders_v", "shipments_v"}
    assert lk.left_column == "OrderRef"
    assert lk.created_by_ai is False


async def test_gather_project_context_fail_open_on_scope_error(
    monkeypatch,
) -> None:
    # If scope resolution raises, context is still returned (scope_links empty)
    # and tier-3 discovery still works downstream.
    async def boom(session, *, project_id, allowed_tables):
        raise RuntimeError("scope query failed")

    monkeypatch.setattr(hi, "_resolve_scope_links", boom)

    class _EmptyScalars:
        def all(self):
            return []

    class _FakeSession:
        async def scalars(self, _stmt):
            return _EmptyScalars()

    project = SimpleNamespace(id=1, name="P", tenant_id=1)
    ctx = await hi.gather_project_context(_FakeSession(), project)
    assert ctx.scope_links == []


def test_plan_reference_kpis_serializes_governed_catalog() -> None:
    ctx = hi.ProjectContext(
        tables=[],
        documents=[],
        reference_kpis=[
            {
                "kpi_key": "gross_margin_pct",
                "display_name": "Gross Margin %",
                "formula": "(Revenue - COGS) / Revenue",
                "description": "x" * 500,
                "required_fields": ["revenue", "cogs"],
                "optional_fields": ["region"],
                "recommended_chart_type": "kpi_grid",
            },
            {"kpi_key": "", "display_name": "", "formula": ""},  # dropped: no name
        ],
    )
    out = hi._plan_reference_kpis(ctx)
    assert len(out) == 1
    kpi = out[0]
    assert kpi["display_name"] == "Gross Margin %"
    assert kpi["formula"] == "(Revenue - COGS) / Revenue"
    assert kpi["required_fields"] == ["revenue", "cogs"]
    assert len(kpi["description"]) == 200  # bounded


def test_plan_reference_kpis_empty_by_default() -> None:
    ctx = hi.ProjectContext(tables=[], documents=[])
    assert hi._plan_reference_kpis(ctx) == []
