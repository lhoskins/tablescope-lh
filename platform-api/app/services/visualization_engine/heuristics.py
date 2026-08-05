from __future__ import annotations

import re
from typing import Any, cast

from .shape import _is_period_dimension, _to_float
from .types import ValueFormat, _Shape

_SHARE_LABEL_KEYS = (
    "categor", "type", "status", "segment", "region", "channel", "class",
    "group", "tier", "rating", "priority", "department", "mode", "method",
    "reason", "country", "state", "industry",
)
_METRIC_LABEL_KEYS = (
    "metric", "measure", "name", "label", "kpi", "indicator", "stat",
    "title", "description", "field",
)
_ID_LABEL_RE = re.compile(
    r"(?i)(sup|sku|id|code|part|item|vendor|customer|prod)[-_ ]?\w*\d"
)
_PCT_COL_RE = re.compile(
    r"(?i)\b(rate|pct|percent|percentage|ratio|share|on[_ -]?time|utiliz\w*|"
    r"defect[_ ]?rate|yield|compliance)\b"
)
_CURRENCY_COL_RE = re.compile(
    r"(?i)\b(revenue|cost|spend|spending|price|amount|sales|value|budget|usd|"
    r"dollars?)\b"
)
_COUNT_COL_RE = re.compile(
    r"(?i)\b(count|qty|quantity|units?|number|orders?|shipments?|items?|"
    r"records?|inspections?|defects?)\b"
)


def detect_value_format(name: str, values: list[Any]) -> ValueFormat:
    """Classify a metric's display format from its name + values."""
    # Treat snake_case as words so ``total_revenue`` matches ``revenue`` etc.
    label = (name or "").replace("_", " ")
    if _PCT_COL_RE.search(label):
        return "percent"
    if _CURRENCY_COL_RE.search(label):
        return "currency"
    if _COUNT_COL_RE.search(label):
        return "count"
    nums = [f for v in values if (f := _to_float(v)) is not None]
    if nums and all(0.0 <= v <= 1.0 for v in nums) and any(
        v not in (0.0, 1.0) for v in nums
    ):
        return "percent"
    return "number"


def _looks_like_share(label_col: str, cardinality: int, all_positive: bool) -> bool:
    if not (3 <= cardinality <= 8) or not all_positive:
        return False
    return any(k in (label_col or "").lower() for k in _SHARE_LABEL_KEYS)


def _looks_like_id_labels(labels: list[str]) -> bool:
    if not labels:
        return False
    idish = sum(
        1
        for lbl in labels
        if _ID_LABEL_RE.search(lbl) or len(lbl) >= 12 or any(c.isdigit() for c in lbl)
    )
    return idish >= max(1, int(len(labels) * 0.5))


def _looks_like_metric_label(label_col: str | None) -> bool:
    if not label_col:
        return False
    lower = label_col.lower()
    return any(k in lower for k in _METRIC_LABEL_KEYS)


#: A column name that identifies a record rather than describing a business
#: category (``order_id``, ``sku``, ``part_number``, ``uuid``). Charting one
#: produces a bar per record — technically valid, analytically worthless.
#: A near-unique column needs at least this many rows before uniqueness means
#: anything, and this share of distinct values to look key-like.
_IDENTIFIER_MIN_ROWS = 20
_IDENTIFIER_UNIQUENESS = 0.85

_ID_COLUMN_NAME_RE = re.compile(
    r"(?i)(^|[_\s-])(id|ids|uuid|guid|key|pk|fk|no|num|number|code|sku|ref|"
    r"reference|serial|barcode|batch|lot|ticket|invoice|order|record)([_\s-]|$)"
)


