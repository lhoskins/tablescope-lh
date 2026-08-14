"""Month-over-month comparison helpers for ITSM KPI cards."""

from __future__ import annotations

import math
from datetime import UTC, datetime


def _safe_divide(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None:
        return None
    if denominator == 0:
        return None
    return numerator / denominator


def compute_comparison(
    current_value: float | None,
    previous_value: float | None,
    polarity: str = "higher_is_better",
    current_label: str = "current",
    previous_label: str = "previous",
    precision: int = 1,
) -> dict[str, float | str | None]:
    """Return delta, deltaPercent, direction, outcome, comparisonLabel.

    Rules from the implementation plan:
    - delta = current - previous
    - delta_percent = ((current - previous) / abs(previous)) * 100
    - arrow direction is mathematical
    - color/outcome is based on polarity
    - zero and missing data are handled explicitly (no Infinity / NaN)
    """
    result: dict[str, float | str | None] = {
        "delta": None,
        "delta_percent": None,
        "direction": None,
        "outcome": None,
        "comparison_label": None,
    }

    if current_value is None:
        return result

    if previous_value is None:
        result["comparison_label"] = "No prior-month comparison"
        result["outcome"] = "neutral"
        return result

    # Both values present (they may be zero)
    delta = current_value - previous_value
    result["delta"] = delta

    if previous_value == 0:
        if current_value == 0:
            result["delta_percent"] = 0.0
            result["direction"] = "flat"
            result["outcome"] = "neutral"
            result["comparison_label"] = f"0.0% vs {previous_label}"
            return result
        # previous 0, current > 0
        result["delta_percent"] = None
        result["direction"] = "up"
        result["outcome"] = "neutral"
        result["comparison_label"] = f"New vs {previous_label}"
        return result

    delta_percent = (delta / abs(previous_value)) * 100
    if math.isfinite(delta_percent):
        result["delta_percent"] = round(delta_percent, precision)
    else:
        result["delta_percent"] = None

    # Direction
    if delta > 0:
        result["direction"] = "up"
    elif delta < 0:
        result["direction"] = "down"
    else:
        result["direction"] = "flat"

    # Outcome based on polarity
    direction = result["direction"]
    if direction == "flat":
        result["outcome"] = "neutral"
    elif direction == "up":
        result["outcome"] = "favorable" if polarity == "higher_is_better" else "unfavorable"
    else:  # down
        result["outcome"] = "favorable" if polarity == "lower_is_better" else "unfavorable"

    arrow = {"up": "↑", "down": "↓", "flat": "→"}[direction]
    pct_text = (
        f"{abs(result['delta_percent']):.{precision}f}%"
        if result["delta_percent"] is not None
        else "New"
    )
    result["comparison_label"] = f"{arrow} {pct_text} vs {previous_label}"
    return result


def outcome_color_class(outcome: str | None) -> str:
    if outcome == "favorable":
        return "text-emerald-600"
    if outcome == "unfavorable":
        return "text-rose-600"
    return "text-slate-500"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
