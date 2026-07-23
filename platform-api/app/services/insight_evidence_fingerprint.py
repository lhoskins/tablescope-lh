"""Canonical evidence fingerprints for generated insight cards.

Implements the four fingerprint families required by the evidence-first
insight pipeline:

* planFingerprint    - the analytical intent, source scope, and method
* resultFingerprint    - the canonicalized query result set
* seriesFingerprint    - the chartable series extracted from the result
* semanticFingerprint  - the semantic roles (dimensions, measures, period,
                         grain, filters) derived from the plan and result

Deduplication uses these fingerprints instead of title wording, so identical
evidence cannot surface as multiple cards merely because the LLM phrased the
title or summary differently.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any

EVIDENCE_FINGERPRINT_VERSION = 2


@dataclass
class EvidenceFingerprint:
    fingerprint_version: int = EVIDENCE_FINGERPRINT_VERSION
    plan_fingerprint: str | None = None
    result_fingerprint: str | None = None
    semantic_fingerprint: str | None = None
    series_fingerprint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def dedupe_key(self) -> str | None:
        """Stable key used for duplicate detection.

        Prefers result and series fingerprints (the actual evidence), then falls
        back to the semantic fingerprint when no executable result exists.
        """
        return (
            self.result_fingerprint
            or self.series_fingerprint
            or self.semantic_fingerprint
            or self.plan_fingerprint
        )


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str, ensure_ascii=True)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_whitespace(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip().lower())


def _normalize_sql(sql: str | None) -> str:
    """Normalize SQL for plan fingerprinting without changing semantics.

    Strips extra whitespace, lowercases, and removes string literal values so
    two syntactically identical queries with different filter constants match.
    """
    if not sql:
        return ""
    # Remove quoted literals.
    cleaned = re.sub(r"'[^']*'", "''", sql)
    cleaned = re.sub(r'"[^"]*"', '""', cleaned)
    # Collapse whitespace around punctuation.
    cleaned = re.sub(r"\s*([(),=<>!+\-*/])\s*", r"\1", cleaned)
    return _normalize_whitespace(cleaned)


def _parse_columns_from_sql(sql: str | None) -> list[str]:
    """Best-effort extraction of column identifiers from a SELECT list."""
    if not sql:
        return []
    match = re.search(r"\bSELECT\b(.+?)\bFROM\b", sql, re.IGNORECASE | re.DOTALL)
    if not match:
        return []
    select_body = match.group(1)
    # Split on top-level commas.
    parts: list[str] = []
    depth = 0
    current = ""
    for ch in select_body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(current)
            current = ""
            continue
        current += ch
    parts.append(current)

    columns: list[str] = []
    for part in parts:
        part = part.strip()
        # Strip aliases: "expr AS alias" or "expr alias".
        part = re.sub(r"\bAS\s+\w+\s*$", "", part, flags=re.IGNORECASE).strip()
        # If it ends with an identifier, treat the last dotted token as the col.
        tokens = re.split(r"\s+", part)
        if tokens:
            candidate = tokens[-1].strip("\"'[]")
            if candidate:
                columns.append(candidate)
    return columns


def _parse_tables_from_sql(sql: str | None) -> list[str]:
    """Best-effort extraction of table/view identifiers from a FROM/JOIN clause."""
    if not sql:
        return []
    tables: list[str] = []
    for match in re.finditer(
        r"\b(?:FROM|JOIN)\s+([\"\w]+(?:\.[\"\w]+)?)",
        sql,
        re.IGNORECASE,
    ):
        name = match.group(1).strip("\"'[]")
        if name:
            tables.append(name)
    return tables


def _parse_aggregations_from_sql(sql: str | None) -> list[str]:
    """Return the set of aggregation functions used in the query."""
    if not sql:
        return []
    return sorted(
        {
            m.group(1).upper()
            for m in re.finditer(
                r"\b(SUM|AVG|COUNT|MIN|MAX|STDDEV|VAR)\s*\(",
                sql,
                re.IGNORECASE,
            )
        }
    )


def _canonicalize_value(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float):
        # Round floats to reduce noise from database formatting.
        return round(float(value), 6)
    if isinstance(value, str):
        s = value.strip().replace(",", "").replace("$", "").replace("%", "").lower()
        # Try numeric normalization.
        try:
            n = float(s)
            return round(n, 6)
        except ValueError:
            return s
    return str(value)


def _canonicalize_rows(
    rows: list[dict[str, Any]],
    label_column: str | None,
    time_column: str | None,
    period_like: bool,
) -> list[dict[str, Any]]:
    """Return a deterministic, value-normalized representation of result rows.

    * Time series are ordered by the period/label column.
    * Unordered category rows are sorted by the label column then value.
    * All numeric values are rounded to avoid float noise.
    """
    canonical: list[dict[str, Any]] = []
    for row in rows:
        out = {str(k): _canonicalize_value(row.get(k)) for k in sorted(row.keys())}
        if not out:
            continue
        canonical.append(out)

    sort_key = time_column or label_column
    if sort_key and sort_key in (rows[0] if rows else {}):

        def _sort_val(row: dict[str, Any]) -> Any:
            v = row.get(sort_key)
            if v is None:
                return (1, "")
            return (0, v)

        canonical.sort(key=_sort_val)
    else:
        canonical.sort(key=lambda r: _canonical_json(r))
    return canonical


def build_plan_fingerprint(
    *,
    project_id: int,
    tenant_id: int,
    analysis: dict[str, Any],
    tables: list[str] | None = None,
    method_id: str | None = None,
    source_columns: list[str] | None = None,
) -> str:
    """Canonical fingerprint of the analysis plan (intent + source scope)."""
    sql = _normalize_sql(analysis.get("sql") if analysis else None)
    payload = {
        "v": EVIDENCE_FINGERPRINT_VERSION,
        "tenant_id": tenant_id,
        "project_id": project_id,
        "category": str(analysis.get("category", "")).lower() if analysis else "",
        "chart_type": str(analysis.get("chart_type", "")).lower() if analysis else "",
        "label_column": str(analysis.get("label_column", "")).lower() if analysis else "",
        "value_column": str(analysis.get("value_column", "")).lower() if analysis else "",
        "value_column_2": str(analysis.get("value_column_2", "")).lower() if analysis else "",
        "source_documents": sorted(
            str(d).lower() for d in (analysis.get("source_documents") if analysis else []) or []
        ),
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
    columns: list[str],
    rows: list[Any],
    *,
    label_column: str | None = None,
    time_column: str | None = None,
    period_like: bool = False,
) -> str | None:
    """Canonical fingerprint of an executed result set."""
    if not rows:
        return None
    dict_rows = rows if (rows and isinstance(rows[0], dict)) else [dict(zip(columns, r, strict=False)) for r in rows]
    canonical = _canonicalize_rows(dict_rows, label_column, time_column, period_like)
    # Cap to first 200 rows, same as the data profiler cache.
    payload = {"columns": sorted({str(c) for c in columns}), "rows": canonical[:200]}
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
    project_id: int,
    tenant_id: int,
    tables: list[str] | None,
    columns: list[str] | None,
    dimensions: list[str] | None,
    measures: list[str] | None,
    period_column: str | None,
    filters: list[dict[str, Any]] | None,
    aggregations: list[str] | None,
    grain: str | None,
    intent: str | None,
) -> str:
    """Canonical fingerprint of the semantic interpretation of the evidence.

    This captures what the insight *means* (entities, measures, grain,
    filters) independently of SQL syntax or title wording.
    """
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
    return EvidenceFingerprint(
        plan_fingerprint=plan_fp,
        result_fingerprint=result_fp,
        semantic_fingerprint=semantic_fp,
        series_fingerprint=series_fp,
    )


def fingerprint_for_card(card: dict[str, Any]) -> EvidenceFingerprint:
    """Rehydrate an evidence fingerprint from a card dict (or recompute)."""
    raw = card.get("evidenceFingerprint") or {}
    if raw and isinstance(raw, dict):
        return EvidenceFingerprint(
            fingerprint_version=raw.get("fingerprint_version", EVIDENCE_FINGERPRINT_VERSION),
            plan_fingerprint=raw.get("plan_fingerprint"),
            result_fingerprint=raw.get("result_fingerprint"),
            semantic_fingerprint=raw.get("semantic_fingerprint"),
            series_fingerprint=raw.get("series_fingerprint"),
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


def are_evidence_duplicates(a: EvidenceFingerprint, b: EvidenceFingerprint) -> bool:
    """Return True when two evidence fingerprints describe the same evidence."""
    if a.result_fingerprint and a.result_fingerprint == b.result_fingerprint:
        return True
    if a.series_fingerprint and a.series_fingerprint == b.series_fingerprint:
        return True
    # For document-only or failed-query cards, fall back to semantic fingerprint.
    if (
        a.semantic_fingerprint
        and a.semantic_fingerprint == b.semantic_fingerprint
        and not (a.result_fingerprint or b.result_fingerprint)
    ):
        return True
    return False


def merge_card_evidence(winner: dict[str, Any], duplicate: dict[str, Any]) -> dict[str, Any]:
    """Merge a duplicate card into the winner, preserving supporting evidence.

    The winner keeps its own chart and explanation; supporting source tables,
    documents, and provenance are unioned so nothing is lost.
    """
    winner.setdefault("sources", {"tables": [], "documents": []})
    dup_sources = duplicate.get("sources") or {"tables": [], "documents": []}
    winner["sources"]["tables"] = sorted(
        set(winner["sources"].get("tables", [])) | set(dup_sources.get("tables", []))
    )
    winner["sources"]["documents"] = sorted(
        set(winner["sources"].get("documents", [])) | set(dup_sources.get("documents", []))
    )
    # Preserve any additional provenance that helps explain the merged evidence.
    for key in ("referenceDocuments", "kpiReferences"):
        if duplicate.get(key):
            existing = winner.get(key) or []
            winner[key] = sorted(set(existing) | set(duplicate[key]))
    return winner


def select_duplicate_winner(
    candidates: list[dict[str, Any]],
    priority_fn=None,
) -> dict[str, Any]:
    """Select the representative card from a set of evidence duplicates."""
    if not candidates:
        raise ValueError("empty duplicate group")

    def _priority(card: dict[str, Any]) -> tuple[float, str]:
        if priority_fn:
            return (float(priority_fn(card)), "")
        # Prefer: data-backed > document-backed, higher confidence, richer chart.
        score = 0.0
        if card.get("chart"):
            score += 10.0
        conf = card.get("confidenceScore") or card.get("confidenceEvaluation", {}).get("score")
        if isinstance(conf, (int, float)):
            score += conf
        # Prefer cards with SQL/provenance over bare summaries.
        if card.get("sql"):
            score += 1.0
        # Deterministic tie-breaker: insightId lexical order.
        return (score, str(card.get("insightId") or ""))

    return max(candidates, key=_priority)


def deduplicate_by_evidence(
    cards: list[dict[str, Any]],
    *,
    priority_fn=None,
) -> list[dict[str, Any]]:
    """Collapse cards that share canonical evidence, preserving the best one."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for card in cards:
        fp = fingerprint_for_card(card)
        key = fp.dedupe_key
        if not key:
            # Cannot fingerprint safely; pass through.
            groups.setdefault(f"passthrough-{id(card)}", []).append(card)
            continue
        groups.setdefault(key, []).append(card)

    winners: list[dict[str, Any]] = []
    for group in groups.values():
        winner = select_duplicate_winner(group, priority_fn=priority_fn)
        for dup in group:
            if dup is not winner:
                winner = merge_card_evidence(winner, dup)
        winners.append(winner)
    return winners
