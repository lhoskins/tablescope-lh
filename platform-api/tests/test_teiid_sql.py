"""Tests for Teiid timestamp/date SQL normalization."""

from __future__ import annotations

import pytest

from app.services.teiid_sql import (
    date_mask_for_value,
    date_masks_from_samples,
    normalize_date_casts,
    normalize_teiid_string_filters,
    normalize_teiid_timestamps,
    rebuild_group_by_from_select,
)


@pytest.mark.parametrize(
    ("sql", "expected_substr"),
    [
        (
            "SELECT * FROM t WHERE d > CAST('2024-01-01' AS timestamp)",
            "PARSETIMESTAMP('2024-01-01', 'yyyy-MM-dd')",
        ),
        (
            "SELECT * FROM t WHERE d > CAST('2024-01-01' AS date)",
            "PARSEDATE('2024-01-01', 'yyyy-MM-dd')",
        ),
        (
            "SELECT * FROM t WHERE d > to_timestamp('2024-01-01')",
            "PARSETIMESTAMP('2024-01-01', 'yyyy-MM-dd')",
        ),
        (
            "SELECT * FROM t WHERE d > to_date('2024-01-01')",
            "PARSEDATE('2024-01-01', 'yyyy-MM-dd')",
        ),
        (
            "SELECT * FROM t WHERE d > to_timestamp('2024-01-01 13:45:00')",
            "PARSETIMESTAMP('2024-01-01 13:45:00', 'yyyy-MM-dd HH:mm:ss')",
        ),
        (
            "SELECT * FROM t WHERE d > to_timestamp('2024-01-01T13:45:00')",
            "PARSETIMESTAMP('2024-01-01T13:45:00', 'yyyy-MM-dd''T''HH:mm:ss')",
        ),
        (
            "SELECT * FROM t WHERE d > to_timestamp('2024-01-01T13:45:00Z')",
            "PARSETIMESTAMP('2024-01-01T13:45:00Z', 'yyyy-MM-dd''T''HH:mm:ss')",
        ),
        (
            "SELECT * FROM t WHERE d > to_timestamp('2024-01-01', 'YYYY-MM-DD')",
            "PARSETIMESTAMP('2024-01-01', 'yyyy-MM-dd')",
        ),
    ],
)
def test_normalize_timestamp_literals(sql: str, expected_substr: str) -> None:
    out = normalize_teiid_timestamps(sql)
    assert expected_substr in out


@pytest.mark.parametrize(
    ("sql", "expected_substr"),
    [
        (
            # The exact query reported failing in production.
            'SELECT COUNT(*) AS value_column FROM "it_change_requests_CSV" '
            "WHERE \"RiskLevel\" = 'High' AND \"Status\" <> 'Closed' "
            'AND "SubmittedDate" >= DATEADD(year, -1, CURRENT_DATE)',
            "TIMESTAMPADD(SQL_TSI_YEAR, -1, CURRENT_DATE)",
        ),
        (
            "SELECT DATEADD('month', -12, CURRENT_DATE()) FROM t",
            "TIMESTAMPADD(SQL_TSI_MONTH, -12, CURRENT_DATE())",
        ),
        (
            "SELECT DATEADD(day, 7, \"DueDate\") FROM t",
            'TIMESTAMPADD(SQL_TSI_DAY, 7, "DueDate")',
        ),
    ],
)
def test_normalize_rewrites_dateadd_to_timestampadd(sql: str, expected_substr: str) -> None:
    out = normalize_teiid_timestamps(sql)
    assert expected_substr in out
    assert "DATEADD" not in out.upper()


def test_normalize_dateadd_unknown_unit_left_unchanged() -> None:
    sql = "SELECT DATEADD(fortnight, 1, CURRENT_DATE) FROM t"
    assert normalize_teiid_timestamps(sql) == sql


@pytest.mark.parametrize(
    ("sql", "expected_substr"),
    [
        (
            "SELECT DATE_FORMAT(A.RenewalMonth, '%Y-%m') FROM t",
            "FORMATTIMESTAMP(A.RenewalMonth, 'yyyy-MM')",
        ),
        (
            'SELECT DATE_FORMAT("SubmittedDate", \'%Y-%m-%d\') FROM t',
            'FORMATTIMESTAMP("SubmittedDate", \'yyyy-MM-dd\')',
        ),
    ],
)
def test_normalize_rewrites_date_format_to_formattimestamp(
    sql: str, expected_substr: str
) -> None:
    out = normalize_teiid_timestamps(sql)
    assert expected_substr in out
    assert "DATE_FORMAT" not in out.upper()


def test_normalize_unknown_literal_left_unchanged() -> None:
    sql = "SELECT * FROM t WHERE d > CAST('not-a-date' AS timestamp)"
    assert normalize_teiid_timestamps(sql) == sql


def test_normalize_column_cast_with_sample() -> None:
    sql = 'SELECT * FROM t WHERE d > CAST("ShipDate" AS timestamp)'
    out = normalize_teiid_timestamps(sql, column_samples={"ShipDate": "1/19/2026"})
    assert "PARSETIMESTAMP(\"ShipDate\", 'M/d/yyyy')" in out


