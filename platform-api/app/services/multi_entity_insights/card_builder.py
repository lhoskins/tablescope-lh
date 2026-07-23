"""Convert a multi-entity payload into the InsightCard dict shape.

This module only produces plain dicts so it stays decoupled from the Home
Intelligence card construction path.
"""

from __future__ import annotations

from typing import Any

from app.services.multi_entity_insights.contract import MultiEntityInsightPayload


def _fmt_value(v: float | None, fmt: str) -> str:
    if v is None:
        return "—"
    if fmt == "percent":
        return f"{v * 100:.1f}%"
    if fmt == "currency":
        return f"${v:,.0f}"
    if v == int(v):
        return str(int(v))
    return f"{v:.2f}"


def _delta(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return a - b


def build_chart(entities: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a grouped-bar chart of entity metrics."""
    if not entities:
        return {"type": "bar", "data": {"series": []}}
    # Use the first metric for each entity as the primary series.
    series: list[dict[str, Any]] = []
    for ent in entities:
        for m in ent.get("metrics", []):
            if m.get("value") is not None:
                series.append({
                    "label": f"{ent['name']} — {m['label']}",
                    "value": float(m["value"]),
                })
    return {
        "type": "bar",
        "subtype": "grouped_bar",
        "title": "",
        "data": {"series": series},
    }


def to_card_kwargs(
    payload: MultiEntityInsightPayload,
    project: Any,
) -> dict[str, Any]:
    """Return keyword arguments that can be passed to ``home_intelligence._card``.

    Extra multi-entity fields live inside ``metadata`` so the existing card
    renderer remains backward-compatible while a future component can read them.
    """
    chart = payload.chart or build_chart(payload.entities)
    return {
        "insight_type": payload.insight_type,
        "severity": payload.severity,
        "title": payload.title,
        "summary": payload.summary,
        "chart": chart,
        "chart_type": chart.get("type") if chart else None,
        "label_column": "label",
        "value_column": "value",
        "tables": payload.tables,
        "sql": payload.sql,
        "metadata": {
            "cardType": "multi_entity",
            "entityType": payload.entity_type,
            "entities": payload.entities,
            "evidenceStatus": payload.evidence_status,
            "analyticalMethod": payload.method_envelope,
            "analysis": {
                "primary": payload.method_envelope,
                "supporting": payload.supporting_envelopes,
            },
            "lineage": payload.lineage.model_dump(mode="json"),
            "sourceStrategy": payload.source_strategy.model_dump(mode="json"),
            "fallbackReason": payload.fallback_reason,
            "warnings": payload.warnings,
            "businessQuestion": payload.business_question,
        },
        "method": payload.method_envelope.get("method") if payload.method_envelope else None,
        "result": {
            "columns": list(payload.method_envelope.get("results", {}).keys()) if payload.method_envelope else [],
            "rows": [],
        } if payload.method_envelope else None,
    }


def build_entities_payload(
    result_rows: list[dict[str, Any]],
    entity_col: str,
    measures: list[Any],
) -> list[dict[str, Any]]:
    """Group final frame rows into per-entity metric dicts."""
    by_entity: dict[str, dict[str, Any]] = {}
    for row in result_rows:
        key = row.get(entity_col)
        if key is None:
            continue
        key = str(key)
        if key not in by_entity:
            by_entity[key] = {"id": key, "name": key, "metrics": []}
            if "name" in row:
                by_entity[key]["name"] = row["name"]
        for m in measures:
            val = row.get(m.name)
            if val is None:
                continue
            try:
                num = float(val)
            except (TypeError, ValueError):
                continue
            by_entity[key]["metrics"].append({
                "key": m.name,
                "label": m.name.replace("_", " ").title(),
                "value": num,
                "formattedValue": _fmt_value(num, m.format or "number"),
            })
    # Add a delta to the first metric where possible.
    for ent in by_entity.values():
        if len(ent["metrics"]) >= 2:
            first = ent["metrics"][0]
            second = ent["metrics"][1]
            first["change"] = _delta(first["value"], second["value"])
    return list(by_entity.values())
