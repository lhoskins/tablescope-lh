
from __future__ import annotations

from typing import Any

from .intent_classification import _CHART_SUBTYPES, _CHART_TYPES
from .result_profiling import _column_data_profile


def _pick_chart_fields(
    columns: list[str],
    rows: list[dict[str, Any]],
    chart_type: str,
    subtype: str | None = None,
) -> dict[str, Any]:
    """Choose grounded label/value/metric columns for a chart type."""
    profile = _column_data_profile(columns, rows)
    numeric = profile["numeric"]
    period = profile["period"]
    categorical = profile["categorical"]
    result: dict[str, Any] = {}

    if chart_type == "kpi":
        result["metricField"] = numeric[0] if numeric else (columns[-1] if columns else None)
        return result

    if chart_type in ("line", "area"):
        # Prefer a period axis, then a categorical axis, then the first column.
        label = period[0] if period else (categorical[0] if categorical else columns[0] if columns else None)
        value = numeric[0] if numeric else (columns[-1] if columns else None)
        if label:
            result["labelColumn"] = label
        if value:
            result["valueColumns"] = [value]
        return result

    if chart_type == "scatter":
        if len(numeric) >= 2:
            result["labelColumn"] = numeric[0]
            result["valueColumns"] = numeric[1:]
        elif numeric:
            result["valueColumns"] = [numeric[0]]
        return result

    # bar / pie and all other chart types need a categorical label + numeric value.
    # Prefer categorical labels, then period labels (which work as bar categories),
    # then fall back to the first column.
    label = categorical[0] if categorical else (period[0] if period else (columns[0] if columns else None))
    value = numeric[0] if numeric else (columns[-1] if columns else None)
    if label:
        result["labelColumn"] = label
    if value:
        result["valueColumns"] = [value]
    return result


