
from __future__ import annotations

from typing import Any

from .planning import (
    MATERIAL_CORRELATION,
    MATERIAL_P_VALUE,
    MATERIAL_RELATIVE_CHANGE,
    Materiality,
    _first_list,
    _first_num,
    logger,
)

# ── Whether the answer is worth showing ──────────────────────────────────────


def assess_materiality(intent: str, envelope: dict[str, Any]) -> Materiality:
    """Decide whether a method's result deserves a card.

    This is what separates "deeper analysis" from filler: a method that ran
    cleanly but found nothing (no anomalies, a flat trend, a trivial
    correlation) must produce **no card**. Unknown intents default to material
    so a newly-catalogued method is not silently suppressed.
    """
    if not isinstance(envelope, dict):
        return Materiality(False, "No analytical envelope.")
    status = str(envelope.get("status") or envelope.get("reason") or "").lower()
    results = envelope.get("results") or {}
    if not isinstance(results, dict):
        results = {}

    if envelope.get("method") is None:
        return Materiality(False, "No governed method matched this shape.")
    if status in {"insufficient_data", "invalid_input", "error", "timeout", "no_method"}:
        return Materiality(False, f"Method did not produce a usable result ({status}).")
    if str(envelope.get("quality") or "").lower() == "unreliable":
        return Materiality(False, "Result quality is unreliable.")

    handler = _MATERIALITY_RULES.get(intent)
    if handler is None:
        return Materiality(True, "Method produced a result.")
    try:
        return handler(results, envelope)
    except Exception:  # pragma: no cover - a gate must never break generation
        logger.exception("materiality gate failed for intent %s", intent)
        return Materiality(True, "Method produced a result.")


def _material_period_change(results: dict[str, Any], _env: dict[str, Any]) -> Materiality:
    # Methods report the move either as a fraction (0.08) or as a percentage
    # (8.0). Read the explicit percentage keys first so the two are never
    # confused; only fall back to a magnitude heuristic for a fraction key
    # carrying an implausible value (a "fraction" of 18 is 18%, not 1800%).
    pct = _first_num(results, "percent_change", "pct_change", "percentage_change")
    frac = _first_num(results, "relative_change", "relativeChange", "rate_of_change")
    if pct is not None:
        fraction = pct / 100
    elif frac is not None:
        fraction = frac / 100 if abs(frac) > 1.5 else frac
    else:
        abs_change = _first_num(results, "absolute_change", "change", "delta")
        if abs_change is None:
            return Materiality(False, "No period comparison was produced.")
        return Materiality(True, "Period change computed.", highlight=f"{abs_change:+,.1f}")
    if abs(fraction) < MATERIAL_RELATIVE_CHANGE:
        return Materiality(
            False,
            f"Period-over-period move of {fraction:+.1%} is within normal variation.",
        )
    return Materiality(
        True,
        f"Period-over-period move of {fraction:+.1%}.",
        highlight=f"{fraction:+.1%}",
        facts={"relative_change": fraction},
    )


def _material_anomalies(results: dict[str, Any], _env: dict[str, Any]) -> Materiality:
    flagged = _first_list(results, "anomalies", "flagged", "outliers", "points")
    count = len(flagged) if flagged else int(_first_num(results, "anomaly_count", "n_anomalies") or 0)
    if count <= 0:
        return Materiality(False, "No observations fell outside the expected range.")
    return Materiality(
        True,
        f"{count} observation(s) outside the expected range.",
        highlight=f"{count} anomal{'y' if count == 1 else 'ies'}",
        facts={"anomaly_count": count},
    )


def _material_change_point(results: dict[str, Any], _env: dict[str, Any]) -> Materiality:
    points = _first_list(results, "change_points", "changepoints", "breaks")
    count = len(points) if points else int(_first_num(results, "change_point_count") or 0)
    if count <= 0:
        return Materiality(False, "No level shift was detected.")
    return Materiality(
        True,
        f"{count} level shift(s) detected.",
        highlight=f"{count} shift{'' if count == 1 else 's'}",
        facts={"change_point_count": count},
    )


def _material_trend(results: dict[str, Any], _env: dict[str, Any]) -> Materiality:
    p = _first_num(results, "p_value", "pvalue", "p")
    slope = _first_num(results, "slope", "sens_slope", "estimate")
    if p is not None and p > MATERIAL_P_VALUE:
        return Materiality(False, f"Trend is not statistically significant (p={p:.3f}).")
    if slope is not None and slope == 0:
        return Materiality(False, "Trend slope is flat.")
    return Materiality(
        True,
        "A statistically significant trend is present.",
        highlight=f"slope {slope:+,.3f}" if slope is not None else "",
        facts={"p_value": p, "slope": slope},
    )


