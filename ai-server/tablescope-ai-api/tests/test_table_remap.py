"""Tests for deterministic table-reference remapping in SQL generation.

Run from the ``tablescope-ai-api`` directory: ``pytest -q``.
"""

from __future__ import annotations

from app.routers.ai import _remap_tables_to_authorized

ALLOWED = [
    "SUP_Quality_Inspections_CSV",
    "SUP_Suppliers_CSV",
    "LOG_Shipments_CSV",
]


def test_remaps_missing_csv_suffix() -> None:
    sql = (
        'SELECT q."defect_count" FROM SUP_Quality_Inspections q '
        'JOIN SUP_Suppliers s ON s."id" = q."supplier_id"'
    )
    out = _remap_tables_to_authorized(sql, ALLOWED)
    assert "FROM SUP_Quality_Inspections_CSV q" in out
    assert "JOIN SUP_Suppliers_CSV s" in out
    assert "SUP_Quality_Inspections " not in out  # bare (non-suffixed) form gone


def test_remaps_quoted_reference() -> None:
    sql = 'SELECT "x" FROM "SUP_Suppliers"'
    out = _remap_tables_to_authorized(sql, ALLOWED)
    assert out == 'SELECT "x" FROM "SUP_Suppliers_CSV"'


def test_leaves_authorized_reference_untouched() -> None:
    sql = 'SELECT "x" FROM SUP_Suppliers_CSV'
    assert _remap_tables_to_authorized(sql, ALLOWED) == sql


def test_leaves_unmatched_reference_untouched() -> None:
    sql = 'SELECT "x" FROM totally_unrelated_source'
    assert _remap_tables_to_authorized(sql, ALLOWED) == sql


def test_noop_without_allowed_tables() -> None:
    sql = "SELECT 1 FROM foo"
    assert _remap_tables_to_authorized(sql, []) == sql


def test_invented_table_remapped_to_single_resolved_source() -> None:
    # The model invented a table name with no fuzzy match; the resolver had
    # already auto-selected one source, so the unknown reference is remapped to
    # it rather than left to fail validation.
    sql = 'SELECT SUM("Amount") AS spend FROM transactions'
    out = _remap_tables_to_authorized(
        sql, ALLOWED, preferred_sources=["LOG_Shipments_CSV"]
    )
    assert out == 'SELECT SUM("Amount") AS spend FROM LOG_Shipments_CSV'


def test_invented_table_not_forced_when_multiple_sources_resolved() -> None:
    # With more than one resolved source we cannot safely guess which one an
    # invented name meant, so it is left untouched (real joins stay intact).
    sql = "SELECT 1 FROM transactions"
    out = _remap_tables_to_authorized(
        sql, ALLOWED, preferred_sources=["LOG_Shipments_CSV", "SUP_Suppliers_CSV"]
    )
    assert out == sql


def test_fuzzy_match_still_wins_over_forced_source() -> None:
    # A confident suffix-drop match is used even when a preferred source exists.
    sql = "SELECT 1 FROM SUP_Suppliers"
    out = _remap_tables_to_authorized(
        sql, ALLOWED, preferred_sources=["LOG_Shipments_CSV"]
    )
    assert "FROM SUP_Suppliers_CSV" in out
