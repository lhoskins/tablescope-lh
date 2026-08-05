
from __future__ import annotations

import math
from typing import Any

from .types import _HIGH, _MEDIUM, ConfidenceFactor


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        s = value.strip().replace(",", "").replace("$", "").replace("%", "")
        if not s:
            return None
        try:
            n = float(s)
            return n if math.isfinite(n) else None
        except ValueError:
            return None
    return None


def _pct_non_null(rows: list[Any], value_col: str | None) -> float:
    if not rows or not value_col:
        return 0.0
    total = len(rows)
    non_null = sum(1 for r in rows if _to_float(r.get(value_col) if isinstance(r, dict) else None) is not None)
    return non_null / total if total else 0.0


def _coverage_fraction(periods: list[Any]) -> float:
    """Rough period-continuity heuristic: count of unique periods / range size.

    Works for year/month/quarter labels. Returns 1.0 when continuity cannot be
    assessed.
    """
    if not periods:
        return 1.0
    try:
        nums = sorted({float(p) for p in periods if _to_float(p) is not None})
    except (TypeError, ValueError):
        return 1.0
    if len(nums) < 2:
        return 1.0
    span = nums[-1] - nums[0]
    if span <= 0:
        return 1.0
    return min(1.0, len(nums) / (span + 1))


def _level_for_score(score: float) -> str:
    if score >= _HIGH:
        return "high"
    if score >= _MEDIUM:
        return "medium"
    return "low"


def _basis_from_factors(
    factors: list[ConfidenceFactor], caps: list[str]
) -> str:
    passed = [f for f in factors if f.status == "passed" and f.score >= 0.75]
    if passed:
        names = [f.label for f in passed]
        base = (
            "Confidence is high because: " + "; ".join(names) + "."
        )
    else:
        partial = [f for f in factors if f.status == "partial"]
        if partial:
            base = (
                "Confidence is medium. Supporting factor: "
                + partial[0].label
                + "."
            )
        else:
            base = "Confidence is low: the evidence is thin or incomplete."
    if caps:
        base += " " + caps[0]
    return base


def _gap_text(factor: ConfidenceFactor) -> str | None:
    if factor.status == "passed":
        return None
    if factor.code == "data_sufficiency":
        return "Collect more rows or a longer time range."
    if factor.code == "data_quality":
        return "Reduce null or malformed values in the metric columns."
    if factor.code == "analytical_validation":
        return "Run a statistical method (trend, anomaly, comparison) that the engine can validate."
    if factor.code == "period_integrity":
        return "Fill missing periods so the time series is continuous."
    if factor.code == "relationship_safety":
        return "Verify join keys resolve uniquely or add a curated scope link."
    if factor.code == "lineage_completeness":
        return "Add source metadata or a saved query to ground the finding."
    if factor.code == "corroboration":
        return "Corroborate with a document reference or secondary data source."
    if factor.code == "execution_grounding":
        return "Ensure the query executes and returns a usable result."
    if factor.status == "failed":
        return f"{factor.label} is insufficient."
    return None