def _material_relationship(results: dict[str, Any], _env: dict[str, Any]) -> Materiality:
    r = _first_num(results, "effect", "correlation", "estimate", "r", "rho", "tau")
    p = _first_num(results, "p_value", "pvalue", "p")
    if r is None:
        return Materiality(False, "No association estimate was produced.")
    if p is not None and p > MATERIAL_P_VALUE:
        return Materiality(False, f"Association is not statistically significant (p={p:.3f}).")
    if abs(r) < MATERIAL_CORRELATION:
        return Materiality(False, f"Association is too weak to act on (r={r:.2f}).")
    return Materiality(
        True,
        f"Association of r={r:.2f}.",
        highlight=f"r={r:.2f}",
        facts={"correlation": r, "p_value": p},
    )


def _material_group_comparison(results: dict[str, Any], _env: dict[str, Any]) -> Materiality:
    p = _first_num(results, "p_value", "pvalue", "p")
    effect = _first_num(results, "effect_size", "eta_squared", "epsilon_squared", "cohens_d")
    if p is None:
        return Materiality(False, "No group comparison statistic was produced.")
    if p > MATERIAL_P_VALUE:
        return Materiality(False, f"Groups do not differ significantly (p={p:.3f}).")
    return Materiality(
        True,
        f"Groups differ significantly (p={p:.3f}).",
        highlight=f"p={p:.3f}",
        facts={"p_value": p, "effect_size": effect},
    )


def _material_contribution(results: dict[str, Any], _env: dict[str, Any]) -> Materiality:
    contributions = _first_list(results, "contributions", "groups", "drivers")
    if not contributions:
        return Materiality(False, "No group contributions were produced.")
    return Materiality(
        True,
        f"{len(contributions)} group(s) explain the movement.",
        highlight=f"{len(contributions)} drivers",
        facts={"driver_count": len(contributions)},
    )


def _material_forecast(results: dict[str, Any], _env: dict[str, Any]) -> Materiality:
    points = _first_list(results, "forecast", "predictions", "mean")
    if not points:
        return Materiality(False, "No forecast points were produced.")
    return Materiality(
        True,
        f"{len(points)} period(s) forecast with prediction intervals.",
        highlight=f"{len(points)}-period outlook",
        facts={"horizon": len(points)},
    )


def _material_seasonality(results: dict[str, Any], _env: dict[str, Any]) -> Materiality:
    strength = _first_num(results, "seasonal_strength", "seasonality_strength", "seasonal")
    if strength is not None and strength < 0.3:
        return Materiality(False, f"Seasonal signal is weak ({strength:.2f}).")
    return Materiality(
        True,
        "A seasonal pattern is present.",
        highlight=f"seasonality {strength:.2f}" if strength is not None else "",
        facts={"seasonal_strength": strength},
    )


def _material_drivers(results: dict[str, Any], _env: dict[str, Any]) -> Materiality:
    """A driver regression only earns a card when it explains something."""
    r2 = _first_num(results, "r_squared", "r2", "adj_r_squared", "adjusted_r_squared")
    p = _first_num(results, "p_value", "pvalue", "model_p_value")
    if p is not None and p > MATERIAL_P_VALUE:
        return Materiality(False, f"Model is not statistically significant (p={p:.3f}).")
    if r2 is not None and r2 < 0.2:
        return Materiality(
            False, f"Measures explain too little of the variation (R²={r2:.2f})."
        )
    return Materiality(
        True,
        f"Measures explain R²={r2:.2f} of the variation." if r2 is not None
        else "A significant explanatory model was found.",
        highlight=f"R²={r2:.2f}" if r2 is not None else "",
        facts={"r_squared": r2, "p_value": p},
    )


_MATERIALITY_RULES = {
    "compare_periods": _material_period_change,
    "compare_to_baseline": _material_period_change,
    "continuous_prediction": _material_drivers,
    "compare_year_over_year": _material_period_change,
    "measure_rate_of_change": _material_period_change,
    "detect_anomalies": _material_anomalies,
    "detect_change_point": _material_change_point,
    "detect_trend": _material_trend,
    "relationship_numeric": _material_relationship,
    "relationship_monotonic": _material_relationship,
    "compare_multiple_groups": _material_group_comparison,
    "compare_two_groups": _material_group_comparison,
    "contribution_to_change": _material_contribution,
    "forecast_time_series": _material_forecast,
    "trend_seasonality": _material_seasonality,
}
