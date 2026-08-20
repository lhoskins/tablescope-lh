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
    if current_value is None:
        return {
            "delta": None,
            "delta_percent": None,
            "direction": None,
            "outcome": None,
            "comparison_label": None,
        }

    if previous_value is None:
        return {
            "delta": None,
            "delta_percent": None,
            "direction": None,
            "outcome": "neutral",
            "comparison_label": "No prior-month comparison",
        }

    # Both values present (they may be zero)
    delta = current_value - previous_value

    if previous_value == 0:
        if current_value == 0:
            return {
                "delta": delta,
                "delta_percent": 0.0,
                "direction": "flat",
                "outcome": "neutral",
                "comparison_label": f"0.0% vs {previous_label}",
            }
        # previous 0, current > 0
        return {
            "delta": delta,
            "delta_percent": None,
            "direction": "up",
            "outcome": "neutral",
            "comparison_label": f"New vs {previous_label}",
        }

    raw_delta_percent: float = (delta / abs(previous_value)) * 100
    if math.isfinite(raw_delta_percent):
        delta_percent: float | None = round(raw_delta_percent, precision)
    else:
        delta_percent = None

    # Direction
    if delta > 0:
        direction = "up"
    elif delta < 0:
        direction = "down"
    else:
        direction = "flat"

    # Outcome based on polarity
    if direction == "flat":
        outcome = "neutral"
    elif direction == "up":
        outcome = "favorable" if polarity == "higher_is_better" else "unfavorable"
    else:  # down
        outcome = "favorable" if polarity == "lower_is_better" else "unfavorable"

    arrow = {"up": "↑", "down": "↓", "flat": "→"}[direction]
    if delta_percent is not None:
        pct_text = f"{abs(delta_percent):.{precision}f}%"
    else:
        pct_text = "New"
    comparison_label = f"{arrow} {pct_text} vs {previous_label}"

    return {
        "delta": delta,
        "delta_percent": delta_percent,
        "direction": direction,
        "outcome": outcome,
        "comparison_label": comparison_label,
    }


def outcome_color_class(outcome: str | None) -> str:
    if outcome == "favorable":
        return "text-emerald-600"
    if outcome == "unfavorable":
        return "text-rose-600"
    return "text-slate-500"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
