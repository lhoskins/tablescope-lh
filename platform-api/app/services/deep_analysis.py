"""Method-driven Deeper analysis.

The Deeper-analysis section used to be a *shape prober*: it read 50 rows from a
table, looked for any column combination that could be drawn, and emitted a
chart. Nothing in that path ran a statistical method, which is why the cards
never felt deeper than the main feed (and why they happily charted record keys).

This module decides Deeper analysis the other way round: it asks which **governed
analytical intents** a table's business columns can support, runs those methods
through the existing Analytical Method Engine, and keeps only results that clear
a **materiality gate**. A statistically empty result produces no card at all.

Everything here is pure and dependency-light so it can be unit-tested without a
database, an LLM, or the R service: :func:`plan_deep_analyses` decides *what to
ask*, :func:`assess_materiality` decides *whether the answer is worth showing*,
and :func:`evidence_presentation` decides *how to show it*. The async
orchestration (running SQL, calling the engine) stays in ``home_intelligence``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Minimum evidence each intent needs before it is worth asking ─────────────
#: Periods required before a time-series method has anything to say. Fitting a
#: forecast or a seasonal decomposition to a handful of points produces
#: confident-looking nonsense, so the gate is applied before execution.
MIN_PERIODS_TREND = 6
MIN_PERIODS_CHANGE_POINT = 12
MIN_PERIODS_ANOMALY = 12
MIN_PERIODS_FORECAST = 12
MIN_PERIODS_SEASONALITY = 24
#: Raw observations required for distribution/relationship methods.
MIN_ROWS_RELATIONSHIP = 20
MIN_ROWS_GROUP_COMPARISON = 20
#: Distinct groups required to compare groups at all.
MIN_GROUPS = 3
MAX_GROUPS = 12

#: Distinct calendar years needed before a year-over-year comparison is honest.
MIN_YEARS_FOR_YOY = 2
#: Measures needed before a driver/decomposition regression is worth running.
MIN_MEASURES_FOR_DRIVERS = 3

#: A period-over-period move smaller than this is noise, not an insight.
MATERIAL_RELATIVE_CHANGE = 0.05
#: Correlations weaker than this are not worth a card even when significant —
#: with enough rows, trivial associations reach significance.
MATERIAL_CORRELATION = 0.30
#: Conventional significance level for the gate.
MATERIAL_P_VALUE = 0.05


@dataclass(frozen=True)
class DeepAnalysisSpec:
    """One governed analysis to run against a table.

    ``intent`` is resolved by the method engine against the governed catalog —
    this module never names a method, only the business question.
    """

    intent: str
    title: str
    question: str
    #: Column roles the SQL projects: e.g. {"period": "month", "measure": "revenue"}.
    roles: dict[str, str]
    #: Presentation family for the method's evidence (see EVIDENCE_PRESENTATION).
    priority: float = 0.5
    group_by: str | None = None
    #: Overrides the intent's default presentation. Two analyses can share an
    #: intent but need different charts — a correlation on raw rows is a
    #: scatter, the same correlation across a shared timeline is a dual-axis
    #: combo showing both metrics moving together.
    presentation: str | None = None


@dataclass
class Materiality:
    """Whether a method's result is worth showing, and why."""

    material: bool
    reason: str
    #: Headline figure for the card summary when the method exposes one.
    highlight: str = ""
    facts: dict[str, Any] = field(default_factory=dict)


