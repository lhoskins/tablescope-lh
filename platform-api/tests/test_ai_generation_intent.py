"""Unit tests for AI generation-intent normalization + datasource detection.

Both are pure helpers in ``app.routes.ai_proxy`` that keep AI-generated tables
bound to a real datasource and route "generate/create/build query|table"
phrasings through the same read-only query-generation flow.
"""

from __future__ import annotations

import pytest

from app.routes.ai_proxy import (
    _detect_datasource,
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
