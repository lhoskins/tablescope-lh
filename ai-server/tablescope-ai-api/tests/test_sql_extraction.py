"""Tests for SQL-only extraction and the read-only statement guard.

Run from the ``tablescope-ai-api`` directory: ``pytest -q``.
"""

from __future__ import annotations

import pytest

from app.routers.ai import _extract_sql
from app.services.sql_validator import SQLValidationError, validate_sql

ALLOWED = ["SUP_Quality_Inspections_CSV", "SUP_Suppliers_CSV"]


def test_strips_leading_prose() -> None:
    raw = (
        "To calculate the defect rate, we group inspections by supplier:\n"
        'SELECT s."name" FROM SUP_Suppliers_CSV s'
    )
    out = _extract_sql(raw)
    assert out == 'SELECT s."name" FROM SUP_Suppliers_CSV s'
    assert "To calculate" not in out


def test_strips_markdown_fence() -> None:
    raw = "Here you go:\n```sql\nSELECT \"x\" FROM SUP_Suppliers_CSV\n```\nDone."
    assert _extract_sql(raw) == 'SELECT "x" FROM SUP_Suppliers_CSV'


def test_drops_trailing_prose_and_second_statement() -> None:
    raw = (
        'SELECT "x" FROM SUP_Suppliers_CSV; -- then explain\n'
        "This shows suppliers."
    )
    assert _extract_sql(raw) == 'SELECT "x" FROM SUP_Suppliers_CSV'


def test_keeps_with_cte() -> None:
    raw = (
        "The query uses a CTE.\n"
        'WITH t AS (SELECT "a" FROM SUP_Suppliers_CSV) SELECT "a" FROM t'
    )
    out = _extract_sql(raw)
    assert out.startswith("WITH t AS")


def test_ignores_bare_with_in_prose() -> None:
    raw = "With the data available, here is the query: SELECT \"x\" FROM SUP_Suppliers_CSV"
    out = _extract_sql(raw)
    assert out == 'SELECT "x" FROM SUP_Suppliers_CSV'


def test_returns_empty_when_no_sql() -> None:
    assert _extract_sql("I cannot answer this from the available data.") == ""
    assert _extract_sql("") == ""


def test_validate_rejects_prose_prefixed_sql() -> None:
    with pytest.raises(SQLValidationError):
        validate_sql(
            'To calculate: SELECT "x" FROM SUP_Suppliers_CSV', ALLOWED
        )


def test_validate_allows_leading_comment() -> None:
    validate_sql(
        '-- top suppliers\nSELECT "x" FROM SUP_Suppliers_CSV', ALLOWED
    )
