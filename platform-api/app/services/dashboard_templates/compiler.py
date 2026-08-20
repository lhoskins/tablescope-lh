"""Safe deterministic Template Metric and Batch Query Compiler."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_$.]*$")
_PERIOD_DAYS = {"30_days": 30, "60_days": 60, "90_days": 90, "6_months": 183, "1_year": 365, "2_years": 730}


@dataclass(slots=True)
class CompiledBatchQuery:
    query_key: str
    sql_template: str
    compiled_sql: str
    metric_keys: list[str]
    dashboard_keys: list[str]
    lineage: dict[str, Any]


def _quote_identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"Unsafe mapped identifier: {value!r}")
    return ".".join(f'"{part}"' for part in value.split("."))


def _literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int | float):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _mapped_field(field_mapping: dict, entity: str, canonical: str) -> str:
    value = (field_mapping.get(entity) or {}).get(canonical)
    if not value:
        raise ValueError(f"Missing mapping for {entity}.{canonical}")
    return _quote_identifier(str(value))


def _filter_sql(spec: dict | None, entity: str, field_mapping: dict) -> str:
    if not spec:
        return ""
    column = _mapped_field(field_mapping, entity, str(spec.get("field", "")))
    operator, value = spec.get("operator", "eq"), spec.get("value")
    if operator == "eq":
        return f" AND {column} = {_literal(value)}"
    if operator == "neq":
        return f" AND {column} <> {_literal(value)}"
    if operator == "in" and isinstance(value, list) and value:
        return f" AND {column} IN ({', '.join(_literal(item) for item in value)})"
    if operator == "is_null":
        return f" AND {column} IS NULL"
    raise ValueError(f"Unsupported metric filter operator: {operator}")


def _aggregate(metric: dict, entity: str, field_mapping: dict, period_condition: str) -> str:
    aggregation = metric.get("aggregation", "count_distinct")
    value_column = _mapped_field(field_mapping, entity, metric["valueField"])
    condition = period_condition + _filter_sql(metric.get("filter"), entity, field_mapping)
    if aggregation == "count_distinct":
        return f"COUNT(DISTINCT CASE WHEN {condition} THEN {value_column} END)"
    if aggregation == "count":
        return f"SUM(CASE WHEN {condition} THEN 1 ELSE 0 END)"
    if aggregation in {"sum", "avg"}:
        return f"{aggregation.upper()}(CASE WHEN {condition} THEN CAST({value_column} AS double) END)"
    if aggregation == "ratio":
        numerator_condition = condition + _filter_sql(metric.get("numeratorFilter"), entity, field_mapping)
        denominator_name = metric.get("denominatorField")
        if denominator_name:
            denominator_column = _mapped_field(field_mapping, entity, denominator_name)
            numerator = f"SUM(CASE WHEN {numerator_condition} THEN CAST({value_column} AS double) END)"
            denominator = f"SUM(CASE WHEN {condition} THEN CAST({denominator_column} AS double) END)"
        else:
            numerator = f"COUNT(DISTINCT CASE WHEN {numerator_condition} THEN {value_column} END)"
            denominator = f"COUNT(DISTINCT CASE WHEN {condition} THEN {value_column} END)"
        return f"100.0 * {numerator} / NULLIF({denominator}, 0)"
    raise ValueError(f"Unsupported aggregation: {aggregation}")


def validate_binding(*, source_mapping: dict, field_mapping: dict, metric_manifest: list[dict], dimension_config: dict) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not metric_manifest:
        errors.append("The selected template has no metric manifest.")
    for metric in metric_manifest:
        entity = str(metric.get("entity", ""))
        if not source_mapping.get(entity):
            errors.append(f"Select a datasource for {entity}.")
            continue
        required = {str(metric.get("valueField", "")), str(metric.get("dateField", ""))}
        if metric.get("denominatorField"):
            required.add(str(metric["denominatorField"]))
        for filter_name in ("filter", "numeratorFilter"):
            if metric.get(filter_name):
                required.add(str(metric[filter_name].get("field", "")))
        for field in sorted(required - {""}):
            if not (field_mapping.get(entity) or {}).get(field):
                errors.append(f"Map {entity}.{field}.")
    dimension_field = dimension_config.get("field")
    if dimension_field and not any((field_mapping.get(entity) or {}).get(dimension_field) for entity in source_mapping):
        warnings.append(f"Dimension field {dimension_field!r} is not mapped; dashboards will show an unfiltered total.")
    return {"valid": not errors, "errors": sorted(set(errors)), "warnings": sorted(set(warnings))}


def period_bounds(period: str, *, as_of: date | None = None) -> dict[str, str]:
    if period not in _PERIOD_DAYS:
        raise ValueError(f"Unsupported period: {period}")
    end = as_of or datetime.now(UTC).date()
    start = end - timedelta(days=_PERIOD_DAYS[period])
    previous = start - timedelta(days=_PERIOD_DAYS[period])
    return {"period_start": start.isoformat(), "period_end": end.isoformat(), "previous_start": previous.isoformat()}


def render_sql_template(sql_template: str, *, period_start: str, period_end: str, previous_start: str, dimension_column: str | None = None, dimension_value: str | None = None) -> str:
    replacements = {
        "{{period_start}}": _literal(period_start),
        "{{period_end}}": _literal(period_end),
        "{{previous_start}}": _literal(previous_start),
        "{{dimension_filter}}": "",
    }
    if dimension_column and dimension_value:
        replacements["{{dimension_filter}}"] = f"AND {_quote_identifier(dimension_column)} = {_literal(dimension_value)}"
    rendered = sql_template
    for token, value in replacements.items():
        rendered = rendered.replace(token, value)
    if "{{" in rendered or "}}" in rendered:
        raise ValueError("Unresolved SQL template token")
    return rendered


def compile_batch_queries(*, source_mapping: dict, field_mapping: dict, metric_manifest: list[dict], dimension_config: dict, period: str = "30_days", as_of: date | None = None) -> list[CompiledBatchQuery]:
    validation = validate_binding(source_mapping=source_mapping, field_mapping=field_mapping, metric_manifest=metric_manifest, dimension_config=dimension_config)
    if not validation["valid"]:
        raise ValueError("; ".join(validation["errors"]))
    grouped: dict[tuple[str, str], list[dict]] = {}
    for metric in metric_manifest:
        grouped.setdefault((metric["entity"], metric["dateField"]), []).append(metric)
    dates = period_bounds(period, as_of=as_of)
    queries: list[CompiledBatchQuery] = []
    for (entity, date_field), metrics in grouped.items():
        view = _quote_identifier(str(source_mapping[entity]))
        date_column = _mapped_field(field_mapping, entity, date_field)
        current = f"{date_column} >= {{{{period_start}}}} AND {date_column} < {{{{period_end}}}}"
        previous = f"{date_column} >= {{{{previous_start}}}} AND {date_column} < {{{{period_start}}}}"
        parts: list[str] = []
        for metric in metrics:
            key = _quote_identifier(metric["key"])
            parts.extend((f"{_aggregate(metric, entity, field_mapping, current)} AS {key}", f'{_aggregate(metric, entity, field_mapping, previous)} AS "{metric["key"]}__previous"'))
        window = f"{date_column} >= {{{{previous_start}}}} AND {date_column} < {{{{period_end}}}}"
        template = f"SELECT {', '.join(parts)} FROM {view} WHERE {window} {{{{dimension_filter}}}}"
        dashboard_keys = sorted({str(key) for metric in metrics for key in metric.get("dashboardKeys", [])})
        common = {"metric_keys": [metric["key"] for metric in metrics], "dashboard_keys": dashboard_keys}
        queries.append(CompiledBatchQuery(f"summary_{entity}_{date_field}", template, render_sql_template(template, **dates), lineage={"entity": entity, "view": source_mapping[entity], "dateField": date_field, "kind": "summary"}, **common))
        dimension_field = dimension_config.get("field")
        dimension_name = (field_mapping.get(entity) or {}).get(dimension_field) if dimension_field else None
        if dimension_name:
            dimension = _quote_identifier(str(dimension_name))
            dimension_template = f'SELECT {dimension} AS "dimension", {", ".join(parts)} FROM {view} WHERE {window} GROUP BY {dimension} ORDER BY {dimension}'
            queries.append(CompiledBatchQuery(f"dimension_{entity}_{date_field}", dimension_template, render_sql_template(dimension_template, **dates), lineage={"entity": entity, "view": source_mapping[entity], "dateField": date_field, "dimensionField": dimension_field, "kind": "dimension"}, **common))
    return queries
