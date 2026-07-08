"""Tests for Teiid aggregate/type auto-casting in the query path.

Teiid imports CSV columns as strings and returns TIMESTAMPDIFF as bigint; both
need CAST(... AS double) so aggregations decode correctly over the pg wire.
"""

from __future__ import annotations

from app.routes.query import _auto_cast_aggregates, _cast_timestampdiff

TD = (
    'TIMESTAMPDIFF(SQL_TSI_DAY, PARSETIMESTAMP("ShipDate", \'M/d/yyyy\'), '
    'PARSETIMESTAMP("DeliveryDate", \'M/d/yyyy\'))'
)


def test_casts_bare_column_aggregate() -> None:
    assert _auto_cast_aggregates('SELECT SUM("qty") FROM t') == (
        'SELECT SUM(CAST("qty" AS double)) FROM t'
    )


def test_leaves_already_cast_aggregate() -> None:
    sql = 'SELECT AVG(CAST("qty" AS double)) FROM t'
    assert _auto_cast_aggregates(sql) == sql


def test_wraps_timestampdiff_in_cast() -> None:
    out = _cast_timestampdiff(f"SELECT AVG({TD}) FROM t")
    assert f"CAST({TD} AS double)" in out
    # The nested PARSETIMESTAMP calls are preserved intact.
    assert out.count("PARSETIMESTAMP") == 2


def test_does_not_double_wrap_timestampdiff() -> None:
    already = f"SELECT AVG(CAST({TD} AS double)) FROM t"
    assert _cast_timestampdiff(already) == already


def test_auto_cast_fixes_aggregated_timestampdiff() -> None:
    # The full path the executor applies: an un-CAST aggregated day count.
    raw = f"SELECT Carrier, AVG({TD}) AS d FROM t GROUP BY Carrier"
    out = _auto_cast_aggregates(raw)
    assert f"AVG(CAST({TD} AS double))" in out


def test_timestampdiff_without_aggregate_still_cast() -> None:
    # Bare selection is cast too (harmless bigint->double) and is idempotent.
    out = _cast_timestampdiff(f"SELECT {TD} AS d FROM t")
    assert out == f"SELECT CAST({TD} AS double) AS d FROM t"


def test_no_timestampdiff_is_unchanged() -> None:
    sql = 'SELECT COUNT(*) FROM t WHERE "Carrier" = \'DHL\''
    assert _cast_timestampdiff(sql) == sql
