
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
    columns: list[str] | None,
    label_column: str | None,
    time_column: str | None,
    period_like: bool,
) -> list[dict[str, Any]]:
    """Return a deterministic, value-normalized representation of result rows.

    * Output keys follow the supplied ``columns`` order when available so column
      reordering changes the fingerprint.
    * Time series are ordered by the period/label column.
    * Unordered category rows are sorted by the label column then value.
    * All numeric values are rounded to avoid float noise.
    """
    key_order = [str(c) for c in (columns or [])]
    if not key_order and rows:
        key_order = sorted({str(k) for r in rows for k in r.keys()})

    canonical: list[dict[str, Any]] = []
    for row in rows:
        out: dict[str, Any] = {}
        for k in key_order:
            if k in row:
                out[k] = _canonicalize_value(row.get(k))
        if not out:
            continue
        canonical.append(out)

    sort_key = time_column or label_column
    if sort_key and sort_key in key_order:

        def _sort_val(row: dict[str, Any]) -> Any:
            v = row.get(sort_key)
            if v is None:
                return (1, "")
            return (0, v)

        canonical.sort(key=_sort_val)
    else:
        canonical.sort(key=lambda r: _canonical_json(r))
    return canonical
