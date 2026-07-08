"""Unit tests for AI generation-intent normalization + datasource detection.

Both are pure helpers in ``app.routes.ai_proxy`` that keep AI-generated tables
bound to a real datasource and route "generate/create/build query|table"
phrasings through the same read-only query-generation flow.
"""

from __future__ import annotations

import pytest

from app.routes.ai_proxy import (
    _detect_datasource,
    _is_query_summary_request,
    _normalize_source_name,
    _resolve_prompt_source,
    _score_source_match,
    normalize_ai_generation_intent,
)


@pytest.mark.parametrize(
    "prompt,expected_intent,expected_remainder",
    [
        ("generate table supplier performance", "table", "supplier performance"),
        ("create query top vendors", "query", "top vendors"),
        ("build table monthly spend", "table", "monthly spend"),
        ("please generate query revenue", "query", "revenue"),
        ("make table foo", "table", "foo"),
        # No verb prefix -> defaults to query intent, prompt unchanged.
        ("show me the top vendors", "query", "show me the top vendors"),
    ],
)
def test_normalize_ai_generation_intent(prompt, expected_intent, expected_remainder):
    intent, cleaned = normalize_ai_generation_intent(prompt)
    assert intent == expected_intent
    assert cleaned == expected_remainder


def test_normalize_intent_verb_only_keeps_original():
    # A bare verb with no remainder should not collapse to an empty prompt.
    intent, cleaned = normalize_ai_generation_intent("generate table")
    assert intent == "table"
    assert cleaned == "generate table"


def test_detect_datasource_matches_referenced_table():
    sql = 'SELECT * FROM "orders" WHERE total > 0'
    # Returns the first allowed table (list order) that appears in the SQL.
    assert _detect_datasource(sql, ["orders", "customers"]) == "orders"
    assert _detect_datasource(sql, ["customers", "orders"]) == "orders"


def test_detect_datasource_falls_back_to_first_allowed():
    # AI-generated tables must never be left with a blank source; when nothing
    # in the SQL matches, fall back to the first allowed table.
    sql = "SELECT 1"
    assert _detect_datasource(sql, ["orders", "customers"]) == "orders"


def test_detect_datasource_none_when_no_tables():
    assert _detect_datasource("SELECT 1", []) is None


# ── Fuzzy source-name matching (Issue 3) ──────────────────────────────────

def test_normalize_source_name_drops_suffix_and_separators():
    assert _normalize_source_name("fin_gl_chart_of_accounts_CSV") == (
        "fin gl chart of accounts"
    )
    assert _normalize_source_name("Sales_2024_XLSX") == "sales 2024"


def test_score_exact_and_suffix_insensitive():
    assert _score_source_match("orders_CSV", "orders_CSV") == 100
    # Requested name without the physical suffix → normalized exact match.
    assert _score_source_match(
        "fin_gl_chart_of_accounts", "fin_gl_chart_of_accounts_CSV"
    ) == 95
    # Spaces/free text normalizes to the same tokens.
    assert _score_source_match(
        "fin gl chart of accounts", "fin_gl_chart_of_accounts_CSV"
    ) == 95
    # A partial token subset ("chart of accounts") still scores as a match.
    assert _score_source_match(
        "chart of accounts", "fin_gl_chart_of_accounts_CSV"
    ) >= 60
    assert _score_source_match("totally unrelated", "orders_CSV") == 0


def test_resolve_prompt_source_single_strong_match():
    strong, close = _resolve_prompt_source(
        "fin_gl_chart_of_accounts",
        ["fin_gl_chart_of_accounts_CSV", "sales_orders_CSV"],
    )
    assert strong == ["fin_gl_chart_of_accounts_CSV"]
    assert close == []


def test_resolve_prompt_source_ambiguous_close_matches():
    # A generic phrase matching two sources by token subset → ambiguous.
    strong, close = _resolve_prompt_source(
        "chart of accounts",
        ["fin_gl_chart_of_accounts_CSV", "fin_gl_chart_of_accounts_archive_CSV"],
    )
    assert strong == []
    assert set(close) == {
        "fin_gl_chart_of_accounts_CSV",
        "fin_gl_chart_of_accounts_archive_CSV",
    }


# ── Query-summary intent detection (Issue 1) ──────────────────────────────

@pytest.mark.parametrize(
    "prompt",
    [
        "Can you give me a summary of my queries?",
        "summarize my queries",
        "list all queries",
        "give me an overview of the queries",
        "How many queries do I have?",
    ],
)
def test_is_query_summary_request_true(prompt):
    assert _is_query_summary_request(prompt) is True


@pytest.mark.parametrize(
    "prompt",
    [
        "create query fin_gl_chart_of_accounts",
        "show me revenue by month",
        "what is the total spend?",
        "",
    ],
)
def test_is_query_summary_request_false(prompt):
    assert _is_query_summary_request(prompt) is False
