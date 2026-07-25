"""Tests for the markdown-driven planner chart vocabulary."""

from __future__ import annotations

from app.services import chart_catalog


def test_allowed_types_come_from_markdown():
    allowed = chart_catalog.allowed_plan_chart_types()
    # Rich families unlocked by the catalog (previously snapped to "bar").
    for t in ("boxplot", "sankey", "candlestick", "sunburst", "heatmap", "theme_river"):
        assert t in allowed, t
    # Subtypes count as valid plan types.
    for t in ("stacked_bar", "donut", "smooth_line"):
        assert t in allowed, t
    # Legacy aliases stay accepted.
    for t in ("kpi_grid", "dual_line", "bullet", "sparkline_table", "none"):
        assert t in allowed, t
    assert "not_a_chart" not in allowed


def test_enum_string_is_pipe_joined_and_sorted():
    enum = chart_catalog.plan_chart_type_enum()
    parts = enum.split("|")
    assert parts == sorted(parts)
    assert "boxplot" in parts


def test_digest_is_compact_one_line_per_family():
    digest = chart_catalog.planner_chart_digest()
    lines = digest.splitlines()
    # Header + 31 families; each family line is a single sentence fragment.
    assert len(lines) == 32
    assert all(len(line) < 200 for line in lines)


def test_missing_markdown_fails_open(monkeypatch):
    monkeypatch.setattr(chart_catalog, "load_prompt_reference", lambda name: "")
    chart_catalog._parse.cache_clear()
    try:
        allowed = chart_catalog.allowed_plan_chart_types()
        # Historical core set still allowed so planning never breaks.
        assert "line" in allowed and "bar" in allowed and "heatmap" in allowed
    finally:
        chart_catalog._parse.cache_clear()
