
from __future__ import annotations

from .materiality_gates import _MATERIALITY_RULES as _MATERIALITY_RULES
from .materiality_gates import _material_anomalies as _material_anomalies
from .materiality_gates import _material_change_point as _material_change_point
from .materiality_gates import _material_contribution as _material_contribution
from .materiality_gates import _material_drivers as _material_drivers
from .materiality_gates import _material_forecast as _material_forecast
from .materiality_gates import _material_group_comparison as _material_group_comparison
from .materiality_gates import _material_period_change as _material_period_change
from .materiality_gates import _material_relationship as _material_relationship
from .materiality_gates import _material_seasonality as _material_seasonality
from .materiality_gates import _material_trend as _material_trend
from .materiality_gates import assess_materiality as assess_materiality
from .planning import MATERIAL_CORRELATION as MATERIAL_CORRELATION
from .planning import MATERIAL_P_VALUE as MATERIAL_P_VALUE
from .planning import MATERIAL_RELATIVE_CHANGE as MATERIAL_RELATIVE_CHANGE
from .planning import MAX_GROUPS as MAX_GROUPS
from .planning import MIN_GROUPS as MIN_GROUPS
from .planning import MIN_MEASURES_FOR_DRIVERS as MIN_MEASURES_FOR_DRIVERS
from .planning import MIN_PERIODS_ANOMALY as MIN_PERIODS_ANOMALY
from .planning import MIN_PERIODS_CHANGE_POINT as MIN_PERIODS_CHANGE_POINT
from .planning import MIN_PERIODS_FORECAST as MIN_PERIODS_FORECAST
from .planning import MIN_PERIODS_SEASONALITY as MIN_PERIODS_SEASONALITY
from .planning import MIN_PERIODS_TREND as MIN_PERIODS_TREND
from .planning import MIN_ROWS_GROUP_COMPARISON as MIN_ROWS_GROUP_COMPARISON
from .planning import MIN_ROWS_RELATIONSHIP as MIN_ROWS_RELATIONSHIP
from .planning import MIN_YEARS_FOR_YOY as MIN_YEARS_FOR_YOY
from .planning import DeepAnalysisSpec as DeepAnalysisSpec
from .planning import Materiality as Materiality
from .planning import _first_list as _first_list
from .planning import _first_num as _first_num
from .planning import _humanize as _humanize
from .planning import _norm_key as _norm_key
from .planning import _num as _num
from .planning import logger as logger
from .planning import plan_deep_analyses as plan_deep_analyses
from .presentation import EVIDENCE_PRESENTATION as EVIDENCE_PRESENTATION
from .presentation import card_summary as card_summary
from .presentation import evidence_presentation as evidence_presentation
from .presentation import spec_presentation as spec_presentation

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