def is_identifier_column(
    shape: _Shape, col: str, dict_rows: list[dict[str, Any]]
) -> bool:
    """True when ``col`` identifies rows rather than grouping them.

    Two independent signals, either of which disqualifies a column from being a
    chart dimension:

    * **Name** — the column reads like a key (``order_id``, ``sku``, ``ref_no``).
    * **Uniqueness** — its distinct-value ratio approaches one row per value, so
      grouping by it cannot aggregate anything.

    Period columns are never identifiers: a date axis is a legitimate dimension
    even when every value is distinct.
    """
    if _is_period_dimension(shape, col):
        return False
    if _ID_COLUMN_NAME_RE.search(col):
        return True

    # Uniqueness alone is NOT evidence of a key: an aggregated result has one
    # row per category by construction (8 suppliers in 8 rows is a bar chart,
    # not a key). A near-unique column is only an identifier when it sits
    # alongside a genuine low-cardinality dimension — the signature of raw,
    # row-level data carrying a key plus a real category.
    total = len([r for r in dict_rows if r.get(col) is not None])
    if total < _IDENTIFIER_MIN_ROWS:
        return False
    try:
        distinct = len({str(r.get(col)) for r in dict_rows if r.get(col) is not None})
    except TypeError:
        return False
    if distinct / total < _IDENTIFIER_UNIQUENESS:
        return False
    for other in shape.dimensions:
        if other == col or _is_period_dimension(shape, other):
            continue
        try:
            other_distinct = len(
                {str(r.get(other)) for r in dict_rows if r.get(other) is not None}
            )
        except TypeError:
            continue
        if other_distinct and other_distinct * 4 <= distinct:
            return True
    return False


def business_dimensions(
    shape: _Shape, dict_rows: list[dict[str, Any]]
) -> list[str]:
    """Non-period dimensions that describe the business, not row identity."""
    return [
        c
        for c in shape.dimensions
        if not _is_period_dimension(shape, c)
        and not is_identifier_column(shape, c, dict_rows)
    ]


def _detect_semantic_roles(
    columns: list[str], rows: list[dict[str, Any]]
) -> dict[str, str | None]:
    """Infer source/target/value/group/stage/rate roles from column names and data.

    Roles are hints for richer families (sankey, treemap, funnel, radial_bar,
    radar). They never force an unrenderable chart; the shape still wins.
    """
    roles: dict[str, str | None] = {
        "source": None,
        "target": None,
        "value": None,
        "group": None,
        "stage": None,
        "rate": None,
    }
    lower = {c.lower(): c for c in columns}

    # Source / target / value triad for Sankey.
    for key in ("source", "from", "origin", "src"):
        if key in lower:
            roles["source"] = lower[key]
            break
    for key in ("target", "to", "destination", "dst", "dest"):
        if key in lower:
            roles["target"] = lower[key]
            break
    for key in ("value", "weight", "amount", "flow", "volume"):
        if key in lower:
            roles["value"] = lower[key]
            break

    # Stage column for funnel.
    stage_re = re.compile(r"(stage|step|phase|status|pipeline|funnel)", re.I)
    for c in columns:
        if stage_re.search(c):
            roles["stage"] = c
            break

    # Group / parent for treemap.
    group_re = re.compile(r"(group|category|class|type|segment|region|department|parent)", re.I)
    for c in columns:
        if group_re.search(c) and c != roles.get("source") and c != roles.get("target"):
            roles["group"] = c
            break

    # Rate / percent column for radial bar.
    rate_re = re.compile(r"(rate|pct|percent|percentage|ratio|compliance|target|on_time|on-time|oee|utilization|score)", re.I)
    for c in columns:
        if rate_re.search(c):
            # Only promote if values are 0..1 or 0..100.
            nums = cast(
                "list[float]",
                [
                    _to_float(r.get(c))
                    for r in rows
                    if isinstance(r, dict) and _to_float(r.get(c)) is not None
                ][:50],
            )
            if nums and all(0 <= v <= 100 for v in nums) and any(v not in (0, 1, 100) for v in nums):
                roles["rate"] = c
                break

    # If no explicit value, prefer a numeric measure named revenue/cost/count.
    if roles["value"] is None:
        for c in columns:
            if re.search(r"(revenue|cost|spend|sales|amount|count|value|total|sum)", c, re.I):
                # Verify numeric.
                sample = [_to_float(r.get(c)) for r in rows if isinstance(r, dict) and _to_float(r.get(c)) is not None]
                if sample:
                    roles["value"] = c
                    break
    return roles


def _is_monotonic_decreasing(values: list[float]) -> bool:
    return all(values[i] >= values[i + 1] for i in range(len(values) - 1))
