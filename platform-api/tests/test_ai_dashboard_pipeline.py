"""Unit tests for the insight-first AI dashboard pipeline helpers.

Covers the judge (drop empty/weak widgets), chart-type mapping + aiChartType
preservation, chart correction, and join-quality metadata as described in the
dashboard best-practices reference and implementation plan.
"""

from __future__ import annotations

from app.routes import ai_proxy as ap


def test_map_widget_visual_preserves_rich_types() -> None:
    # Advanced planner types map to a renderer-compatible (type, subtype) pair.
    assert ap._map_widget_visual("horizontal_bar") == ("bar", "horizontal_bar")
    assert ap._map_widget_visual("dual_line") == ("line", "biaxial_line")
    assert ap._map_widget_visual("donut") == ("pie", "donut")
    assert ap._map_widget_visual("gauge") == ("pie", "gauge")
    # Unknown types fall back to a safe default rather than raising.
    assert ap._map_widget_visual("made_up_chart") == ("bar", "column")


def test_judge_drops_zero_row_widgets() -> None:
    keep, reason = ap._judge_widget({"type": "bar"}, ["Supplier", "Defects"], [])
    assert keep is False
    assert "no rows" in reason


def test_judge_drops_missing_value_column() -> None:
    widget = {"type": "bar", "value_column": "Defects"}
    keep, reason = ap._judge_widget(
        widget, ["Supplier", "Total"], [{"Supplier": "A", "Total": 3}]
    )
    assert keep is False
    assert "missing" in reason


def test_judge_drops_all_null_metric() -> None:
    widget = {"type": "bar", "value_column": "Defects"}
    rows = [{"Supplier": "A", "Defects": None}, {"Supplier": "B", "Defects": None}]
    keep, reason = ap._judge_widget(widget, ["Supplier", "Defects"], rows)
    assert keep is False
    assert "null" in reason


def test_judge_drops_short_time_series() -> None:
    widget = {"type": "line", "value_column": "Defects"}
    rows = [{"Period": "2026-01", "Defects": 3}, {"Period": "2026-02", "Defects": 5}]
    keep, reason = ap._judge_widget(widget, ["Period", "Defects"], rows)
    assert keep is False
    assert "periods" in reason


def test_judge_keeps_strong_widget() -> None:
    widget = {"type": "bar", "value_column": "Defects"}
    rows = [
        {"Supplier": "A", "Defects": 3},
        {"Supplier": "B", "Defects": 5},
    ]
    keep, reason = ap._judge_widget(widget, ["Supplier", "Defects"], rows)
    assert keep is True
    assert reason == ""


def test_correct_widget_converts_oversized_pie() -> None:
    widget = {"type": "pie", "label_column": "Supplier", "value_column": "Spend"}
    rows = [{"Supplier": f"S{i}", "Spend": i} for i in range(10)]
    ap._correct_widget_chart(widget, ["Supplier", "Spend"], rows)
    assert widget["type"] == "horizontal_bar"


def test_build_join_metadata_from_relationship_plan() -> None:
    widget = {
        "title": "Defects by supplier spend",
        "sql": 'SELECT s."Name", q."Defects" FROM "Suppliers" s '
        'JOIN "Quality" q ON s."SupplierID" = q."SupplierID"',
        "relationship_plan": {
            "requires_join": True,
            "left_table": "Suppliers",
            "right_table": "Quality",
            "left_join_key": "SupplierID",
            "right_join_key": "SupplierID",
            "relationship_type": "one_to_many",
            "join_confidence": 0.9,
            "confidence_reason": "exact key match",
            "row_multiplication_risk": "low",
        },
    }
    meta = ap._build_join_metadata(widget)
    assert meta is not None
    assert meta["requiresJoin"] is True
    assert meta["leftTable"] == "Suppliers"
    assert meta["relationshipType"] == "one_to_many"
    assert meta["joinConfidence"] == 0.9
    assert meta["validated"] is False


def test_build_join_metadata_best_effort_from_sql() -> None:
    # A JOIN with no planner metadata still gets best-effort metadata.
    widget = {
        "title": "joined",
        "sql": 'SELECT a."x", b."y" FROM "A" a JOIN "B" b ON a."k" = b."k"',
    }
    meta = ap._build_join_metadata(widget)
    assert meta is not None
    assert meta["requiresJoin"] is True
    assert meta["relationshipType"] == "unknown"


def test_build_join_metadata_none_for_single_table() -> None:
    widget = {"title": "simple", "sql": 'SELECT "x" FROM "A"'}
    assert ap._build_join_metadata(widget) is None
