"""Stage A — Data Profiler.

Measures the *condition* of a result set so the selector can choose a method
from the data profile, not intent alone. Profiles are cached by result-set hash
so the Method Engine and (future) Visualization Engine share one computation.
"""

from __future__ import annotations

import hashlib
import json
import warnings
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

# Cache profiles by result-set hash.
_profile_cache: dict[str, dict[str, Any]] = {}

_MIN_SHAPE_N = 8
_MIN_NORMALITY_N = 3
_MAX_NORMALITY_N = 5000

_PERIOD_HINTS = ("date", "day", "week", "month", "quarter", "year", "period", "time")


def result_set_hash(columns: list[str], rows: list[list[Any]]) -> str:
    payload = json.dumps({"c": columns, "r": rows[:200]}, default=str, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def to_dataframe(columns: list[str], rows: list[Any]) -> pd.DataFrame:
    """Build a DataFrame from ask-and-run's columns + rows (list or dict rows)."""
    if rows and isinstance(rows[0], dict):
        return pd.DataFrame(rows, columns=columns)
    return pd.DataFrame(rows, columns=columns)


def _column_kind(series: pd.Series) -> str:
    non_null = series.dropna()
    if non_null.empty:
        return "empty"
    numeric = pd.to_numeric(non_null, errors="coerce")
    if numeric.notna().mean() >= 0.9:
        uniq = numeric.dropna().nunique()
        if uniq <= 2:
            return "binary"
        return "numeric"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed = pd.to_datetime(non_null, errors="coerce")
    if parsed.notna().mean() >= 0.8:
        return "datetime"
    if non_null.nunique() <= max(2, int(0.5 * len(non_null))):
        return "categorical"
    return "text"


def _numeric_profile(series: pd.Series) -> dict[str, Any]:
    values = pd.to_numeric(series, errors="coerce").dropna().to_numpy(dtype=float)
    n = int(values.size)
    prof: dict[str, Any] = {"n": n}
    if n == 0:
        return prof
    q1, q3 = np.percentile(values, [25, 75])
    iqr = float(q3 - q1)
    prof["mean"] = float(np.mean(values))
    prof["std"] = float(np.std(values, ddof=1)) if n > 1 else 0.0
    prof["min"] = float(np.min(values))
    prof["max"] = float(np.max(values))
    prof["iqr"] = iqr

    if n >= _MIN_SHAPE_N and prof["std"] > 0:
        prof["skewness"] = float(stats.skew(values))
        prof["kurtosis"] = float(stats.kurtosis(values))
    # Outliers: IQR fences + |z| > 3
    if iqr > 0:
        low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        iqr_out = int(np.sum((values < low) | (values > high)))
    else:
        iqr_out = 0
    if prof["std"] > 0:
        z = np.abs((values - prof["mean"]) / prof["std"])
        z_out = int(np.sum(z > 3))
    else:
        z_out = 0
    prof["outlier_count"] = max(iqr_out, z_out)
    prof["outlier_rate"] = round(prof["outlier_count"] / n, 4) if n else 0.0

    # Normality
    if _MIN_NORMALITY_N <= n <= _MAX_NORMALITY_N and prof["std"] > 0:
        try:
            _, p = stats.shapiro(values)
            prof["normality_p"] = float(p)
            prof["is_normal"] = bool(p > 0.05)
        except Exception:
            prof["is_normal"] = None
    else:
        prof["is_normal"] = None
    return prof


def profile_dataframe(df: pd.DataFrame) -> dict[str, Any]:
    row_count = int(len(df))
    columns: dict[str, Any] = {}
    numeric_cols: list[str] = []
    datetime_cols: list[str] = []
    categorical_cols: list[str] = []
    binary_cols: list[str] = []

    for col in df.columns:
        series = df[col]
        kind = _column_kind(series)
        null_rate = float(series.isna().mean()) if row_count else 0.0
        info: dict[str, Any] = {
            "kind": kind,
            "null_rate": round(null_rate, 4),
            "cardinality": int(series.nunique(dropna=True)),
        }
        if kind in ("numeric", "binary"):
            info.update(_numeric_profile(series))
            numeric_cols.append(col)
            if kind == "binary":
                binary_cols.append(col)
        elif kind == "datetime":
            datetime_cols.append(col)
        elif kind == "categorical":
            categorical_cols.append(col)
        columns[col] = info

    # Pairwise collinearity across numeric columns (max |r|).
    collinearity_max = None
    if len(numeric_cols) >= 2:
        num_df = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
        corr = num_df.corr(method="pearson").abs()
        np.fill_diagonal(corr.values, np.nan)
        if not np.all(np.isnan(corr.values)):
            collinearity_max = float(np.nanmax(corr.values))

    has_time = bool(datetime_cols) or any(
        any(h in str(c).lower() for h in _PERIOD_HINTS) for c in df.columns
    )

    return {
        "row_count": row_count,
        "columns": columns,
        "numeric_columns": numeric_cols,
        "datetime_columns": datetime_cols,
        "categorical_columns": categorical_cols,
        "binary_columns": binary_cols,
        "collinearity_max": collinearity_max,
        "has_time_structure": has_time,
    }


def profile(columns: list[str], rows: list[Any]) -> dict[str, Any]:
    key = result_set_hash(columns, rows if isinstance(rows, list) else [])
    if key in _profile_cache:
        return _profile_cache[key]
    df = to_dataframe(columns, rows)
    result = profile_dataframe(df)
    result["hash"] = key
    _profile_cache[key] = result
    return result
