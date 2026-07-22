"""Resolve which result-set columns play which role for a given analysis intent.

Kept separate so the selector (feasibility) and executor (execution) agree on the
same column assignment. Returns ``None`` when the data shape cannot satisfy the
intent (the selector then reports insufficient structure).
"""

from __future__ import annotations

from typing import Any


def _groups(profile: dict[str, Any], col: str) -> int:
    return int(profile["columns"].get(col, {}).get("cardinality", 0))


def resolve_roles(intent: str, profile: dict[str, Any]) -> dict[str, Any] | None:
    numeric = list(profile.get("numeric_columns", []))
    categorical = list(profile.get("categorical_columns", []))
    binary = list(profile.get("binary_columns", []))
    datetime = list(profile.get("datetime_columns", []))
    # binary columns are a subset of numeric; treat as candidate group columns too
    group_candidates = [c for c in categorical] + [c for c in binary]

    if intent in ("describe_numeric", "normality", "r_descriptive_profile"):
        if numeric:
            return {"value": numeric[0]}
        return None

    if intent in ("relationship_numeric", "relationship_monotonic"):
        plain_numeric = [c for c in numeric if c not in binary]
        if len(plain_numeric) >= 2:
            return {"x": plain_numeric[0], "y": plain_numeric[1]}
        if len(numeric) >= 2:
            return {"x": numeric[0], "y": numeric[1]}
        return None

    if intent == "compare_two_groups":
        value = next((c for c in numeric if c not in binary), None)
        group = next((c for c in group_candidates if 2 <= _groups(profile, c) <= 2), None)
        if group is None:
            group = next((c for c in group_candidates if _groups(profile, c) == 2), None)
        if value and group:
            return {"value": value, "group": group}
        return None

    if intent == "compare_multiple_groups":
        value = next((c for c in numeric if c not in binary), None)
        group = next((c for c in categorical if _groups(profile, c) >= 3), None)
        if value and group:
            return {"value": value, "group": group}
        return None

    if intent == "compare_paired":
        plain_numeric = [c for c in numeric if c not in binary]
        if len(plain_numeric) >= 2:
            return {"a": plain_numeric[0], "b": plain_numeric[1]}
        return None

    if intent == "compare_category_rates":
        cats = categorical + binary
        if len(cats) >= 2:
            return {"a": cats[0], "b": cats[1]}
        return None

    if intent == "compare_to_target":
        if numeric:
            return {"value": next((c for c in numeric if c not in binary), numeric[0])}
        return None

    if intent == "binary_outcome":
        if binary and len(numeric) >= 2:
            target = binary[0]
            predictors = [c for c in numeric if c != target][:5]
            if predictors:
                return {"target": target, "predictors": predictors}
        return None

    if intent in ("count_outcome", "zero_heavy_count"):
        plain_numeric = [c for c in numeric if c not in binary]
        if len(plain_numeric) >= 2:
            return {"target": plain_numeric[0], "predictors": plain_numeric[1:6]}
        return None

    if intent in ("continuous_prediction", "explain_change"):
        plain_numeric = [c for c in numeric if c not in binary]
        if len(plain_numeric) >= 2:
            return {"target": plain_numeric[0], "predictors": plain_numeric[1:6]}
        return None

    if intent in ("detect_trend", "trend_seasonality"):
        time_col = datetime[0] if datetime else None
        value = next((c for c in numeric if c not in binary), None)
        if value:
            return {"time": time_col, "value": value}
        return None

    if intent in ("compare_periods", "compare_year_over_year", "compare_to_baseline", "measure_rate_of_change", "detect_change_point", "detect_anomalies", "forecast_time_series"):
        time_col = datetime[0] if datetime else None
        value = next((c for c in numeric if c not in binary), None)
        if value:
            return {"time": time_col, "value": value}
        return None

    if intent == "contribution_to_change":
        value = next((c for c in numeric if c not in binary), None)
        group = categorical[0] if categorical else None
        time_col = datetime[0] if datetime else None
        if value and group:
            return {"value": value, "group": group, "time": time_col}
        return None

    return None
