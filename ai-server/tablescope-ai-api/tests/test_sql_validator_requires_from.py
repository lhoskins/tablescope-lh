"""Tests that validate_sql rejects a query with no FROM/JOIN clause at all.

Live incident: a generated aggregate query (SUM/COUNT with a CASE WHEN) came
back with the aggregate expression present but the FROM clause missing
entirely. validate_sql's table-reference check only inspected tables it DID
find, so an empty match list (no FROM/JOIN anywhere) produced zero
violations and the malformed query reached Teiid, which rejected it with a
confusing "aggregate functions only allowed in ..." error instead of a clear
missing-table one.

Run from the ``tablescope-ai-api`` directory: ``pytest -q``.
"""

from __future__ import annotations

import pytest

from app.services.sql_validator import SQLValidationError, validate_sql

ALLOWED = ["it_backup_jobs_CSV"]


def test_rejects_aggregate_query_missing_from_clause() -> None:
    sql = (
        'SELECT SUM(CASE WHEN LOWER("Result") = LOWER(\'failed\') THEN 1 '
        "ELSE 0 END), COUNT(*)"
    )
    with pytest.raises(SQLValidationError) as exc:
        validate_sql(sql, ALLOWED)
    assert "FROM clause" in exc.value.reason


def test_rejects_simple_select_missing_from_clause() -> None:
    with pytest.raises(SQLValidationError) as exc:
        validate_sql('SELECT "Status"', ALLOWED)
    assert "FROM clause" in exc.value.reason


def test_accepts_query_with_from_clause() -> None:
    validate_sql(
        'SELECT SUM(CASE WHEN LOWER("Result") = LOWER(\'failed\') THEN 1 '
        'ELSE 0 END) AS FailedCount FROM "it_backup_jobs_CSV"',
        ALLOWED,
    )


def test_no_from_requirement_when_allowed_tables_is_empty() -> None:
    """Without allowed_tables the table-reference check is skipped entirely
    (existing behavior) -- the FROM requirement lives inside that same
    check and must not fire when it's off."""
    validate_sql("SELECT SUM(1)", [])


def test_rejects_outer_select_missing_from_when_cte_has_one() -> None:
    """Live incident, part 2: a repair rewrite came back as a CTE whose
    inner SELECT has a FROM, but the outer SELECT holding the actual
    aggregate expressions has none -- Teiid rejects this the same way as a
    query with no FROM anywhere, but the old whole-string check ("is there
    a FROM/JOIN token anywhere") missed it because the CTE's FROM counted
    as satisfying it."""
    sql = (
        'WITH sub AS (SELECT "Result" FROM "it_backup_jobs_CSV") '
        'SELECT SUM(CASE WHEN LOWER("Result") = LOWER(\'failed\') THEN 1 '
        "ELSE 0 END), COUNT(*)"
    )
    with pytest.raises(SQLValidationError) as exc:
        validate_sql(sql, ALLOWED)
    assert "FROM" in exc.value.reason


def test_accepts_outer_select_with_its_own_from_after_a_cte() -> None:
    sql = (
        'WITH sub AS (SELECT "Result" FROM "it_backup_jobs_CSV") '
        'SELECT SUM(CASE WHEN LOWER("Result") = LOWER(\'failed\') THEN 1 '
        "ELSE 0 END), COUNT(*) FROM sub"
    )
    validate_sql(sql, ALLOWED)


def test_rejects_union_branch_missing_its_own_from() -> None:
    """Each UNION branch is its own top-level query in Teiid -- a FROM in
    one branch does not satisfy another branch that has none."""
    sql = (
        'SELECT "Result" FROM "it_backup_jobs_CSV" '
        "UNION ALL "
        "SELECT SUM(1)"
    )
    with pytest.raises(SQLValidationError) as exc:
        validate_sql(sql, ALLOWED)
    assert "FROM" in exc.value.reason


def test_accepts_case_when_used_as_a_column_expression() -> None:
    """A CASE WHEN inside the SELECT list must not be mistaken for a nested
    top-level SELECT/branch boundary."""
    validate_sql(
        'SELECT CASE WHEN "Result" = \'failed\' THEN 1 ELSE 0 END AS Failed '
        'FROM "it_backup_jobs_CSV"',
        ALLOWED,
    )
