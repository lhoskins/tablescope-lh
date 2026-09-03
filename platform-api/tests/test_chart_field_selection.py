"""Tests for _build_chart_config's suggested-visualization -> chart-config
normalization, focused on the combo (bar+line) y2Field gap.

Live finding: "Show me the incidents open vs resolve by month for year
2026" rendered a bar+line combo chart where both series showed the same
number (OpenCount) instead of bar=OpenCount, line=ResolvedCount. The data
table was correct; only the chart was wrong. Root cause: _build_chart_config
only ever kept a single-element valueColumns list, ignoring the
visualization engine's y2Field (recommend.py's y2_field) entirely -- so
every combo chart's second series was undefined, and the frontend's
fallback for a missing second series (build-combo-option.ts) duplicates the
first series rather than erroring, silently rendering a wrong-but-plausible
chart instead of failing loudly.

Run from ``platform-api``: ``pytest -q tests/test_chart_field_selection.py``.
"""

from __future__ import annotations

from app.services.conversational_analytics.chart_field_selection import (
    _build_chart_config,
)


def test_combo_chart_keeps_both_value_columns():
    suggested = {
        "type": "combo",
        "chartStyle": "bar_line",
        "xField": "OpenedMonth",
        "yField": "OpenCount",
        "y2Field": "ResolvedCount",
    }
    columns = ["OpenedMonth", "OpenCount", "ResolvedCount"]
    rows = [{"OpenedMonth": "2026-01", "OpenCount": 4, "ResolvedCount": 4}]

    config = _build_chart_config(suggested, columns, rows)

    assert config["valueColumns"] == ["OpenCount", "ResolvedCount"]


def test_y2_field_not_in_columns_is_dropped_not_guessed():
    suggested = {
        "type": "combo",
        "xField": "OpenedMonth",
        "yField": "OpenCount",
        "y2Field": "NotARealColumn",
    }
    columns = ["OpenedMonth", "OpenCount"]
    rows = [{"OpenedMonth": "2026-01", "OpenCount": 4}]

    config = _build_chart_config(suggested, columns, rows)

    assert config["valueColumns"] == ["OpenCount"]


def test_y2_field_same_as_y_field_is_not_duplicated():
    suggested = {
        "type": "combo",
        "xField": "OpenedMonth",
        "yField": "OpenCount",
        "y2Field": "OpenCount",
    }
    columns = ["OpenedMonth", "OpenCount"]
    rows = [{"OpenedMonth": "2026-01", "OpenCount": 4}]

    config = _build_chart_config(suggested, columns, rows)

    assert config["valueColumns"] == ["OpenCount"]


def test_single_series_bar_chart_unaffected_by_missing_y2_field():
    suggested = {"type": "bar", "xField": "Category", "yField": "Count"}
    columns = ["Category", "Count"]
    rows = [{"Category": "Network", "Count": 4}]

    config = _build_chart_config(suggested, columns, rows)

    assert config["valueColumns"] == ["Count"]
