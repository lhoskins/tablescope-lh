"""Tests for the shared conversational ask pipeline."""

from __future__ import annotations

from app.services.ask_pipeline import (
    build_insight_followup,
    chart_config,
    followup_prompt,
    resolve_presentation,
)
from app.services.visualization_engine import ChartType, VizDecision


def _matrix_rows():
    return [
        {"region": f"R{i}", "product": f"P{j}", "revenue": i * j + 5}
        for i in range(8)
        for j in range(12)
    ]


def _series_rows():
    return [{"month": f"2026-{m:02d}", "revenue": 100 + m} for m in range(1, 13)]


# ── Chart resolution shares the insight ranker ───────────────────────────────


def test_empty_result_is_a_table_not_an_error():
    assert resolve_presentation([], []).chart == {"type": "table"}
    assert resolve_presentation(["a"], []).chart == {"type": "table"}


def test_time_series_resolves_to_a_line_in_chat():
    pres = resolve_presentation(["month", "revenue"], _series_rows())
    assert pres.chart["type"] == "line"
    assert pres.chart["labelColumn"] == "month"
    assert pres.chart["valueColumns"] == ["revenue"]


def test_matrix_resolves_to_heatmap_not_a_narrowed_bar():
    """The old surface map collapsed everything to kpi/table/line/bar/pie."""
    pres = resolve_presentation(["region", "product", "revenue"], _matrix_rows())
    assert pres.chart["type"] == "heatmap"


def test_two_measures_resolve_to_scatter_not_table():
    """`_ASK_AND_RUN_SURFACE` mapped SCATTER -> "table"; chat lost the chart."""
    rows = [{"price": i * 1.5, "volume": 100 - i} for i in range(60)]
    pres = resolve_presentation(["price", "volume"], rows)
    assert pres.chart["type"] == "scatter"


def test_chat_gets_ranked_alternatives_for_the_chart_picker():
    pres = resolve_presentation(["region", "product", "revenue"], _matrix_rows())
    assert 1 < len(pres.candidates) <= 6
    families = [c["decision"]["chartType"] for c in pres.candidates]
    assert families[0] == pres.chart["type"]
    assert len(set(families)) > 1  # genuinely diverse, not six of one family


def test_suggestion_limit_is_honoured():
    pres = resolve_presentation(
        ["region", "product", "revenue"], _matrix_rows(), suggestion_limit=3
    )
    assert len(pres.candidates) <= 3


def test_ranking_failure_degrades_to_a_table(monkeypatch):
    import app.services.ask_pipeline as ap

    def boom(*_a, **_kw):
        raise RuntimeError("ranker exploded")

    monkeypatch.setattr(ap, "rank_visualizations", boom)
    assert resolve_presentation(["a", "b"], [{"a": 1, "b": 2}]).chart == {"type": "table"}


# ── Chart config contract (what chat already renders) ────────────────────────


def test_chart_config_preserves_the_existing_contract():
    decision = VizDecision(
        chart_type=ChartType.BAR,
        chart_style="horizontal_bar",
        x_field="plant",
        y_field="defects",
        value_format="count",
        top_n=12,
    )
    cfg = chart_config(decision, ["plant", "defects"])
    assert cfg == {
        "type": "bar",
        "subtype": "horizontal_bar",
        "labelColumn": "plant",
        "valueColumns": ["defects"],
        "topN": 12,
        "valueFormat": "count",
    }


def test_chart_config_emits_metric_field_for_kpi():
    decision = VizDecision(chart_type=ChartType.KPI, y_field="revenue")
    cfg = chart_config(decision, ["revenue"])
    assert cfg["metricField"] == "revenue"


def test_chart_config_drops_fields_absent_from_the_result():
    decision = VizDecision(chart_type=ChartType.LINE, x_field="ghost", y_field="revenue")
    cfg = chart_config(decision, ["revenue"])
    assert "labelColumn" not in cfg
    assert cfg["valueColumns"] == ["revenue"]


def test_dual_axis_decision_carries_both_measures():
    decision = VizDecision(
        chart_type=ChartType.COMBO, x_field="month", y_field="revenue", y2_field="margin"
    )
    cfg = chart_config(decision, ["month", "revenue", "margin"])
    assert cfg["valueColumns"] == ["revenue", "margin"]


# ── Asking about an insight card ─────────────────────────────────────────────


def test_no_card_leaves_the_question_untouched():
    fu = build_insight_followup("why did revenue drop?", None)
    assert fu.context == ""
    assert followup_prompt(fu) == "why did revenue drop?"


def test_card_context_grounds_the_follow_up():
    card = {
        "title": "Revenue: year over year",
        "summary": "Revenue fell 12% versus last year.",
        "sql": "SELECT month, SUM(revenue) FROM sales GROUP BY month",
        "sources": {"tables": ["sales"]},
        "analyticalMethod": {
            "intent": "compare_year_over_year",
            "method": "period_change",
            "executionEngine": "r",
            "usableN": 24,
            "warnings": ["Partial current period"],
        },
    }
    fu = build_insight_followup("which region drove it?", card)
    assert fu.intent == "compare_year_over_year"
    assert fu.base_sql.startswith("SELECT month")
    prompt = followup_prompt(fu)
    assert "Revenue: year over year" in prompt
    assert "period_change" in prompt
    assert "executed in R" in prompt
    assert "24 observations" in prompt
    assert "Partial current period" in prompt
    assert "sales" in prompt
    assert prompt.endswith("Question: which region drove it?")
    # The guard that keeps a follow-up on topic.
    assert "do not change the subject" in prompt


def test_card_without_provenance_still_grounds_on_title_and_summary():
    card = {"title": "Scrap rate by plant", "summary": "Plant B is highest."}
    prompt = followup_prompt(build_insight_followup("why?", card))
    assert "Scrap rate by plant" in prompt
    assert "Plant B is highest." in prompt


def test_python_executed_card_is_not_described_as_r():
    card = {
        "title": "t",
        "analyticalMethod": {"method": "pearson_correlation", "executionEngine": "python"},
    }
    prompt = followup_prompt(build_insight_followup("q", card))
    assert "pearson_correlation" in prompt
    assert "executed in R" not in prompt
