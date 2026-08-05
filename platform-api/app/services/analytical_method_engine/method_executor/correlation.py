
from __future__ import annotations

import math

import numpy as np
from scipy import stats

from .descriptive import _assumption, _finite, _pair, _result

_CORR_MIN_N = 10


def _pearson_correlation(df, roles, profile, policies):
    x, y, n = _pair(df, roles)
    total = len(df)
    if n < _CORR_MIN_N:
        return _result("insufficient_data", n=total, usable_n=n,
                       reason=f"fewer than {_CORR_MIN_N} complete pairs")
    r, p = stats.pearsonr(x, y)
    lin = stats.linregress(x, y)
    # Fisher z CI for r
    z = np.arctanh(r)
    se = 1.0 / math.sqrt(n - 3)
    lo, hi = math.tanh(z - 1.96 * se), math.tanh(z + 1.96 * se)
    results = {
        "effect": _finite(r), "effectName": "pearson_r", "pValue": _finite(p),
        "rSquared": _finite(r * r), "slope": _finite(lin.slope),
        "intercept": _finite(lin.intercept),
        "confidenceInterval": [_finite(lo), _finite(hi)],
    }
    xinfo = profile["columns"].get(roles["x"], {})
    yinfo = profile["columns"].get(roles["y"], {})
    assumptions = [
        _assumption("normality", "met" if xinfo.get("is_normal") and yinfo.get("is_normal")
                    else "not_met", "warning"),
        _assumption("independent_observations", "not_verifiable", "warning"),
    ]
    excl = total - n
    return _result("ok", results=results, assumptions=assumptions, n=total,
                   usable_n=n, missing=excl, caveats=["Association does not establish causation"])


def _spearman_correlation(df, roles, profile, policies):
    x, y, n = _pair(df, roles)
    total = len(df)
    if n < _CORR_MIN_N:
        return _result("insufficient_data", n=total, usable_n=n,
                       reason=f"fewer than {_CORR_MIN_N} complete pairs")
    rho, p = stats.spearmanr(x, y)
    ts = stats.theilslopes(y, x)
    results = {"effect": _finite(rho), "effectName": "spearman_rho", "pValue": _finite(p),
               "slope": _finite(ts[0]), "confidenceInterval": [_finite(ts[2]), _finite(ts[3])]}
    return _result("ok", results=results, n=total, usable_n=n,
                   assumptions=[_assumption("monotonic_relationship", "assumed")],
                   caveats=["Association does not establish causation"])


def _kendall_correlation(df, roles, profile, policies):
    x, y, n = _pair(df, roles)
    total = len(df)
    if n < _CORR_MIN_N:
        return _result("insufficient_data", n=total, usable_n=n,
                       reason=f"fewer than {_CORR_MIN_N} complete pairs")
    tau, p = stats.kendalltau(x, y)
    results = {"effect": _finite(tau), "effectName": "kendall_tau", "pValue": _finite(p)}
    return _result("ok", results=results, n=total, usable_n=n)
