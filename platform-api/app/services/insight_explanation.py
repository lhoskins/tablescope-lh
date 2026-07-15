"""Structured, factual explainability metadata for generated insight cards.

Explanations are derived from the actual analysis inputs and results that
produced a card, not invented after the fact. They are persisted on the card
so frozen snapshots and Home pins remain explainable after the live feed is
refreshed.
"""

from __future__ import annotations

import math
from typing import Any

_METHOD_TAXONOMY = {
    "aggregation": "Aggregation",
    "trend_analysis": "Trend analysis",
    "period_over_period_comparison": "Period-over-period comparison",
    "variance_analysis": "Variance analysis",
    "ranking": "Ranking",
    "segmentation": "Segmentation",
    "anomaly_detection": "Anomaly detection",
    "distribution_analysis": "Distribution analysis",
    "correlation_analysis": "Correlation analysis",
    "forecast": "Forecast",
    "document_synthesis": "Document synthesis",
    "rule_based_detection": "Rule-based detection",
    "other": "Other",
}

# Backward-compatible labels for the built-in diagnostic prompt types.
_INSIGHT_TYPE_METHOD: dict[str, str] = {
    "risk_sla": "rule_based_detection",
    "risk_threshold": "rule_based_detection",
    "risk_expiry": "document_synthesis",
    "risk_upcoming": "trend_analysis",
    "trend_spend": "period_over_period_comparison",
    "trend_metric": "trend_analysis",
    "opportunity_supplier": "ranking",
    "opportunity_performance": "ranking",
}


def _method_label(method: str | None) -> str:
    key = method or "other"
    return _METHOD_TAXONOMY.get(key, key.replace("_", " ").title())


def infer_method(
    insight_type: str,
    chart_type: str | None = None,
    sql: str | None = None,
    documents: list[str] | None = None,
    category: str | None = None,
) -> str:
    """Select a controlled analytical-method taxonomy key for an insight."""
    base = insight_type.split("_", 1)[0] if insight_type else ""
    exact = _INSIGHT_TYPE_METHOD.get(insight_type)
    if exact:
        return exact
    if category == "relationship" or "relationship" in insight_type:
        return "correlation_analysis"
    if documents and not sql:
        return "document_synthesis"
    if chart_type in ("line", "area"):
        return "trend_analysis"
    if chart_type in ("bar", "radial_bar") and base == "opportunity":
        return "ranking"
    if chart_type == "bar" and (base == "risk" or "status" in insight_type):
        return "distribution_analysis"
    if chart_type == "kpi_grid" and base in ("trend", "spend"):
        return "period_over_period_comparison"
    if base == "risk":
        return "rule_based_detection"
    if base == "opportunity":
        return "ranking"
    if base == "trend":
        return "trend_analysis"
    return "other"


