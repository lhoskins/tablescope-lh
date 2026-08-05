from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.services.visualization_engine import (
    _Shape as Shape,
)

from .chart_builder import _build_chart, _build_multi_chart, _nice_name, _shape_scatter_label_col
from .query_helpers import _agg_for_measure, _quote, _safe_query, _to_float

if TYPE_CHECKING:
    from .query_helpers import QueryRunner



def _build_radar_rows(rows: list[dict[str, Any]], subject_col: str, measure_cols: list[str]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Melt a wide scorecard (subject + measures) into long radar rows."""
    long_rows: list[dict[str, Any]] = []
    for r in rows:
        subject = r.get(subject_col)
        if subject is None:
            continue
        for m in measure_cols:
            v = _to_float(r.get(m))
            if v is None:
                continue
            long_rows.append({"subject": str(subject), "metric": m, "value": round(v, 2)})
    return long_rows, {"x": "subject", "y": "value", "group": "metric"}


async def _build_radar_template(
    table: Any,
    shape: Shape,
    dims: list[str],
    measures: list[str],
    roles: dict[str, Any],
    runner: QueryRunner,
    max_rows: int,
) -> dict[str, Any] | None:
    if len(dims) < 1 or len(measures) < 3:
        return None
    subject_col = dims[0]
    measure_cols = measures[:6]
    agg = ", ".join(f'{_agg_for_measure(m)}({_quote(m)}) AS {_quote(m)}' for m in measure_cols)
    sql = f'SELECT {_quote(subject_col)}, {agg} FROM {_quote(table.view_name)} GROUP BY {_quote(subject_col)} LIMIT {max_rows}'
    result = await _safe_query(runner, sql)
    if not result or not result.get("rows"):
        return None
    long_rows, radar_roles = _build_radar_rows(result["rows"], subject_col, measure_cols)
    if not long_rows:
        return None
    title = f"{_nice_name(subject_col)} Scorecard"
    chart = _build_multi_chart("radar", title, long_rows, ["subject", "metric", "value"], radar_roles)
    return {
        "insight_type": "shape_radar",
        "group": "analysis",
        "title": title,
        "summary": f"Compare {len(measure_cols)} metrics across {len(result['rows'])} {_nice_name(subject_col)} values.",
        "chart": chart,
        "result": result,
        "sql": sql,
    }


async def _build_heatmap_template(
    table: Any,
    shape: Shape,
    dims: list[str],
    measures: list[str],
    roles: dict[str, Any],
    runner: QueryRunner,
    max_rows: int,
) -> dict[str, Any] | None:
    if len(dims) < 2 or len(measures) < 1:
        return None
    x_col, y_col = dims[0], dims[1]
    value_col = measures[0]
    agg = _agg_for_measure(value_col)
    sql = (
        f'SELECT {_quote(x_col)}, {_quote(y_col)}, {agg}({_quote(value_col)}) AS {_quote("value")} '
        f'FROM {_quote(table.view_name)} GROUP BY {_quote(x_col)}, {_quote(y_col)} LIMIT {max_rows}'
    )
    result = await _safe_query(runner, sql)
    if not result or not result.get("rows"):
        return None
    title = f"{_nice_name(value_col)} by {_nice_name(x_col)} and {_nice_name(y_col)}"
    chart = _build_multi_chart(
        "heatmap",
        title,
        result["rows"],
        result.get("columns", [x_col, y_col, "value"]),
        {"x": x_col, "y": y_col, "value": "value"},
    )
    return {
        "insight_type": "shape_heatmap",
        "group": "analysis",
        "title": title,
        "summary": f"Heatmap of {_nice_name(value_col)} across {_nice_name(x_col)} and {_nice_name(y_col)}.",
        "chart": chart,
        "result": result,
        "sql": sql,
    }


async def _build_treemap_template(
    table: Any,
    shape: Shape,
    dims: list[str],
    measures: list[str],
    roles: dict[str, Any],
    runner: QueryRunner,
    max_rows: int,
) -> dict[str, Any] | None:
    if len(dims) < 2 or len(measures) < 1:
        return None
    parent_col, child_col = dims[0], dims[1]
    value_col = measures[0]
    agg = _agg_for_measure(value_col)
    sql = (
        f'SELECT {_quote(parent_col)}, {_quote(child_col)}, {agg}({_quote(value_col)}) AS {_quote("value")} '
        f'FROM {_quote(table.view_name)} GROUP BY {_quote(parent_col)}, {_quote(child_col)} LIMIT {max_rows}'
    )
    result = await _safe_query(runner, sql)
    if not result or not result.get("rows"):
        return None
    title = f"{_nice_name(value_col)} by {_nice_name(parent_col)} / {_nice_name(child_col)}"
    chart = _build_multi_chart(
        "treemap",
        title,
        result["rows"],
        result.get("columns", [parent_col, child_col, "value"]),
        {"x": parent_col, "group": child_col, "value": "value"},
    )
    return {
        "insight_type": "shape_treemap",
        "group": "analysis",
        "title": title,
        "summary": f"Hierarchical breakdown of {_nice_name(value_col)} by {_nice_name(parent_col)} and {_nice_name(child_col)}.",
        "chart": chart,
        "result": result,
        "sql": sql,
    }


async def _build_sankey_template(
    table: Any,
    shape: Shape,
    dims: list[str],
    measures: list[str],
    roles: dict[str, Any],
    runner: QueryRunner,
    max_rows: int,
) -> dict[str, Any] | None:
    if len(measures) < 1:
        return None
    if roles.get("source") and roles.get("target"):
        source_col = roles["source"]
        target_col = roles["target"]
    elif len(dims) >= 2:
        source_col = dims[0]
        target_col = dims[1]
    else:
        return None
    value_col = roles.get("value") or measures[0]
    agg = _agg_for_measure(value_col)
    sql = (
        f'SELECT {_quote(source_col)}, {_quote(target_col)}, {agg}({_quote(value_col)}) AS {_quote("value")} '
        f'FROM {_quote(table.view_name)} GROUP BY {_quote(source_col)}, {_quote(target_col)} LIMIT {max_rows}'
    )
    result = await _safe_query(runner, sql)
    if not result or not result.get("rows"):
        return None
    title = f"Flow from {_nice_name(source_col)} to {_nice_name(target_col)}"
    chart = _build_multi_chart(
        "sankey",
        title,
        result["rows"],
        result.get("columns", [source_col, target_col, "value"]),
        {"x": source_col, "group": target_col, "value": "value"},
    )
    return {
        "insight_type": "shape_sankey",
        "group": "analysis",
        "title": title,
        "summary": f"Source-to-target flow weighted by {_nice_name(value_col)}.",
        "chart": chart,
        "result": result,
        "sql": sql,
    }


async def _build_funnel_template(
    table: Any,
    shape: Shape,
    dims: list[str],
    measures: list[str],
    roles: dict[str, Any],
    runner: QueryRunner,
    max_rows: int,
) -> dict[str, Any] | None:
    if len(dims) < 1 or len(measures) < 1:
        return None
    stage_col = roles.get("stage")
    if not stage_col:
        return None
    value_col = measures[0]
    agg = _agg_for_measure(value_col)
    sql = (
        f'SELECT {_quote(stage_col)}, {agg}({_quote(value_col)}) AS {_quote("value")} '
        f'FROM {_quote(table.view_name)} GROUP BY {_quote(stage_col)} ORDER BY {_quote("value")} DESC LIMIT {max_rows}'
    )
    result = await _safe_query(runner, sql)
    if not result or not result.get("rows"):
        return None
    title = f"{_nice_name(stage_col)} {_nice_name(value_col)} Funnel"
    chart = _build_multi_chart(
        "funnel",
        title,
        result["rows"],
        result.get("columns", [stage_col, "value"]),
        {"x": stage_col, "value": "value"},
    )
    return {
        "insight_type": "shape_funnel",
        "group": "analysis",
        "title": title,
        "summary": f"Stage progression of {_nice_name(value_col)} by {_nice_name(stage_col)}.",
        "chart": chart,
        "result": result,
        "sql": sql,
    }


async def _build_scatter_template(
    table: Any,
    shape: Shape,
    dims: list[str],
    measures: list[str],
    roles: dict[str, Any],
    runner: QueryRunner,
    max_rows: int,
) -> dict[str, Any] | None:
    if len(measures) < 2:
        return None
    x_col, y_col = measures[0], measures[1]
    label_col = _shape_scatter_label_col(shape, {x_col, y_col})
    label_select = f", {_quote(label_col)}" if label_col else ""
    sql = f'SELECT {_quote(x_col)}, {_quote(y_col)}{label_select} FROM {_quote(table.view_name)} LIMIT {max_rows}'
    result = await _safe_query(runner, sql)
    if not result or not result.get("rows"):
        return None
    title = f"{_nice_name(x_col)} vs {_nice_name(y_col)}"
    scatter_chart = _build_chart(
        "scatter",
        title,
        result,
        label_hint=label_col or "",
        value_hint=x_col,
        value_hint_2=y_col,
    )
    if not scatter_chart:
        return None
    return {
        "insight_type": "shape_scatter",
        "group": "analysis",
        "title": title,
        "summary": f"Relationship between {_nice_name(x_col)} and {_nice_name(y_col)} across {len(result['rows'])} records.",
        "chart": scatter_chart,
        "result": result,
        "sql": sql,
    }


#: A shape template only runs when the family is a genuinely good fit for the
#: probed table; below this the card would be a technically-eligible but
#: misleading chart (e.g. a heatmap over an id-like dimension).
_SHAPE_TEMPLATE_MIN_FIT = 0.5

_TEMPLATE_BUILDERS: dict[str, Any] = {
    "radar": _build_radar_template,
    "heatmap": _build_heatmap_template,
    "treemap": _build_treemap_template,
    "sankey": _build_sankey_template,
    "funnel": _build_funnel_template,
    "scatter": _build_scatter_template,
}
