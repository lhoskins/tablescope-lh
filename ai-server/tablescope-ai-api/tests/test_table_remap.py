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