def _pluck_series(chart: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not chart:
        return []
    data = chart.get("data") or {}
    return data.get("series") or data.get("kpis") or []


def _to_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        # Strip common formatting characters (currency, units, commas, percent).
        cleaned = (
            value.replace(",", "")
            .replace("$", "")
            .replace("%", "")
            .replace("K", "")
            .replace("M", "")
            .strip()
        )
        try:
            n = float(cleaned)
            return n if math.isfinite(n) else None
        except ValueError:
            return None
    return None


def _top_finding(
    chart: dict[str, Any] | None,
    method: str,
    metric: str | None,
    label_column: str | None,
) -> str | None:
    series = _pluck_series(chart)
    if not series:
        return None
    numeric = [
        (s, v)
        for s in series
        if (v := _to_number(s.get("value"))) is not None
    ]
    if not numeric:
        return None
    if method in ("trend_analysis", "period_over_period_comparison", "variance_analysis"):
        first, first_val = numeric[0]
        last, last_val = numeric[-1]
        if first_val != 0:
            pct = (last_val - first_val) / first_val * 100
            direction = "increased" if pct > 0 else "decreased"
            return (
                f"{metric or 'The metric'} {direction} "
                f"{abs(pct):.1f}% from {first.get('label')} to {last.get('label')}."
            )
    try:
        top = max(numeric, key=lambda s_v: s_v[1])[0]
    except (TypeError, ValueError):
        return None
    return (
        f"{top.get('label')} leads at {top.get('value')} "
        f"{metric or ''} across the {len(series)} values shown."
    )


def _default_steps(
    method: str,
    *,
    aggregation: str | None,
    metric: str | None,
    label_column: str | None,
    period_column: str | None,
    filters: list[dict] | None,
    documents: list[str] | None,
    sql: str | None,
) -> list[str]:
    steps: list[str] = []
    if method == "document_synthesis":
        steps.append("Reviewed the supplied documents and extracted relevant metadata.")
        if documents:
            steps.append(f"Sources: {', '.join(documents[:4])}.")
        steps.append("Synthesized the finding from document content; no executable SQL was used.")
        return steps

    if sql:
        if label_column and metric:
            steps.append(f"Grouped data by {label_column}.")
            steps.append(f"Computed {aggregation or 'the value'} of {metric} for each group.")
        elif period_column and metric:
            steps.append(f"Grouped records by {period_column}.")
            steps.append(f"Computed {aggregation or 'the value'} of {metric} for each period.")
        elif metric:
            steps.append(f"Computed {aggregation or 'the value'} for {metric}.")
        else:
            steps.append("Executed the analysis query against the project's authorized data.")
    else:
        steps.append("Analyzed the available project data and metadata.")

    if method in ("ranking", "correlation_analysis"):
        steps.append("Ranked results and highlighted the top-performing values.")
    elif method in ("trend_analysis", "period_over_period_comparison", "variance_analysis"):
        steps.append("Compared the most recent period to the prior period to identify direction and magnitude.")
    elif method == "rule_based_detection":
        steps.append("Evaluated records against the defined threshold or status rule.")
    elif method == "distribution_analysis":
        steps.append("Sorted groups by frequency or magnitude to identify the dominant categories.")

    if filters:
        for f in filters[:2]:
            steps.append(f"Filtered on {f.get('field')} {f.get('operator')} {f.get('value')}.")

    return steps


def _confidence(
    row_count: int | None,
    method: str,
    sql: str | None,
) -> dict[str, Any]:
    if method == "document_synthesis":
        level = "low" if row_count is None or row_count < 3 else "medium"
        basis = "Finding is derived from document metadata and summaries without query execution."
    elif sql:
        if row_count and row_count >= 5:
            level = "medium"
            basis = "Result was supported by a successfully executed query with multiple rows."
        elif row_count and row_count > 0:
            level = "medium"
            basis = "Result was supported by a successfully executed query with a small number of rows."
        else:
            level = "low"
            basis = "SQL was generated but returned no rows or could not be evaluated."
    else:
        level = "low"
        basis = "No executable SQL was used; confidence is based on available metadata only."
    return {"level": level, "score": None, "basis": basis}


def build_explanation(
    *,
    project_id: int | str,
    project_name: str,
    insight_type: str,
    summary: str,
    method: str | None = None,
    chart: dict[str, Any] | None = None,
    chart_type: str | None = None,
    label_column: str | None = None,
    value_column: str | None = None,
    value_column_2: str | None = None,
    tables: list[str] | None = None,
    fields: list[str] | None = None,
    metric: str | None = None,
    aggregation: str | None = None,
    period_column: str | None = None,
    filters: list[dict] | None = None,
    comparison: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    sql: str | None = None,
    assumptions: list[str] | None = None,
    limitations: list[str] | None = None,
    documents: list[str] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any] | None:
    """Build a structured explanation from the actual analysis that produced a card.

    Returns ``None`` when there is not enough metadata to build a useful
    explanation (legacy cards without any of these fields remain renderable).
    """
    if not method:
        method = infer_method(
            insight_type,
            chart_type=chart_type,
            sql=sql,
            documents=documents,
        )

    if method == "document_synthesis" and not documents:
        # Insufficient metadata for a document-only explanation.
        return None

    rows = result.get("rows") if result else None
    row_count = len(rows) if isinstance(rows, list) else None
    result_columns: list[str] | None = None
    if result and isinstance(result.get("columns"), list):
        result_columns = [str(c) for c in result["columns"]]

    # Fallback evidence from the chart series when a raw result is unavailable.
    series = _pluck_series(chart)
    if row_count is None and series:
        row_count = len(series)
    if result_columns is None and series:
        result_columns = ["label", "value"]
        if any("value2" in s for s in series):
            result_columns.append("value2")

    default_assumptions = [
        "Columns referenced in the SQL exist and are accessible to the project.",
        "Numeric values are cast to double for aggregation where needed.",
        "The analysis reflects the project's currently authorized data source snapshot.",
    ]
    default_limitations = [
        "Analysis is limited to the tables and columns the project has exposed.",
        "No causal inference is performed; correlations are not causes.",
        "Aggregations assume consistent data types and no hidden nulls.",
        "Results reflect data available at the time the insight was generated.",
    ]

    if method == "document_synthesis":
        default_assumptions = [
            "Document metadata and AI summaries are treated as source content.",
        ]
        default_limitations = [
            "No executable SQL was used for this finding.",
            "The synthesis depends on the quality and completeness of the document summaries.",
        ]

    evidence: dict[str, Any] = {"rowCount": row_count, "resultColumns": result_columns}
    top = _top_finding(chart, method, metric, label_column)
    if top:
        evidence["topFinding"] = top

    explanation: dict[str, Any] = {
        "summary": summary,
        "method": method,
        "methodLabel": _method_label(method),
        "steps": _default_steps(
            method,
            aggregation=aggregation,
            metric=metric,
            label_column=label_column,
            period_column=period_column,
            filters=filters,
            documents=documents,
            sql=sql,
        ),
        "source": {
            "projectId": project_id,
            "projectName": project_name,
            "dataSourceId": None,
            "dataSourceName": None,
            "tables": tables or [],
            "fields": fields or [],
        },
        "filters": filters or [],
        "metrics": [],
        "evidence": evidence,
        "sql": sql,
        "chart": None,
        "assumptions": assumptions or default_assumptions,
        "limitations": limitations or default_limitations,
        "confidence": _confidence(row_count, method, sql),
        "generatedAt": generated_at,
    }

    if metric:
        explanation["metrics"].append(
            {"name": metric, "aggregation": aggregation or "value", "field": metric}
        )

    if comparison:
        explanation["comparison"] = comparison

    if chart_type:
        explanation["chart"] = {
            "chartType": chart_type,
            "labelColumn": label_column,
            "valueColumn": value_column,
            "valueColumn2": value_column_2,
        }

    # Remove empty optional blocks instead of returning nulls.
    if not explanation["filters"]:
        del explanation["filters"]
    if not explanation["metrics"]:
        del explanation["metrics"]
    if not explanation["evidence"]["rowCount"] and not explanation["evidence"]["resultColumns"] and not explanation["evidence"].get("topFinding"):
        explanation["evidence"] = {"rowCount": None, "resultColumns": None}

    return explanation