def test_normalize_column_cast_without_sample_left_unchanged() -> None:
    sql = 'SELECT * FROM t WHERE d > CAST("ShipDate" AS timestamp)'
    assert normalize_teiid_timestamps(sql) == sql


def test_date_mask_for_value() -> None:
    assert date_mask_for_value("2024-01-01") == "yyyy-MM-dd"
    assert date_mask_for_value("2024-01-01T13:45:00") == "yyyy-MM-dd''T''HH:mm:ss"
    assert date_mask_for_value("1/19/2026") == "M/d/yyyy"
    assert date_mask_for_value("not a date") is None


def test_date_masks_from_samples_uses_first_non_empty() -> None:
    out = date_masks_from_samples(
        [
            {"ShipDate": "1/19/2026", "DeliveryDate": "2/20/2026"},
            {"ShipDate": "3/21/2026"},
        ]
    )
    assert out == {
        "ShipDate": "M/d/yyyy",
        "DeliveryDate": "M/d/yyyy",
    }


def test_normalize_date_casts_known_columns() -> None:
    sql = 'SELECT * FROM t WHERE d > CAST("ShipDate" AS timestamp)'
    masks = {"ShipDate": "M/d/yyyy"}
    assert normalize_date_casts(sql, masks) == (
        "SELECT * FROM t WHERE d > PARSETIMESTAMP(\"ShipDate\", 'M/d/yyyy')"
    )


def test_normalize_date_casts_ignores_unknown_columns() -> None:
    sql = 'SELECT * FROM t WHERE d > CAST("OtherDate" AS timestamp)'
    assert normalize_date_casts(sql, {"ShipDate": "M/d/yyyy"}) == sql


def test_normalize_string_filter_case_insensitive() -> None:
    schema = [{"table": "t", "columns": [{"name": "Status", "type": "string"}]}]
    sql = 'SELECT * FROM t WHERE "Status" = \'failed\''
    out = normalize_teiid_string_filters(sql, schema)
    assert 'LOWER("Status") = LOWER(\'failed\')' in out


def test_normalize_string_filter_ignores_numeric_columns() -> None:
    schema = [{"table": "t", "columns": [{"name": "Amount", "type": "double"}]}]
    sql = 'SELECT * FROM t WHERE "Amount" = \'100\''
    assert normalize_teiid_string_filters(sql, schema) == sql


def test_normalize_string_filter_handles_in_lists() -> None:
    schema = [{"table": "t", "columns": [{"name": "Result", "type": "string"}]}]
    sql = 'SELECT * FROM t WHERE "Result" IN (\'failed\', \'success\')'
    out = normalize_teiid_string_filters(sql, schema)
    assert 'LOWER("Result") IN (LOWER(\'failed\'), LOWER(\'success\'))' in out


def test_rebuild_group_by_drops_aggregate_and_double_wrap() -> None:
    sql = (
        'SELECT PARSETIMESTAMP("Month", \'yyyy-MM-dd\') AS "month", '
        'SUM(CAST("RevenueUSD" AS double)) AS total_revenue '
        'FROM "monthly_review_metrics_CSV" '
        'GROUP BY PARSETIMESTAMP(PARSETIMESTAMP("Month", \'yyyy-MM-dd\'), \'M/d/yyyy\'), '
        'SUM(CAST("RevenueUSD" AS double)) '
        'ORDER BY PARSETIMESTAMP("Month", \'yyyy-MM-dd\')'
    )
    out = rebuild_group_by_from_select(sql)
    assert 'GROUP BY PARSETIMESTAMP("Month", \'yyyy-MM-dd\')' in out
    assert 'SUM(CAST("RevenueUSD" AS double))' not in out.split("GROUP BY")[1].split("ORDER BY")[0]
    assert 'PARSETIMESTAMP(PARSETIMESTAMP' not in out
    assert 'ORDER BY PARSETIMESTAMP("Month", \'yyyy-MM-dd\')' in out


def test_rebuild_group_by_multiple_non_aggregate_columns() -> None:
    sql = 'SELECT "Region", "Month", SUM("Sales") FROM t GROUP BY "Month", "Region"'
    out = rebuild_group_by_from_select(sql)
    # Rebuilt GROUP BY follows the SELECT order of non-aggregate expressions.
    gb = out.split("GROUP BY")[1].strip()
    assert gb.startswith('"Region", "Month"')


def test_rebuild_group_by_no_aggregates_removes_group_by() -> None:
    sql = 'SELECT "Region", "Month" FROM t GROUP BY "Region", "Month"'
    out = rebuild_group_by_from_select(sql)
    assert "GROUP BY" not in out.upper()


def test_rebuild_group_by_already_correct_unchanged() -> None:
    sql = 'SELECT "Month", SUM("Sales") FROM t GROUP BY "Month"'
    out = rebuild_group_by_from_select(sql)
    assert out == sql


def test_rebuild_group_by_maps_order_by_alias() -> None:
    sql = (
        'SELECT "Month" AS sales_month, SUM("Sales") FROM t '
        'GROUP BY "Month" ORDER BY sales_month'
    )
    out = rebuild_group_by_from_select(sql)
    # Alias in ORDER BY is left as-is because Teiid supports it.
    assert "ORDER BY sales_month" in out
