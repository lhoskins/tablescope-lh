
from __future__ import annotations

import re
from typing import Any

from .canonicalization import (
    EVIDENCE_FINGERPRINT_VERSION,
    EvidenceFingerprint,
    _canonical_json,
    _canonicalize_rows,
    _canonicalize_value,
    _normalize_sql,
    _normalize_whitespace,
    _parse_aggregations_from_sql,
    _parse_columns_from_sql,
    _parse_tables_from_sql,
    _sha256,
)


def build_grounding_fingerprint(
    grounding: dict[str, Any] | None,
) -> str | None:
    """Canonical fingerprint of the evidence used to ground the answer.

    Hashes the KG version, the IDs of the KG nodes, document chunks, and
    governed KPIs referenced, plus the mix of retrieval methods.
    """
    if not grounding:
        return None
    passages = grounding.get("passages") or []
    kg_nodes = grounding.get("kg_nodes") or grounding.get("kgNodes") or []
    kpis = grounding.get("kpis") or []

    payload = {
        "kg_version_id": grounding.get("kg_version_id") or grounding.get("kgVersionId"),
        "kg_node_ids": sorted(
            {str(n.get("id")) for n in kg_nodes if n.get("id")}
        ),
        "chunk_keys": sorted(
            {
                f"{p.get('document_id') or p.get('documentId')}:{p.get('chunk_index') or p.get('chunkIndex')}:{p.get('source_type') or p.get('sourceType')}"
                for p in passages
            }
        ),
        "kpi_keys": sorted(
            {str(k.get("kpi_key") or k.get("kpiKey") or "") for k in kpis if k.get("kpi_key") or k.get("kpiKey")}
        ),
        "retrieval_methods": sorted(
            {str(p.get("retrieval_method") or p.get("retrievalMethod") or "") for p in passages}
        ),
        "question": _normalize_whitespace(grounding.get("question")),
    }
    return _sha256(_canonical_json(payload))


def build_plan_fingerprint(
    analysis: dict[str, Any] | None = None,
    *,
    project_id: int,
    tenant_id: int,
    tables: list[str] | None = None,
    method_id: str | None = None,
    source_columns: list[str] | None = None,
) -> str:
    """Canonical fingerprint of the analysis plan (intent + source scope)."""
    analysis = analysis or {}
    sql = _normalize_sql(analysis.get("sql") if analysis else None)

    # Source documents now carry chunk-level granularity when available.
    source_documents = analysis.get("source_documents") or []
    source_chunks: list[str] = []
    for d in source_documents:
        if isinstance(d, dict):
            doc_id = str(d.get("id") or d.get("documentId") or "")
            for ch in d.get("chunks") or []:
                idx = ch.get("chunk_index") if isinstance(ch, dict) else None
                source_chunks.append(f"{doc_id}:{idx}")
        else:
            source_chunks.append(str(d).lower())

    payload = {
        "v": EVIDENCE_FINGERPRINT_VERSION,
        "tenant_id": tenant_id,
        "project_id": project_id,
        "category": str(analysis.get("category", "")).lower() if analysis else "",
        "chart_type": str(analysis.get("chart_type", "")).lower() if analysis else "",
        "label_column": str(analysis.get("label_column", "")).lower() if analysis else "",
        "value_column": str(analysis.get("value_column", "")).lower() if analysis else "",
        "value_column_2": str(analysis.get("value_column_2", "")).lower() if analysis else "",
        "source_documents": sorted(source_chunks),
        "sql_columns": sorted(
            c.lower() for c in (source_columns if source_columns else _parse_columns_from_sql(sql))
        ),
        "sql_tables": sorted(t.lower() for t in (tables or _parse_tables_from_sql(sql))),
        "aggregations": _parse_aggregations_from_sql(sql),
        "method_id": str(method_id or "").lower(),
        "sql_normalized": sql,
    }
    return _sha256(_canonical_json(payload))


