
from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)

_DEFAULT_MIN_N = 8


def _clean(df: pd.DataFrame, col: str) -> np.ndarray:
    return pd.to_numeric(df[col], errors="coerce").dropna().to_numpy(dtype=float)


def _finite(x: float | None) -> float | None:
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _result(
    status: str,
    *,
    results: dict[str, Any] | None = None,
    assumptions: list[dict[str, Any]] | None = None,
    caveats: list[str] | None = None,
    n: int = 0,
    usable_n: int = 0,
    excluded: int = 0,
    missing: int = 0,
    quality: str = "reliable",
    warnings: list[str] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "results": results or {},
        "assumptions": assumptions or [],
        "caveats": caveats or [],
        "n": n,
        "usable_n": usable_n,
        "excluded": excluded,
        "missing": missing,
        "quality": quality,
        "warnings": warnings or [],
        "reason": reason,
    }


def _assumption(name: str, status: str, severity: str | None = None) -> dict[str, Any]:
    a = {"name": name, "status": status}
    if severity:
        a["severity"] = severity
    return a


# --------------------------------------------------------------------------- #
# Descriptive / distribution
# --------------------------------------------------------------------------- #
def _describe_numeric(df, roles, profile, policies):
    v = _clean(df, roles["value"])
    n = v.size
    if n < 3:
        return _result("insufficient_data", n=n, reason="fewer than 3 values")
    q = np.percentile(v, [25, 50, 75])
    results = {
        "n": int(n),
        "mean": _finite(np.mean(v)),
        "median": _finite(q[1]),
        "std": _finite(np.std(v, ddof=1)) if n > 1 else 0.0,
        "min": _finite(np.min(v)),
        "max": _finite(np.max(v)),
        "quantiles": {"p25": _finite(q[0]), "p50": _finite(q[1]), "p75": _finite(q[2])},
        "skewness": _finite(stats.skew(v)) if n >= _DEFAULT_MIN_N else None,
        "kurtosis": _finite(stats.kurtosis(v)) if n >= _DEFAULT_MIN_N else None,
    }
    return _result("ok", results=results, n=int(n), usable_n=int(n))


def _normality_test(df, roles, profile, policies):
    v = _clean(df, roles["value"])
    n = v.size
    if n < 3:
        return _result("insufficient_data", n=n, reason="fewer than 3 values")
    if n > 5000:
        stat, p = stats.normaltest(v)
        name = "dagostino_pearson"
    else:
        stat, p = stats.shapiro(v)
        name = "shapiro_wilk"
    results = {"statistic": _finite(stat), "pValue": _finite(p),
               "isNormal": bool(p > 0.05), "test": name}
    return _result("ok", results=results, n=int(n), usable_n=int(n))


# --------------------------------------------------------------------------- #
# Correlation
# --------------------------------------------------------------------------- #
def _pair(df, roles):
    sub = df[[roles["x"], roles["y"]]].apply(pd.to_numeric, errors="coerce").dropna()
    return (sub[roles["x"]].to_numpy(float), sub[roles["y"]].to_numpy(float), len(sub))
