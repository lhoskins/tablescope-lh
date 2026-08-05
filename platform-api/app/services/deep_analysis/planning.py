
from __future__ import annotations

import logging
import re
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


def _norm_key(key: Any) -> str:
    """Flatten a result key for matching: lower-case and drop punctuation."""
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _first_num(results: dict[str, Any], *keys: str) -> float | None:
    """First numeric value found under any of ``keys`` (case-insensitive)."""
    if not isinstance(results, dict):
        return None
    norm = {_norm_key(k): v for k, v in results.items()}
    for key in keys:
        if (v := _num(norm.get(_norm_key(key)))) is not None:
            return v
    return None


def _first_list(results: dict[str, Any], *keys: str) -> list[Any]:
    if not isinstance(results, dict):
        return []
    norm = {_norm_key(k): v for k, v in results.items()}
    for key in keys:
        v = norm.get(_norm_key(key))
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