def build_result_fingerprint(
    columns: dict[str, Any] | list[str] | None = None,
    rows: list[Any] | None = None,
    *,
    label_column: str | None = None,
    time_column: str | None = None,
    period_like: bool = False,
) -> str | None:
    """Canonical fingerprint of an executed result set.

    Accepts either a ``{"columns": [...], "rows": [...]}`` result dict as the
    first positional argument or explicit ``columns``/``rows`` lists.
    """
    if isinstance(columns, dict):
        result = columns
        column_list = [str(c) for c in (result.get("columns") or [])]
        row_list = result.get("rows") or []
    else:
        column_list = [str(c) for c in (columns or [])]
        row_list = rows or []

    if not row_list:
        return None
    dict_rows = row_list if (row_list and isinstance(row_list[0], dict)) else [dict(zip(column_list, r, strict=False)) for r in row_list]
    canonical = _canonicalize_rows(dict_rows, column_list, label_column, time_column, period_like)
    # Cap to first 200 rows, same as the data profiler cache.
    payload = {"columns": column_list, "rows": canonical[:200]}
    return _sha256(_canonical_json(payload))


def build_series_fingerprint(chart: dict[str, Any] | None) -> str | None:
    """Canonical fingerprint of the rendered chart series.

    Uses only label/value/value2 so that two charts with identical data but
    different titles map to the same fingerprint.
    """
    if not chart or not isinstance(chart, dict):
        return None
    data = chart.get("data") or {}
    series = data.get("series") or data.get("kpis")
    if not series:
        return None
    canonical: list[dict[str, Any]] = []
    for point in series:
        if not isinstance(point, dict):
            continue
        item: dict[str, Any] = {}
        if "label" in point:
            item["label"] = str(point["label"]).strip().lower()
        if "value" in point:
            item["value"] = _canonicalize_value(point.get("value"))
        if "value2" in point:
            item["value2"] = _canonicalize_value(point.get("value2"))
        if item:
            canonical.append(item)
    if not canonical:
        return None
    canonical.sort(key=_canonical_json)
    return _sha256(_canonical_json(canonical))


def build_semantic_fingerprint(
    *,
    project_id: int = 0,
    tenant_id: int = 0,
    tables: list[str] | None = None,
    columns: list[str] | None = None,
    dimensions: list[str] | None = None,
    measures: list[str] | None = None,
    period_column: str | None = None,
    filters: list[dict[str, Any]] | None = None,
    aggregations: list[str] | None = None,
    grain: str | None = None,
    intent: str | None = None,
    # Legacy aliases used by direct callers and older tests.
    title: str | None = None,
    summary: str | None = None,
    row_count: int | None = None,
    label_column: str | None = None,
    value_column: str | None = None,
    insight_type: str | None = None,
) -> str:
    """Canonical fingerprint of the semantic interpretation of the evidence.

    This captures what the insight *means* (entities, measures, grain,
    filters) independently of SQL syntax or title wording. ``title`` and
    ``summary`` are intentionally ignored so wording does not affect identity.
    """
    # Legacy mapping for callers that pass column-oriented descriptors.
    if columns and not dimensions and not measures:
        dims = [str(c).lower() for c in columns if c != value_column]
        if label_column and label_column not in dims:
            dims.append(str(label_column).lower())
        dimensions = dims
        if value_column:
            measures = [str(value_column).lower()]
    if insight_type and not intent:
        intent = insight_type
    if row_count is not None and not grain:
        grain = "many" if row_count >= 10 else "few"

    # ``title`` and ``summary`` are deliberately ignored.
    _ = (title, summary)

    payload = {
        "v": EVIDENCE_FINGERPRINT_VERSION,
        "tenant_id": tenant_id,
        "project_id": project_id,
        "tables": sorted(t.lower() for t in (tables or [])),
        "columns": sorted(str(c).lower() for c in (columns or [])),
        "dimensions": sorted(str(d).lower() for d in (dimensions or [])),
        "measures": sorted(str(m).lower() for m in (measures or [])),
        "period_column": str(period_column or "").lower(),
        "filters": sorted(
            _canonical_json({str(k).lower(): _canonicalize_value(v) for k, v in f.items()})
            for f in (filters or [])
        ),
        "aggregations": sorted(str(a).lower() for a in (aggregations or [])),
        "grain": str(grain or "").lower(),
        "intent": str(intent or "").lower(),
    }
    return _sha256(_canonical_json(payload))


