
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from .descriptive import _DEFAULT_MIN_N, _clean, _finite, _result


def _one_sample_t_test(df, roles, profile, policies):
    v = _clean(df, roles["value"])
    target = roles.get("target")
    if target is None:
        return _result("insufficient_data", n=v.size,
                       reason="no comparison target provided for one-sample test")
    if v.size < 3:
        return _result("insufficient_data", n=v.size, reason="fewer than 3 values")
    _t, p = stats.ttest_1samp(v, float(target))
    d = (np.mean(v) - float(target)) / np.std(v, ddof=1) if np.std(v, ddof=1) > 0 else 0.0
    return _result("ok", results={"effect": _finite(np.mean(v) - float(target)),
                                  "effectName": "mean_difference", "pValue": _finite(p),
                                  "cohensD": _finite(d)}, n=v.size, usable_n=v.size)


# --------------------------------------------------------------------------- #
# Time series
# --------------------------------------------------------------------------- #
def _ordered_series(df, roles):
    value = roles["value"]
    time = roles.get("time")
    sub = df.copy()
    sub[value] = pd.to_numeric(sub[value], errors="coerce")
    if time and time in sub.columns:
        sub["_t"] = pd.to_datetime(sub[time], errors="coerce")
        sub = sub.dropna(subset=[value, "_t"]).sort_values("_t")
    else:
        sub = sub.dropna(subset=[value])
    return sub[value].to_numpy(float)


def _trend_slope(df, roles, profile, policies):
    y = _ordered_series(df, roles)
    if y.size < _DEFAULT_MIN_N:
        return _result("insufficient_data", n=y.size, reason="too few ordered points for a trend")
    x = np.arange(y.size, dtype=float)
    lin = stats.linregress(x, y)
    ci = 1.96 * lin.stderr
    results = {"slope": _finite(lin.slope), "pValue": _finite(lin.pvalue),
               "rSquared": _finite(lin.rvalue ** 2),
               "confidenceInterval": [_finite(lin.slope - ci), _finite(lin.slope + ci)]}
    return _result("ok", results=results, n=y.size, usable_n=y.size)


def _mann_kendall_trend(df, roles, profile, policies):
    y = _ordered_series(df, roles)
    if y.size < _DEFAULT_MIN_N:
        return _result("insufficient_data", n=y.size, reason="too few ordered points")
    tau, p = stats.kendalltau(np.arange(y.size), y)
    trend = "increasing" if tau > 0 and p < 0.05 else "decreasing" if tau < 0 and p < 0.05 else "no trend"
    return _result("ok", results={"effect": _finite(tau), "effectName": "kendall_tau",
                                  "pValue": _finite(p), "trend": trend}, n=y.size, usable_n=y.size)


def _sens_slope(df, roles, profile, policies):
    y = _ordered_series(df, roles)
    if y.size < _DEFAULT_MIN_N:
        return _result("insufficient_data", n=y.size, reason="too few ordered points")
    x = np.arange(y.size, dtype=float)
    ts = stats.theilslopes(y, x)
    return _result("ok", results={"slope": _finite(ts[0]),
                                  "confidenceInterval": [_finite(ts[2]), _finite(ts[3])]},
                   n=y.size, usable_n=y.size)


def _stl_decomposition(df, roles, profile, policies):
    from statsmodels.tsa.seasonal import STL

    y = _ordered_series(df, roles)
    n = y.size
    if n < 16:
        return _result("insufficient_data", n=n, reason="need >= 16 points for STL")
    period = min(12, n // 2)
    try:
        res = STL(y, period=period, robust=True).fit()
    except Exception as exc:
        return _result("error", n=n, reason=f"STL failed: {exc}")
    var_resid = np.var(res.resid)
    trend_strength = max(0.0, 1 - var_resid / np.var(res.trend + res.resid)) if np.var(res.trend + res.resid) > 0 else 0.0
    seasonal_strength = max(0.0, 1 - var_resid / np.var(res.seasonal + res.resid)) if np.var(res.seasonal + res.resid) > 0 else 0.0
    return _result("ok", results={"trendStrength": _finite(trend_strength),
                                  "seasonalStrength": _finite(seasonal_strength),
                                  "period": int(period)}, n=n, usable_n=n)