def _build_chart_config(
    suggested: dict[str, Any] | None,
    columns: list[str],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Normalize the ask-and-run visualization suggestion into a stable chart config."""
    if not suggested:
        suggested = {}
    chart_type = suggested.get("type") or "table"
    config: dict[str, Any] = {
        "type": chart_type,
        "title": suggested.get("title", "Chart"),
    }
    if suggested.get("chartStyle"):
        config["subtype"] = suggested["chartStyle"]
    if suggested.get("topN") is not None:
        config["topN"] = suggested["topN"]

    # Prefer the engine's explicit x/y/metric mapping when it is grounded in the
    # actual result columns.
    x_field = suggested.get("xField")
    y_field = suggested.get("yField")
    metric_field = suggested.get("metricField") or y_field
    if x_field in columns:
        config["labelColumn"] = x_field
    if y_field in columns:
        config["valueColumns"] = [y_field]
    if metric_field in columns and chart_type == "kpi":
        config["metricField"] = metric_field

    # If the suggestion did not include usable fields, derive them from the data.
    if chart_type != "table" and "valueColumns" not in config and "metricField" not in config:
        derived = _pick_chart_fields(columns, rows, chart_type, config.get("subtype"))
        config.update(derived)

    return config


_SUBTYPE_LABELS = {
    "horizontal_bar": "horizontal bar",
    "stacked_bar": "stacked bar",
    "grouped_bar": "grouped bar",
    "stacked_horizontal": "stacked horizontal bar",
    "positive_negative": "diverging bar",
    "waterfall": "waterfall",
    "column": "column",
    "smooth_line": "smooth line",
    "step_line": "step line",
    "dashed_line": "dashed line",
    "stacked_area": "stacked area",
    "donut": "donut",
    "two_level": "two-level pie",
    "gauge": "gauge",
    "bubble": "bubble",
    "best_fit": "trend-line scatter",
}


def apply_chart_patch(
    chart_config: dict[str, Any],
    result: dict[str, Any],
    patch: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Apply a structured chart patch to the existing config.

    The patch comes from the LLM classifier (or the degraded fallback); this
    function is the deterministic guardrail: every field is validated against
    the renderer's chart vocabulary and the columns that actually exist in the
    cached result, so the chart is always drawable and always grounded.

    Returns the updated config and a short assistant message.
    """
    if not patch:
        return chart_config, (
            "I couldn't map that to a chart change. Try something like "
            "'show it as a horizontal bar chart' or 'change it to a donut'."
        )

    new_config = dict(chart_config)
    columns = (result.get("columns") or []) if result else []
    changes: list[str] = []

    type_changed = patch.get("type") in _CHART_TYPES
    if type_changed:
        new_config["type"] = patch["type"]
        # A new type resets any previous style unless the patch names one, so
        # "make it a vertical bar" clears horizontal_bar instead of keeping it.
        new_config.pop("subtype", None)
    subtype = patch.get("subtype")
    subtype_changed = bool(
        subtype and subtype in _CHART_SUBTYPES.get(new_config.get("type", ""), set())
    )
    if subtype_changed:
        new_config["subtype"] = subtype
    if type_changed or subtype_changed:
        style = _SUBTYPE_LABELS.get(new_config.get("subtype", ""), "")
        if new_config.get("type") == "table" and not style:
            changes.append("showing the result as a table")
        else:
            name = style or new_config.get("type", "")
            changes.append(f"changed the chart to a {name} chart")

    # Re-derive grounded label/value/metric columns whenever the chart type
    # changed or no drawable fields are present, but never overwrite an explicit
    # label/value choice from the patch.
    if new_config.get("type") not in ("table",) and columns:
        rows_for_fields = (result.get("rows") or []) if result else []
        derived = _pick_chart_fields(
            columns,
            rows_for_fields,
            new_config["type"],
            new_config.get("subtype"),
        )
        if "labelColumn" not in new_config and "metricField" not in new_config:
            new_config.setdefault("labelColumn", derived.get("labelColumn"))
        new_config.setdefault("valueColumns", derived.get("valueColumns"))
        new_config.setdefault("metricField", derived.get("metricField"))

    label = patch.get("labelColumn")
    if label:
        if label not in columns:
            return chart_config, (
                f"Column '{label}' is not in this result. "
                f"Available columns: {', '.join(columns) or 'none'}."
            )
        new_config["labelColumn"] = label
        changes.append(f"using {label} as the label")

    values = patch.get("valueColumns")
    if values:
        missing = [v for v in values if v not in columns]
        if missing:
            return chart_config, (
                f"Column '{missing[0]}' is not in this result. "
                f"Available columns: {', '.join(columns) or 'none'}."
            )
        new_config["valueColumns"] = list(values)
        changes.append(f"plotting {', '.join(values)}")

    if isinstance(patch.get("sort"), dict):
        sort = patch["sort"]
        if sort.get("column") and sort.get("direction") in ("asc", "desc"):
            new_config["sort"] = {"column": sort["column"], "direction": sort["direction"]}
            direction = "descending" if sort["direction"] == "desc" else "ascending"
            changes.append(f"sorted by {sort['column']} {direction}")

    if isinstance(patch.get("dataLabels"), bool):
        new_config["dataLabels"] = patch["dataLabels"]
        changes.append("data labels {}".format("on" if patch["dataLabels"] else "off"))

    if isinstance(patch.get("legendVisible"), bool):
        new_config["legend"] = {"visible": patch["legendVisible"]}
        changes.append("legend {}".format("on" if patch["legendVisible"] else "off"))

    if patch.get("title"):
        new_config["title"] = str(patch["title"])[:120]
        changes.append("renamed the chart")

    # Pie/donut needs one category and one numeric value; adapt rather than fail.
    if new_config.get("type") == "pie":
        if not new_config.get("labelColumn") and columns:
            non_numeric = [c for c in columns if c not in (new_config.get("valueColumns") or [])]
            if non_numeric:
                new_config["labelColumn"] = non_numeric[0]
        current_values = new_config.get("valueColumns") or []
        if len(current_values) > 1:
            new_config["valueColumns"] = current_values[:1]
        if not new_config.get("labelColumn") or not new_config.get("valueColumns"):
            return chart_config, "A pie chart needs one category column and one numeric value."

    if not changes:
        return chart_config, (
            "I couldn't map that to a chart change. Try something like "
            "'show it as a horizontal bar chart' or 'change it to a donut'."
        )
    message = "; ".join(changes)
    return new_config, message[0].upper() + message[1:] + "."