def build_evidence_fingerprint(
    *,
    project_id: int,
    tenant_id: int,
    analysis: dict[str, Any] | None,
    result: dict[str, Any] | None,
    chart: dict[str, Any] | None,
    tables: list[str] | None = None,
    columns: list[str] | None = None,
    label_column: str | None = None,
    value_column: str | None = None,
    value_column_2: str | None = None,
    method_id: str | None = None,
    dimensions: list[str] | None = None,
    measures: list[str] | None = None,
    period_column: str | None = None,
    filters: list[dict[str, Any]] | None = None,
    aggregations: list[str] | None = None,
    grain: str | None = None,
    intent: str | None = None,
    grounding_evidence: dict[str, Any] | None = None,
) -> EvidenceFingerprint:
    """Compute the full evidence fingerprint package for an insight card."""
    result_columns = []
    result_rows: list[Any] = []
    if result and isinstance(result, dict):
        result_columns = [str(c) for c in (result.get("columns") or [])]
        result_rows = result.get("rows") or []

    period_like = bool(period_column) or bool(
        result_columns
        and any(
            re.search(r"(period|month|year|quarter|week|date|day|fiscal|time)", str(c), re.I)
            for c in result_columns
        )
    )
    time_col = period_column
    if not time_col and result_columns:
        for c in result_columns:
            if re.search(r"(period|month|year|quarter|week|date|day|fiscal|time)", str(c), re.I):
                time_col = c
                break

    plan_fp = build_plan_fingerprint(
        project_id=project_id,
        tenant_id=tenant_id,
        analysis=analysis or {},
        tables=tables,
        method_id=method_id,
        source_columns=columns,
    )
    result_fp = build_result_fingerprint(
        columns=result_columns,
        rows=result_rows,
        label_column=label_column,
        time_column=time_col,
        period_like=period_like,
    )
    series_fp = build_series_fingerprint(chart)
    semantic_fp = build_semantic_fingerprint(
        project_id=project_id,
        tenant_id=tenant_id,
        tables=tables,
        columns=columns or result_columns,
        dimensions=dimensions or ([label_column] if label_column else []),
        measures=measures or ([value_column] if value_column else []),
        period_column=period_column or time_col,
        filters=filters,
        aggregations=aggregations,
        grain=grain,
        intent=intent,
    )
    grounding_fp = build_grounding_fingerprint(grounding_evidence)
    return EvidenceFingerprint(
        plan_fingerprint=plan_fp,
        result_fingerprint=result_fp,
        semantic_fingerprint=semantic_fp,
        series_fingerprint=series_fp,
        grounding_fingerprint=grounding_fp,
    )


def fingerprint_for_card(card: dict[str, Any]) -> EvidenceFingerprint:
    """Rehydrate an evidence fingerprint from a card dict (or recompute)."""
    raw = card.get("evidenceFingerprint") or {}
    if raw and isinstance(raw, dict):
        return EvidenceFingerprint(
            fingerprint_version=raw.get("fingerprint_version") or raw.get("fingerprintVersion", EVIDENCE_FINGERPRINT_VERSION),
            plan_fingerprint=raw.get("plan_fingerprint") or raw.get("planFingerprint"),
            result_fingerprint=raw.get("result_fingerprint") or raw.get("resultFingerprint"),
            semantic_fingerprint=raw.get("semantic_fingerprint") or raw.get("semanticFingerprint"),
            series_fingerprint=raw.get("series_fingerprint") or raw.get("seriesFingerprint"),
            grounding_fingerprint=raw.get("grounding_fingerprint") or raw.get("groundingFingerprint"),
        )
    return build_evidence_fingerprint(
        project_id=int(card.get("projectId") or 0),
        tenant_id=int(card.get("tenant_id") or 0),
        analysis=card,
        result=card.get("validation"),
        chart=card.get("chart"),
        tables=card.get("sources", {}).get("tables"),
        columns=card.get("validation", {}).get("columnsReturned"),
        label_column=card.get("labelColumn"),
        value_column=card.get("valueColumn"),
        value_column_2=card.get("valueColumn2"),
        method_id=(card.get("analyticalMethod") or {}).get("method")
            or card.get("insightMethod"),
    )
