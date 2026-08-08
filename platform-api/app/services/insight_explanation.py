"""Structured, factual explainability metadata for generated insight cards.

Explanations are derived from the actual analysis inputs and results that
produced a card, not invented after the fact. They are persisted on the card
so frozen snapshots and Home pins remain explainable after the live feed is
refreshed.
"""

from __future__ import annotations

import math
from typing import Any

from app.services.ai_governance import get_method_label, infer_governance_key
from app.services.insight_confidence import evaluate_confidence


def _method_label(method: str | None) -> str:
    return get_method_label(method)


def infer_method(
    insight_type: str,
    chart_type: str | None = None,
    sql: str | None = None,
    documents: list[str] | None = None,
    category: str | None = None,
    method_id: str | None = None,
    analysis_intent: str | None = None,
) -> str:
    """Select a controlled analytical-method taxonomy key for an insight."""
    return infer_governance_key(
        insight_type=insight_type,
        chart_type=chart_type,
        sql=sql,
        documents=documents,
        category=category,
        method_id=method_id,
        analysis_intent=analysis_intent,
    )


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
    *,
    result: dict[str, Any] | None = None,
    chart: dict[str, Any] | None = None,
    source_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Delegate to the evidence-based evaluator when a result or chart is
    # available; the row-count heuristic is only a last resort for legacy calls.
    if result or chart:
        try:
            columns = [str(c) for c in (result.get("columns") or [])] if result else []
            rows = result.get("rows") or [] if result else []
            eval_ = evaluate_confidence(
                validation={"rowCount": row_count or len(rows)},
                result=result,
                source_context=source_context,
                columns=columns,
                rows=rows,
                is_document_only=(method == "document_synthesis"),
                has_project_evidence=(result is not None),
            )
            return {
                "level": eval_.level,
                "score": eval_.score,
                "basis": eval_.basis,
                "confidenceEvaluation": eval_.to_dict(),
            }
        except Exception:
            pass
    if method == "document_synthesis":
        level = "low" if row_count is None or row_count < 3 else "medium"
        basis = "Finding is derived from document metadata and summaries without query execution."
    elif sql:
        if row_count and row_count >= 5:
            level = "medium"
            basis = "Result was supported by a successfully executed query."
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
    governance: dict[str, Any] | None = None,
    project_context: dict[str, Any] | None = None,
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
        "confidence": _confidence(
            row_count,
            method,
            sql,
            result=result,
            chart=chart,
            source_context={
                "sourceTables": tables,
                "sourceColumns": fields,
                "periodColumn": period_column,
                "referenceDocuments": documents,
            },
        ),
        "generatedAt": generated_at,
    }
    if governance:
        explanation["governance"] = governance

    if project_context:
        explanation["projectContext"] = {
            "version": project_context.get("version"),
            "aiContextEnabled": project_context.get("ai_context_enabled"),
            "settings": project_context.get("project"),
            "goals": project_context.get("goals") or [],
            "metrics": project_context.get("metrics") or [],
            "risks": project_context.get("risks") or [],
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
