"""_render_preview_widgets must sync a widget's displayed chartType with the
actually-rendered, grounded chart -- not leave it frozen at the LLM's raw,
unvalidated guess.

Live report: a combo widget (revenue vs. backlog over time) rendered with
two real series, but the review UI still showed "dual_line" -- the LLM's
original chart_type field -- even though hi._build_chart correctly grounds
a "dual_line" hint into {"type": "combo", "subtype": "bar_line"} for a
two-metric time series (chart_builder.py's _two_value_chart). The nested
``chart`` dict had the right values; the widget-level ``chartType`` field
(what the UI actually displays) was set once from the raw guess and never
updated after grounding.

Run from ``platform-api``:
``pytest -q tests/test_dashboard_suggest_preview_chart_type.py``.
"""

from __future__ import annotations

import pytest

from app.routes.ai_proxy_dashboard_suggest import _render_preview_widgets

pytestmark = pytest.mark.anyio


_ROWS = [
    {"Month": "2026-06", "RevenueUSD": 6700000.0, "BacklogUSD": 2090000.0},
    {"Month": "2026-07", "RevenueUSD": 6750000.0, "BacklogUSD": 2040000.0},
    {"Month": "2026-08", "RevenueUSD": 6720000.0, "BacklogUSD": 2330000.0},
]


async def _fake_runner(sql: str) -> dict:
    return {"columns": ["Month", "RevenueUSD", "BacklogUSD"], "rows": _ROWS}


async def test_widget_chart_type_is_synced_to_the_grounded_combo_chart():
    widgets = await _render_preview_widgets(
        _fake_runner,
        [
            {
                "title": "Revenue vs Backlog by Month",
                "chart_type": "dual_line",
                "sql": "SELECT Month, RevenueUSD, BacklogUSD FROM t",
                "label_column": "Month",
                "value_column": "RevenueUSD",
            }
        ],
    )

    assert len(widgets) == 1
    widget = widgets[0]
    assert widget["status"] == "valid"
    assert widget["chart"]["type"] == "combo"
    assert widget["chart"]["subtype"] == "bar_line"
    # The field the review UI actually reads must match the rendered chart,
    # not the LLM's original "dual_line" guess.
    assert widget["chartType"] == "bar_line"


async def test_widget_without_rows_keeps_the_raw_chart_type_hint():
    async def empty_runner(sql: str) -> dict:
        return {"columns": [], "rows": []}

    widgets = await _render_preview_widgets(
        empty_runner,
        [
            {
                "title": "No data",
                "chart_type": "dual_line",
                "sql": "SELECT 1 FROM t",
                "label_column": "Month",
                "value_column": "RevenueUSD",
            }
        ],
    )

    assert widgets[0]["status"] == "preview_only"
    assert widgets[0]["chartType"] == "dual_line"
