"""Tests for _fix_glued_keywords / _prepare_sql's defense against a CASE
expression's END landing with zero whitespace before the next clause
keyword.

Live finding: a "backup failure rate" query against it_backup_jobs_CSV
failed with TEIID31100 ("Encountered ... ENDORDER ...") because the
generated SQL had "...AS double) ENDORDER BY JobMonth" -- END glued
directly onto ORDER BY with no space, which Teiid's tokenizer reads as one
unrecognized identifier instead of two valid keywords. Confirmed this
isn't introduced anywhere else in the normalization pipeline:
_cast_timestampdiff and _auto_cast_aggregates only ever insert characters
around an existing span, never remove whitespace.

Run from ``platform-api``: ``pytest -q tests/test_fix_glued_keywords.py``.
"""

from __future__ import annotations

import pytest

from app.routes.query_sql_helpers import _fix_glued_keywords, _prepare_sql

pytestmark = pytest.mark.anyio


def test_fixes_end_glued_to_order_by():
    # Reproduces the exact reported fragment: END immediately followed by
    # ORDER BY with no space.
    glued = (
        'SELECT CAST(COUNT(*) AS double) ENDORDER BY JobMonth '
        'FROM "it_backup_jobs_CSV"'
    )
    fixed = _fix_glued_keywords(glued)
    assert "ENDORDER" not in fixed
    assert "END ORDER BY JobMonth" in fixed


def test_fixes_end_glued_to_group_by_where_having_limit():
    assert _fix_glued_keywords("SELECT 1 ENDGROUP BY x") == "SELECT 1 END GROUP BY x"
    assert _fix_glued_keywords("SELECT 1 ENDWHERE x = 1") == "SELECT 1 END WHERE x = 1"
    assert _fix_glued_keywords("SELECT 1 ENDHAVING x = 1") == "SELECT 1 END HAVING x = 1"
    assert _fix_glued_keywords("SELECT 1 ENDLIMIT 10") == "SELECT 1 END LIMIT 10"


def test_leaves_correctly_spaced_sql_unchanged():
    sql = (
        'SELECT CASE WHEN "x" = 1 THEN 1 ELSE 0 END AS y '
        'FROM t ORDER BY y'
    )
    assert _fix_glued_keywords(sql) == sql


def test_does_not_touch_end_as_part_of_a_longer_identifier():
    # "APPEND" etc. must not be mangled -- the match requires END immediately
    # followed by one of the clause keywords, not just the substring "end".
    sql = 'SELECT "AppendOrderBy" FROM t'
    assert _fix_glued_keywords(sql) == sql


async def test_prepare_sql_applies_the_fix_end_to_end():
    glued = (
        'SELECT CASE WHEN "x" = 1 THEN CAST(COUNT(*) AS double) ELSE 0 END '
        'AS JobMonth FROM "it_backup_jobs_CSV" ENDORDER BY JobMonth'
    )
    out = await _prepare_sql(
        glued, table_schema=[], column_types={}, column_samples={}
    )
    assert "ENDORDER" not in out
    assert "END ORDER BY JobMonth" in out
