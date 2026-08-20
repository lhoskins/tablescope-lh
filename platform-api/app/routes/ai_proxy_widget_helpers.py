"""Widget helpers shared by the dashboard generation/suggestion routers.

Chart-type mapping, the widget judge, chart correction, grid packing and
join-quality metadata."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.services.visualization_engine import ChartType, select_visualization

logger = logging.getLogger(__name__)

def _derive_dashboard_title(
    project_name: str, widgets: list[dict[str, Any]]
) -> str:
    """Build a descriptive, non-generic dashboard title from the widget content."""
    titles = [
        str(w.get("title") or "").strip()
        for w in widgets
        if w.get("title") and str(w.get("title")).strip() not in ("", "Widget")
    ]
    seen: list[str] = []
    for t in titles:
        if t not in seen:
            seen.append(t)
        if len(seen) == 2:
            break
    if seen:
        base = " & ".join(seen)
        if "dashboard" not in base.lower():
            base = f"{base} Dashboard"
        return base
    return f"{project_name} — AI Dashboard"


def _suggestion_save_prompt(
    title: str,
    business_purpose: str,
    description: str,
    widgets: list[dict[str, Any]],
    kpis: list[str],
) -> str:
    """Build a focused prompt that pins the strict save stage to a chosen plan."""
    parts: list[str] = [p for p in (title, business_purpose, description) if p]
    for w in widgets:
        label = str(w.get("title") or "")
        question = str(w.get("businessQuestion") or "")
        if label or question:
            parts.append(": ".join(p for p in (label, question) if p))
    if kpis:
        parts.append("KPIs to cover: " + ", ".join(kpis))
    return ". ".join(parts)


# Insight-first chart catalog → (dashboard WidgetType, ChartSubtype).
# The planner may request a rich type (horizontal_bar, dual_line, waterfall,
# bubble, …); the dashboard renderer expresses these as a base type plus a
# subtype, so map every planner type down to a supported pair.
_CHART_TYPE_MAP: dict[str, tuple[str, str]] = {
    "kpi": ("kpi", "kpi"),
    "kpi_grid": ("kpi", "kpi"),
    "bar": ("bar", "column"),
    "vertical_bar": ("bar", "column"),
    "horizontal_bar": ("bar", "horizontal_bar"),
    "stacked_bar": ("bar", "stacked_bar"),
    "grouped_bar": ("bar", "grouped_bar"),
    "waterfall": ("bar", "waterfall"),
    "bullet": ("bar", "horizontal_bar"),
    "line": ("line", ""),
    "dual_line": ("line", "biaxial_line"),
    "combo": ("combo", "bar_line"),
    "area": ("area", ""),
    "pie": ("pie", ""),
    "donut": ("pie", "donut"),
    "gauge": ("pie", "gauge"),
    "table": ("table", ""),
    "pivot_table": ("table", ""),
    "sparkline_table": ("table", ""),
    "heatmap": ("table", ""),
    "scatter": ("scatter", ""),
    "bubble": ("scatter", "bubble"),
    "treemap": ("treemap", ""),
    "funnel": ("funnel", ""),
    "radar": ("radar", ""),
}


def _map_widget_visual(ai_type: str) -> tuple[str, str]:
    """Map a planner chart type to a (WidgetType, ChartSubtype) pair."""
    return _CHART_TYPE_MAP.get((ai_type or "").lower(), ("bar", "column"))


def _map_chart_type(ai_type: str) -> str:
    """Map an AI-suggested chart type to the dashboard widget chart type."""
    return _map_widget_visual(ai_type)[0]


def _map_chart_subtype(ai_type: str) -> str:
    """Map an AI-suggested type to a chart subtype."""
    return _map_widget_visual(ai_type)[1]


def _build_join_metadata(widget: dict[str, Any]) -> dict[str, Any] | None:
    """Build join-quality metadata for a widget when it uses a join.

    Prefers the planner's ``relationship_plan``. If that is absent but the SQL
    contains a JOIN, emit best-effort metadata and flag it so the gap is
    visible. Returns None when the widget is single-table.
    """
    plan = widget.get("relationship_plan")
    sql = (widget.get("sql", "") or "")
    has_join = re.search(r"\bjoin\b", sql, re.IGNORECASE) is not None

    if isinstance(plan, dict) and (plan.get("requires_join") or has_join):
        return {
            "requiresJoin": bool(plan.get("requires_join") or has_join),
            "leftTable": str(plan.get("left_table") or ""),
            "rightTable": str(plan.get("right_table") or ""),
            "leftJoinKey": str(plan.get("left_join_key") or ""),
            "rightJoinKey": str(plan.get("right_join_key") or ""),
            "relationshipType": str(plan.get("relationship_type") or "unknown"),
            "joinConfidence": plan.get("join_confidence"),
            "confidenceReason": str(plan.get("confidence_reason") or ""),
            "rowMultiplicationRisk": str(plan.get("row_multiplication_risk") or ""),
            "validated": False,
            "matchRate": None,
            "rowMultiplicationRatio": None,
        }

    if has_join:
        logger.warning(
            "AI dashboard widget %r uses a JOIN with no relationship_plan; "
            "emitting best-effort join metadata",
            widget.get("title", "untitled"),
        )
        return {
            "requiresJoin": True,
            "leftTable": "",
            "rightTable": "",
            "leftJoinKey": "",
            "rightJoinKey": "",
            "relationshipType": "unknown",
            "joinConfidence": None,
            "confidenceReason": "inferred from SQL JOIN (no planner metadata)",
            "rowMultiplicationRisk": "unknown",
            "validated": False,
            "matchRate": None,
            "rowMultiplicationRatio": None,
        }

    return None


_TIME_SERIES_TYPES = frozenset({"line", "area", "dual_line"})


_NARRATIVE_TYPES = frozenset({"narrative_insight", "none", "narrative"})


def _norm_col(name: str) -> str:
    return (name or "").strip().strip('"').lower()


def _judge_widget(
    widget: dict[str, Any], columns: list[str], rows: list[dict[str, Any]]
) -> tuple[bool, str]:
    """Decide whether an executed widget should be kept.

    Returns ``(keep, reason)``; ``reason`` explains the drop when ``keep`` is
    False. Mirrors the doc's judge rules: drop empty results, drop when the
    configured value column is missing/all-null, and drop time-series widgets
    with fewer than 3 periods.
    """
    wtype = str(widget.get("type", "bar")).lower()

    if not rows:
        return False, "returned no rows"

    vcol = widget.get("value_column") or widget.get("y_column") or ""
    if vcol:
        col_map = {_norm_col(c): c for c in columns}
        actual = col_map.get(_norm_col(vcol))
        if actual is None:
            return False, f"value column '{vcol}' missing from result"
        if all(r.get(actual) is None for r in rows):
            return False, f"value column '{vcol}' is entirely null"

    if wtype in _TIME_SERIES_TYPES and len(rows) < 3:
        return False, f"time-series needs >= 3 periods (got {len(rows)})"

    return True, ""


# Engine chart family -> planner-vocabulary type understood by _CHART_TYPE_MAP.
_ENGINE_TO_PLANNER: dict[ChartType, str] = {
    ChartType.KPI: "kpi",
    ChartType.TABLE: "table",
    ChartType.LINE: "line",
    ChartType.AREA: "area",
    ChartType.COMBO: "dual_line",
    ChartType.PIE: "pie",
    ChartType.SCATTER: "scatter",
    ChartType.RADAR: "radar",
    ChartType.RADIAL_BAR: "gauge",
    ChartType.TREEMAP: "treemap",
    ChartType.FUNNEL: "funnel",
    ChartType.SANKEY: "table",
    ChartType.BAR: "bar",
}


# Visually interchangeable families: when the engine's decision lands in the same
# group as the planner's family, the planner's (richer) type/subtype is left
# untouched — so valid variants (waterfall, stacked_bar, biaxial_line, gauge, …)
# survive. Only a shape-mismatched choice is rewritten. Keys are dashboard
# WidgetTypes; values are engine ChartType values considered compatible.
_FAMILY_GROUPS: dict[str, frozenset[str]] = {
    "bar": frozenset({"bar"}),
    "line": frozenset({"line", "area", "combo"}),
    "area": frozenset({"line", "area", "combo"}),
    "combo": frozenset({"line", "area", "combo"}),
    "pie": frozenset({"pie"}),
    "scatter": frozenset({"scatter"}),
    "radar": frozenset({"radar"}),
    "radial_bar": frozenset({"radial_bar"}),
    "treemap": frozenset({"treemap"}),
    "funnel": frozenset({"funnel"}),
    "sankey": frozenset({"sankey"}),
}


def _correct_widget_chart(
    widget: dict[str, Any], columns: list[str], rows: list[dict[str, Any]]
) -> None:
    """Validate the LLM's chart choice against the executed data shape.

    Delegates the shape decision to the one Universal Visualization Engine
    (the same authority Home cards and ask-and-run use). When the engine's
    family agrees with the planner's family, the planner's (richer) type +
    subtype is preserved; only a shape-mismatched choice — e.g. a pie with
    many slices, or a line over non-time categories — is rewritten in place to
    the engine's renderable family. KPI / table / narrative widgets are
    container choices, not chart-shape ones, and are left as the planner set
    them.
    """
    wtype = str(widget.get("type", "bar")).lower()
    if wtype in _NARRATIVE_TYPES or not rows or not columns:
        return

    widget_family = _map_widget_visual(wtype)[0]
    if widget_family in ("kpi", "table"):
        return

    decision = select_visualization(columns, rows, intent_hint=wtype)
    compatible = decision.chart_type.value in _FAMILY_GROUPS.get(
        widget_family, frozenset({widget_family})
    )
    if compatible:
        return

    corrected = _ENGINE_TO_PLANNER.get(decision.chart_type, "bar")
    if decision.chart_type is ChartType.BAR and decision.chart_style == "horizontal_bar":
        corrected = "horizontal_bar"
    widget["type"] = corrected


def _pack_grid(widgets_config: list[dict[str, Any]]) -> None:
    """Lay widgets out left-to-right on a 12-column grid in priority order.

    KPI tiles are placed first across the top row; remaining widgets flow in a
    simple row-packing reading path. Mutates each widget's gridX/gridY/colSpan.
    """
    cursor_x = 0
    cursor_y = 0
    row_h = 0
    for w in widgets_config:
        gw = max(2, min(12, int(w.get("gridW") or 6)))
        gh = max(1, min(8, int(w.get("gridH") or 4)))
        if cursor_x + gw > 12:
            cursor_x = 0
            cursor_y += row_h
            row_h = 0
        w["gridX"] = cursor_x
        w["gridY"] = cursor_y
        w["gridW"] = gw
        w["gridH"] = gh
        w["colSpan"] = gw
        cursor_x += gw
        row_h = max(row_h, gh)
