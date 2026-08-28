from __future__ import annotations

from typing import Any

from app.services.visualization_engine import (
    ChartType,
    derive_shape,
    rank_visualizations,
    select_visualization,
)
from app.services.visualization_engine import (
    _Shape as Shape,
)

from .formatting import _fmt_num
from .query_helpers import _TWO_VALUE_TYPES, _dimension_columns, _pick_columns, _pick_second_value, _to_float


def _two_value_chart(
    chart_type: str,
    title: str,
    columns: list[str],
    rows: list[dict[str, Any]],
    label_hint: str,
    value_hint: str,
    value_hint_2: str,
) -> dict[str, Any] | None:
    """Build a two-metric chart (dual_line / scatter / bubble).

    Returns ``None`` when a second numeric column can't be resolved, so the
    caller can fall back to a single-value chart instead of dropping the card.
    """
    if chart_type in ("scatter", "bubble"):
        # Scatter uses two numeric measures as X and Y; a label dimension is only
        # used for point names and must not consume one of the measures.
        value_col = value_hint if value_hint and value_hint in columns else _pick_columns(columns, rows, "", "")[1]
        if not value_col:
            return None
        value2_col = _pick_second_value(columns, rows, (value_col,), value_hint_2)
        if not value2_col:
            return None
        shape = derive_shape(columns, rows)
        label_col = next(
            (c.name for c in shape.columns if c.name not in (value_col, value2_col) and c.kind in ("categorical", "text")),
            None,
        )
    else:
        label_col, value_col = _pick_columns(columns, rows, label_hint, value_hint)
        if not value_col:
            return None
        value2_col = _pick_second_value(
            columns, rows, (value_col, label_col), value_hint_2
        )
        if not value2_col:
            return None
    series: list[dict[str, Any]] = []
    for r in rows[-24:]:
        v = _to_float(r.get(value_col))
        v2 = _to_float(r.get(value2_col))
        if v is None or v2 is None:
            continue
        series.append(
            {
                "label": str(r.get(label_col)) if label_col else "",
                "value": round(v, 2),
                "value2": round(v2, 2),
            }
        )
    if not series:
        return None
    series_labels = {"value": value_col, "value2": value2_col}
    if chart_type == "dual_line":
        # Two metrics over a shared (time) axis -> combo (bar + overlay line).
        return {
            "type": "combo",
            "subtype": "bar_line",
            "title": title,
            "data": {"series": series},
            "roles": {"x": label_col or "label", "y": value_col, "y2": value2_col},
            "seriesLabels": series_labels,
        }
    # scatter / bubble -> two variables as x/y (bubble degrades to scatter when
    # no third size metric is available).
    return {
        "type": "scatter",
        "subtype": "bubble" if chart_type == "bubble" else "",
        "title": title,
        "data": {"series": series},
        "roles": {"x": value_col, "y": value2_col},
        "seriesLabels": series_labels,
    }


