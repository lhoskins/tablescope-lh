"""Minimal deterministic analysis-intent inference.

A lightweight, keyword+profile heuristic — NOT the LLM. This is intentionally
conservative: it returns a single analysisIntent the selector understands, or
``None`` when nothing statistical is clearly requested (the engine then no-ops).
The full Intent Engine is a later milestone; this keeps M1 self-contained.
"""

from __future__ import annotations

import re
from typing import Any

_KEYWORDS: list[tuple[str, str]] = [
    # Set B time-series / change intents (specific phrases first so "MoM growth"
    # routes to period comparison rather than generic "growth" -> detect_trend).
    (r"\b(month over month|mom|quarter over quarter|qoq|year over year|yoy|period over period|vs prior|vs previous|baseline|rate of change|from prior period|prior period)\b", "compare_periods"),
    (r"\b(forecast|project|predict future|what should we expect|forward looking|outlook|next quarter|next month|next year|upcoming)\b", "forecast_time_series"),
    (r"\b(change point|when did it change|structural break|break point|shift in|turning point|inflection)\b", "detect_change_point"),
    (r"\b(anomal|outlier|unusual|unexpected|spike|dip)\b", "detect_anomalies"),
    (r"\b(contribution to change|what drove the change|why did it change|breakdown of change|drivers? of the change|drove the change)\b", "contribution_to_change"),
    # Relationship / association.
    (r"\b(correlat|relationship|associat|related to|vs\.?|versus|driver)\b", "relationship_numeric"),
    # Group comparisons.
    (r"\b(compare|difference between|differ|higher than|lower than|vs group)\b", "compare_two_groups"),
    (r"\b(across|among|between groups|by (category|segment|region|type))\b", "compare_multiple_groups"),
    (r"\b(rate|proportion|share).*(differ|compare|between)\b", "compare_category_rates"),
    # Trend and distribution.
    (r"\b(trend|over time|increasing|decreasing|growth|declin)\b", "detect_trend"),
    (r"\b(seasonal|seasonality|cycle)\b", "trend_seasonality"),
    # Prediction, normality, description.
    (r"\b(predict|drivers of|explain|what affects|impact of|factors)\b", "continuous_prediction"),
    (r"\b(normal|distribution|distributed)\b", "normality"),
    (r"\b(describe|summary|summarize|statistics of|average|mean|median)\b", "describe_numeric"),
]


def infer_intent(question: str, profile: dict[str, Any]) -> str | None:
    q = (question or "").lower()
    numeric = profile.get("numeric_columns", [])
    plain_numeric = [c for c in numeric if c not in profile.get("binary_columns", [])]
    categorical = profile.get("categorical_columns", [])
    has_time = profile.get("has_time_structure")

    for pattern, intent in _KEYWORDS:
        if re.search(pattern, q):
            # Reconcile keyword with data shape where it obviously conflicts.
            if intent == "relationship_numeric" and len(plain_numeric) < 2:
                continue
            if intent in ("detect_trend", "trend_seasonality") and not has_time:
                continue
            if intent == "compare_multiple_groups" and not categorical:
                intent = "compare_two_groups"
            if intent == "compare_two_groups" and not (categorical or profile.get("binary_columns")):
                continue
            return intent

    # Fall back to shape-driven defaults.
    if has_time and plain_numeric:
        return "detect_trend"
    if len(plain_numeric) >= 2:
        return "relationship_numeric"
    if plain_numeric and categorical:
        return "compare_multiple_groups"
    if plain_numeric:
        return "describe_numeric"
    return None
