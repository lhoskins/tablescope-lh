"""Tests for insight-card retrieval by title.

The failure these guard against: asking "show me the query for <card title>"
returned an *invented* SQL query, because no ask path could look a card up.
"""

from __future__ import annotations

from app.services.insight_registry import (
    InsightRef,
    extract_title_fragment,
    format_ambiguous,
    format_insight_context,
    insight_catalog_context,
    resolve_insight_reference,
    score_title,
)

CARDS = [
    {
        "title": "Material Costs vs Revenue Trend",
        "summary": "Material costs rose while revenue flattened.",
        "sql": "SELECT month, SUM(material_costs) AS mc FROM monthly_review_metrics GROUP BY month",
        "sources": {"tables": ["monthly_review_metrics"]},
        "result": {"columns": ["month", "mc"]},
        "analyticalMethod": {
            "method": "pearson_correlation",
            "executionEngine": "r",
            "usableN": 24,
        },
        "group": "analysis",
    },
    {
        "title": "Revenue: year over year",
        "summary": "Revenue fell 12% versus last year.",
        "sql": "SELECT month, SUM(revenue) FROM executive_kpi_scorecard_monthly GROUP BY month",
        "sources": {"tables": ["executive_kpi_scorecard_monthly"]},
    },
    {
        "title": "Scrap rate by plant",
        "summary": "Plant B is highest.",
        "sql": "SELECT plant, AVG(scrap_rate) FROM production GROUP BY plant",
    },
]


# ── Recognising that a question names a card ─────────────────────────────────


def test_extracts_title_after_the_label_form_users_actually_type():
    frag = extract_title_fragment(
        "Please display query for Business Insight Title: Material Costs vs Revenue Trend"
    )
    assert frag == "Material Costs vs Revenue Trend"


def test_extracts_quoted_title():
    assert extract_title_fragment('show me the sql for "Scrap rate by plant"') == "Scrap rate by plant"


def test_extracts_trailing_reference():
    assert extract_title_fragment("what is the query for Scrap rate by plant") == "Scrap rate by plant"


def test_no_reference_returns_empty():
    assert extract_title_fragment("what were revenues last quarter?") == ""


# ── Matching ─────────────────────────────────────────────────────────────────


def test_exact_title_resolves():
    m = resolve_insight_reference(
        "Business Insight Title: Material Costs vs Revenue Trend", CARDS
    )
    assert m.resolved
    assert m.match.title == "Material Costs vs Revenue Trend"


def test_a_distinctive_fragment_is_enough():
    """The user should only have to type part of the title when it is unique."""
    m = resolve_insight_reference("show me the query for material costs", CARDS)
    assert m.resolved
    assert m.match.title == "Material Costs vs Revenue Trend"


def test_case_and_spacing_are_ignored():
    m = resolve_insight_reference('the "SCRAP RATE BY PLANT" card', CARDS)
    assert m.resolved
    assert m.match.title == "Scrap rate by plant"


def test_unrelated_question_matches_nothing():
    assert not resolve_insight_reference("how many suppliers are late?", CARDS).resolved


def test_empty_card_list_is_safe():
    assert not resolve_insight_reference("anything", []).resolved


def test_ambiguous_fragment_is_reported_not_guessed():
    cards = [
        {"title": "Revenue: year over year"},
        {"title": "Revenue: month over month"},
    ]
    m = resolve_insight_reference("show me the query for revenue", cards)
    assert not m.resolved
    assert len(m.ambiguous) == 2


def test_scoring_prefers_containment_over_word_overlap():
    assert score_title("material costs", "Material Costs vs Revenue Trend") > score_title(
        "revenue trend costs", "Material Costs vs Revenue Trend"
    )
    assert score_title("", "anything") == 0.0
    assert score_title("x", "") == 0.0


# ── Grounding text ───────────────────────────────────────────────────────────


def test_context_quotes_the_stored_sql_and_forbids_inventing_one():
    ref = InsightRef(card=CARDS[0], score=1.0, title=CARDS[0]["title"])
    ctx = format_insight_context(ref)
    assert "SELECT month, SUM(material_costs)" in ctx
    assert "do NOT write a different query" in ctx
    assert "monthly_review_metrics" in ctx
    assert "pearson_correlation" in ctx
    assert "executed in R" in ctx
    assert "24" in ctx
    assert "month, mc" in ctx


def test_card_without_sql_says_so_rather_than_inviting_invention():
    ref = InsightRef(card={"title": "Doc finding", "summary": "s"}, score=1.0, title="Doc finding")
    ctx = format_insight_context(ref)
    assert "no stored SQL" in ctx
    assert "instead of inventing one" in ctx
    assert "```sql" not in ctx


def test_ambiguous_text_asks_rather_than_answers():
    text = format_ambiguous(["Revenue: year over year", "Revenue: month over month"])
    assert "Ask the user which one" in text
    assert "- Revenue: year over year" in text


def test_catalog_lists_available_cards():
    catalog = insight_catalog_context(CARDS)
    assert "Material Costs vs Revenue Trend" in catalog
    assert "Scrap rate by plant" in catalog
    assert "[analysis]" in catalog


def test_catalog_is_empty_when_there_are_no_cards():
    assert insight_catalog_context([]) == ""
    assert insight_catalog_context([{"summary": "no title"}]) == ""


# ── Retrieval vs generation ──────────────────────────────────────────────────


def test_query_requests_are_recognised_as_retrieval():
    from app.services.insight_registry import is_query_request

    for q in [
        "Please display query for Business Insight Title: Material Costs vs Revenue Trend",
        "show me the sql for scrap rate",
        "what is the query for revenue",
        "can I see the SQL statement for that card",
    ]:
        assert is_query_request(q) is True, q


def test_analytical_questions_are_not_retrieval():
    from app.services.insight_registry import is_query_request

    for q in ["why did revenue drop?", "break this down by region", "forecast next quarter"]:
        assert is_query_request(q) is False, q


def test_stored_query_answer_returns_the_real_sql():
    from app.services.insight_registry import stored_query_answer

    ref = InsightRef(card=CARDS[0], score=1.0, title=CARDS[0]["title"])
    ans = stored_query_answer(ref)
    assert ans is not None
    assert ans["sql"] == CARDS[0]["sql"]
    assert ans["status"] == "success"
    assert ans["retrievedFromInsight"] == "Material Costs vs Revenue Trend"


def test_card_without_sql_yields_no_fabricated_answer():
    from app.services.insight_registry import stored_query_answer

    ref = InsightRef(card={"title": "Doc finding"}, score=1.0, title="Doc finding")
    assert stored_query_answer(ref) is None


def test_build_insight_context_routes_to_the_right_grounding():
    from app.services.insight_registry import build_insight_context

    # Named card -> its stored SQL.
    ctx = build_insight_context("query for material costs", CARDS)
    assert "SELECT month, SUM(material_costs)" in ctx
    # Generic insight question -> the catalog.
    catalog = build_insight_context("what insights do we have?", CARDS)
    assert "Material Costs vs Revenue Trend" in catalog
    # Unrelated question -> no grounding, so ordinary answers are unaffected.
    assert build_insight_context("how many suppliers are late?", CARDS) == ""