def _num(value: Any) -> float | None:
    """Coerce a possibly-stringy numeric to float, or None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        s = value.strip().replace("%", "").replace(",", "")
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _first_num(results: dict[str, Any], *keys: str) -> float | None:
    """First numeric value found under any of ``keys`` (case-insensitive)."""
    if not isinstance(results, dict):
        return None
    lowered = {str(k).lower(): v for k, v in results.items()}
    for key in keys:
        if (v := _num(lowered.get(key.lower()))) is not None:
            return v
    return None


def _first_list(results: dict[str, Any], *keys: str) -> list[Any]:
    if not isinstance(results, dict):
        return []
    lowered = {str(k).lower(): v for k, v in results.items()}
    for key in keys:
        v = lowered.get(key.lower())
        if isinstance(v, list):
            return v
    return []


# ── What to ask ──────────────────────────────────────────────────────────────


def plan_deep_analyses(
    *,
    table_title: str,
    period_column: str | None,
    measures: list[str],
    dimensions: list[str],
    row_count: int,
    period_count: int,
    distinct_years: int = 0,
    target_column: str | None = None,
    max_per_table: int = 3,
) -> list[DeepAnalysisSpec]:
    """Decide which governed analyses a table's shape can genuinely support.

    ``dimensions`` must already exclude identifier and period columns (see
    ``visualization_engine.business_dimensions``) — a Deeper analysis grouped by
    a record key is exactly the failure this section had before.

    Returns specs ordered by business value, capped at ``max_per_table``.
    """
    if not measures:
        return []

    measure = measures[0]
    specs: list[DeepAnalysisSpec] = []
    metric = _humanize(measure)

    if period_column and period_count >= MIN_PERIODS_TREND:
        specs.append(
            DeepAnalysisSpec(
                intent="compare_periods",
                title=f"{metric}: period-over-period change",
                question=f"How did {metric} change versus the prior period?",
                roles={"period": period_column, "measure": measure},
                priority=0.95,
            )
        )
    # Year over year — the comparison every executive asks for first. Needs two
    # distinct calendar years, not merely 24 rows: 24 months inside one year
    # cannot support a YoY read.
    if period_column and distinct_years >= MIN_YEARS_FOR_YOY:
        specs.append(
            DeepAnalysisSpec(
                intent="compare_year_over_year",
                title=f"{metric}: year over year",
                question=f"How does {metric} compare with the same period last year?",
                roles={"period": period_column, "measure": measure},
                priority=0.97,
                presentation="combo",
            )
        )
    # Growth rate / momentum.
    if period_column and period_count >= MIN_PERIODS_TREND:
        specs.append(
            DeepAnalysisSpec(
                intent="measure_rate_of_change",
                title=f"{metric}: rate of change",
                question=f"How fast is {metric} growing or declining?",
                roles={"period": period_column, "measure": measure},
                priority=0.86,
            )
        )
    # Actual vs plan/target/budget — only when the table carries a baseline.
    if period_column and target_column:
        specs.append(
            DeepAnalysisSpec(
                intent="compare_to_baseline",
                title=f"{metric} vs {_humanize(target_column)}",
                question=f"Is {metric} tracking against {_humanize(target_column)}?",
                roles={
                    "period": period_column,
                    "measure": measure,
                    "measure2": target_column,
                },
                priority=0.93,
                presentation="combo",
            )
        )
    # Two KPIs moving along a shared timeline — the co-movement read (revenue
    # against margin, volume against scrap). Same correlation intent as the raw
    # scatter, but aggregated per period and drawn as a dual-axis combo.
    if period_column and len(measures) >= 2 and period_count >= MIN_PERIODS_TREND:
        other = measures[1]
        specs.append(
            DeepAnalysisSpec(
                intent="relationship_numeric",
                title=f"{metric} and {_humanize(other)} over time",
                question=(
                    f"Do {metric} and {_humanize(other)} move together over time?"
                ),
                roles={
                    "period": period_column,
                    "measure": measure,
                    "measure2": other,
                },
                priority=0.91,
                presentation="combo",
            )
        )
    # Is the movement real, or noise?
    if period_column and period_count >= MIN_PERIODS_TREND:
        specs.append(
            DeepAnalysisSpec(
                intent="detect_trend",
                title=f"{metric}: underlying trend",
                question=f"Is the movement in {metric} a real trend or noise?",
                roles={"period": period_column, "measure": measure},
                priority=0.83,
            )
        )
    # Which factors explain the KPI (executive driver analysis).
    if len(measures) >= MIN_MEASURES_FOR_DRIVERS and row_count >= MIN_ROWS_RELATIONSHIP:
        specs.append(
            DeepAnalysisSpec(
                intent="continuous_prediction",
                title=f"What explains {metric}",
                question=f"Which measures explain movement in {metric}?",
                roles={"measure": measure},
                priority=0.78,
            )
        )
    if period_column and period_count >= MIN_PERIODS_ANOMALY:
        specs.append(
            DeepAnalysisSpec(
                intent="detect_anomalies",
                title=f"Unusual {metric} observations",
                question=f"Are there unusual {metric} values against the expected range?",
                roles={"period": period_column, "measure": measure},
                priority=0.9,
            )
        )
    if period_column and period_count >= MIN_PERIODS_CHANGE_POINT:
        specs.append(
            DeepAnalysisSpec(
                intent="detect_change_point",
                title=f"When {metric} shifted",
                question=f"Did {metric} shift to a new level, and when?",
                roles={"period": period_column, "measure": measure},
                priority=0.85,
            )
        )
    if period_column and period_count >= MIN_PERIODS_FORECAST:
        specs.append(
            DeepAnalysisSpec(
                intent="forecast_time_series",
                title=f"{metric} outlook",
                question=f"What should we expect for {metric} next?",
                roles={"period": period_column, "measure": measure},
                priority=0.8,
            )
        )
    if period_column and dimensions and period_count >= MIN_PERIODS_TREND:
        specs.append(
            DeepAnalysisSpec(
                intent="contribution_to_change",
                title=f"What drove the change in {metric}",
                question=f"Which {_humanize(dimensions[0])} groups explain the movement in {metric}?",
                roles={"period": period_column, "measure": measure},
                group_by=dimensions[0],
                priority=0.88,
            )
        )
    if period_column and period_count >= MIN_PERIODS_SEASONALITY:
        specs.append(
            DeepAnalysisSpec(
                intent="trend_seasonality",
                title=f"{metric}: trend and seasonality",
                question=f"How much of {metric} is trend versus seasonal pattern?",
                roles={"period": period_column, "measure": measure},
                priority=0.7,
            )
        )
    if len(measures) >= 2 and row_count >= MIN_ROWS_RELATIONSHIP:
        other = measures[1]
        specs.append(
            DeepAnalysisSpec(
                intent="relationship_numeric",
                title=f"{metric} vs {_humanize(other)}",
                question=f"Is {metric} related to {_humanize(other)}?",
                roles={"measure": measure, "measure2": other},
                priority=0.75,
            )
        )
    if dimensions and row_count >= MIN_ROWS_GROUP_COMPARISON:
        specs.append(
            DeepAnalysisSpec(
                intent="compare_multiple_groups",
                title=f"{metric} by {_humanize(dimensions[0])}",
                question=f"Does {metric} differ by {_humanize(dimensions[0])}?",
                roles={"measure": measure},
                group_by=dimensions[0],
                priority=0.72,
            )
        )

    specs.sort(key=lambda s: s.priority, reverse=True)
    return specs[:max_per_table]


def _humanize(column: str) -> str:
    """``total_revenue_usd`` -> ``Total Revenue USD`` (best effort)."""
    cleaned = column.replace("_", " ").replace("-", " ").strip()
    if not cleaned:
        return column
    words = [w.upper() if len(w) <= 3 and w.isalpha() and w.isupper() else w for w in cleaned.split()]
    return " ".join(w if w.isupper() else w.capitalize() for w in words)


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
    r = _first_num(results, "correlation", "estimate", "r", "rho", "tau")
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


# ── How to show it ───────────────────────────────────────────────────────────

#: Chart family + analytical layers that render each intent's evidence. These
#: families are registered in the ECharts renderer and declared in
#: ``chart_selection_best_practices.md``.
EVIDENCE_PRESENTATION: dict[str, dict[str, Any]] = {
    "compare_periods": {"chart": "combo", "layers": ["reference_line"]},
    "compare_to_baseline": {"chart": "combo", "layers": ["reference_line"]},
    "continuous_prediction": {"chart": "bar", "layers": []},
    "compare_year_over_year": {"chart": "combo", "layers": ["reference_line"]},
    "measure_rate_of_change": {"chart": "line", "layers": ["reference_line"]},
    "detect_trend": {"chart": "line", "layers": ["regression_line"]},
    "trend_seasonality": {"chart": "line", "layers": []},
    "detect_anomalies": {"chart": "line", "layers": ["confidence_band", "anomaly_marker"]},
    "detect_change_point": {"chart": "line", "layers": ["change_point"]},
    "forecast_time_series": {"chart": "line", "layers": ["prediction_band"]},
    "contribution_to_change": {"chart": "bar", "layers": []},
    "relationship_numeric": {"chart": "scatter", "layers": ["regression_line"]},
    "relationship_monotonic": {"chart": "scatter", "layers": ["regression_line"]},
    "compare_multiple_groups": {"chart": "boxplot", "layers": []},
    "compare_two_groups": {"chart": "boxplot", "layers": []},
}


def spec_presentation(spec: DeepAnalysisSpec) -> dict[str, Any]:
    """Presentation for a planned analysis, honouring an explicit override."""
    base = evidence_presentation(spec.intent)
    if spec.presentation:
        return {"chart": spec.presentation, "layers": base.get("layers", [])}
    return base


def evidence_presentation(intent: str) -> dict[str, Any]:
    """Chart family + analytical layers for an intent's evidence.

    Falls back to a table so an uncatalogued intent degrades honestly rather
    than being force-fitted into a chart that misrepresents it.
    """
    return EVIDENCE_PRESENTATION.get(intent, {"chart": "table", "layers": []})


def card_summary(spec: DeepAnalysisSpec, materiality: Materiality, envelope: dict[str, Any]) -> str:
    """Business-language summary: the finding first, the method as provenance."""
    parts = [materiality.reason]
    n = envelope.get("usableN") or envelope.get("n")
    if n:
        parts.append(f"Based on {n} observations.")
    engine = str(envelope.get("executionEngine") or "").lower()
    method = envelope.get("method")
    if method:
        label = f"Method: {method}"
        if engine == "r":
            label += " (R)"
        parts.append(label + ".")
    return " ".join(p for p in parts if p)