def _build_chart(
    chart_type: str,
    title: str,
    result: dict[str, Any],
    label_hint: str,
    value_hint: str,
    value_hint_2: str = "",
) -> dict[str, Any] | None:
    """Pick the best visual for a real query result (shape-aware, never faked).

    The planner's ``chart_type`` is treated as a hint chosen from the dashboard
    chart catalog; the actual result shape validates/overrides it so insights
    aren't all rendered as bars:
      - single row / few headline numbers -> KPI tiles
      - ordered time-period labels         -> line (trend)
      - parts-of-a-whole categories        -> donut/pie (mix)
      - everything else with categories    -> the planner's pick, else bar
    ``chart_type == "none"`` (or no usable numeric data) -> text-only card.
    """
    columns = result.get("columns", [])
    rows = result.get("rows", [])
    if not rows or not columns:
        return None

    # Planner explicitly wants a narrative (text + highlights) card.
    if chart_type in ("none", "text", "callout"):
        return None

    # Single-row result with one or more numeric columns -> KPI tiles. This also
    # covers a single headline number, which reads better as a tile than a bar.
    # Exclude the grouped dimension/period column (e.g. a "Period" year) so it is
    # never shown as a headline number — a bare year like 2026 would otherwise
    # format as a meaningless "2.0K" tile.
    if len(rows) == 1:
        row = rows[0]
        skip = _dimension_columns(columns, label_hint)
        kpis = [
            {"value": _fmt_num(v), "label": col}
            for col in columns
            if col not in skip and (v := _to_float(row.get(col))) is not None
        ]
        if kpis:
            return {"type": "kpi_grid", "title": title, "data": {"kpis": kpis[:6]}}
        return None

    # Two-metric charts (dual_line / scatter / bubble) need a second numeric
    # column; build that shape when one is available, else fall through to the
    # single-value handling below so the card still renders.
    #
    # The planner's chart_type is only a hint, and it can be wrong: the LLM
    # may call a two-measure time series "line" instead of "dual_line". When
    # the hint isn't already a two-value family, ask the same confidence-
    # ranked engine _grounded_chart_selection (ai_proxy_dashboard_designer.py)
    # already consults unconditionally at apply time whether the executed
    # shape is actually a combo -- without this, a widget mislabeled "line"
    # rendered as a single measure here (dropping the second one entirely)
    # while apply-time grounding correctly built a combo from the same data,
    # so the preview and the created dashboard disagreed on the same widget.
    effective_type = chart_type
    if chart_type not in _TWO_VALUE_TYPES:
        engine_decision = select_visualization(columns, rows, intent_hint=chart_type)
        if engine_decision.chart_type == ChartType.COMBO:
            effective_type = "dual_line"
    if effective_type in _TWO_VALUE_TYPES:
        two = _two_value_chart(
            effective_type, title, columns, rows, label_hint, value_hint, value_hint_2
        )
        if two is not None:
            return two

    label_col, value_col = _pick_columns(columns, rows, label_hint, value_hint)
    if not label_col or not value_col:
        return None
    series: list[dict[str, Any]] = []
    for r in rows[-24:]:
        v = _to_float(r.get(value_col))
        if v is None:
            continue
        series.append({"label": str(r.get(label_col)), "value": round(v, 2)})
    if not series:
        return None

    # ``kpi_grid`` is a shape-specific tile layout, not a chart family — keep it.
    if chart_type == "kpi_grid":
        kpis = [
            {"value": _fmt_num(s["value"]), "label": s["label"]} for s in series[:6]
        ]
        return {"type": "kpi_grid", "title": title, "data": {"kpis": kpis}}

    # Delegate the single-metric chart-type decision to the one Universal
    # Visualization Engine, passing the planner's pick as a hint so Home cards,
    # ask-and-run, and dashboards all resolve the same chart for the same shape.
    # The series (already shaped from the executed result) is preserved as-is.
    decision = select_visualization(
        [label_col, value_col],
        [{label_col: s["label"], value_col: s["value"]} for s in series],
        intent_hint=chart_type,
    )
    return {
        "type": decision.chart_type.value,
        "subtype": decision.chart_style,
        "title": title,
        "data": {"series": series},
        "seriesLabels": {"value": value_col},
        "roles": {"x": label_col or "label", "y": value_col},
    }


def _nice_name(col: str) -> str:
    """Human-friendly column name for insight titles."""
    return str(col).replace("_", " ").strip().title()


def _shape_scatter_label_col(shape: Shape, used: set[str]) -> str | None:
    """Pick a categorical/text label for scatter points, avoiding period axes."""
    return next(
        (
            c.name
            for c in shape.columns
            if c.name not in used and c.kind in ("categorical", "text")
        ),
        None,
    )


def _build_multi_chart(
    chart_type: str,
    title: str,
    rows: list[dict[str, Any]],
    columns: list[str],
    roles: dict[str, str],
) -> dict[str, Any]:
    """Build a chart payload using generic data rows + field roles.

    The frontend ``InsightChartView`` maps ``roles`` to ``WidgetConfig`` columns
    and renders the rows through the same ``WidgetRenderer`` used by dashboards.
    All shape-compatible chart families are ranked so the chart-suggestion modal
    can offer every viable alternative, not just the template's first choice.
    """
    ranked = rank_visualizations(columns, rows, limit=50)

    # Promote the template's intended family to the top so the preselected card
    # matches the shape that produced it, but still expose every eligible family.
    candidates = [c.to_dict() for c in ranked]
    template_index = next(
        (
            i
            for i, c in enumerate(candidates)
            if c.get("decision", {}).get("chartType") == chart_type
        ),
        None,
    )
    if template_index is not None and template_index > 0:
        intended = candidates.pop(template_index)
        candidates.insert(0, intended)
    elif not candidates:
        # Fallback: at least one candidate for the intended family.
        x_field = roles.get("x")
        y_field = roles.get("value") or roles.get("y")
        y2_field = roles.get("y2") or roles.get("group")
        candidates = [
            {
                "decision": {
                    "chartType": chart_type,
                    "chartStyle": "",
                    "xField": x_field,
                    "yField": y_field,
                    "valueFormat": "number",
                    "reason": f"Shape template generated a {chart_type} chart from the source table.",
                    "y2Field": y2_field,
                },
                "score": 1.0,
                "supported": True,
                "unsupportedReason": "",
            }
        ]

    decision = candidates[0]["decision"]

    return {
        "type": chart_type,
        "subtype": "",
        "title": title,
        "data": {"rows": rows, "columns": columns},
        "roles": roles,
        "visualizationDecision": decision,
        "chartCandidates": candidates,
    }
