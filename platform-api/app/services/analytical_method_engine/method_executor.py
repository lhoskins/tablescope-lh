"""Stage C — Method Executor.

Runs the deterministic scipy/statsmodels computation for a selected method after
applying assumption gates (minimum-n floor, null policy, outlier handling). Each
executor returns a normalized ``ExecResult`` dict; it never raises — failures
become an ``error``/``insufficient_data`` status the envelope reports safely.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)

_DEFAULT_MIN_N = 8
_CORR_MIN_N = 10
_REG_MIN_PER_PREDICTOR = 10


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


# --------------------------------------------------------------------------- #
# Significance tests
# --------------------------------------------------------------------------- #
def _cohens_d(a, b):
    na, nb = len(a), len(b)
    sp = math.sqrt(((na - 1) * np.var(a, ddof=1) + (nb - 1) * np.var(b, ddof=1)) / (na + nb - 2))
    return (np.mean(a) - np.mean(b)) / sp if sp > 0 else 0.0


def _two_groups(df, roles):
    sub = df[[roles["value"], roles["group"]]].copy()
    sub[roles["value"]] = pd.to_numeric(sub[roles["value"]], errors="coerce")
    sub = sub.dropna()
    groups = [g[roles["value"]].to_numpy(float) for _, g in sub.groupby(roles["group"])]
    return [g for g in groups if g.size > 0]


def _welch_t_test(df, roles, profile, policies):
    groups = _two_groups(df, roles)
    if len(groups) != 2 or min(len(g) for g in groups) < 3:
        return _result("insufficient_data", reason="need 2 groups with >=3 values each")
    a, b = groups
    t, p = stats.ttest_ind(a, b, equal_var=False)
    results = {"effect": _finite(np.mean(a) - np.mean(b)), "effectName": "mean_difference",
               "pValue": _finite(p), "cohensD": _finite(_cohens_d(a, b)),
               "statistic": _finite(t)}
    return _result("ok", results=results, n=len(a) + len(b), usable_n=len(a) + len(b))


def _students_t_test(df, roles, profile, policies):
    groups = _two_groups(df, roles)
    if len(groups) != 2 or min(len(g) for g in groups) < 3:
        return _result("insufficient_data", reason="need 2 groups with >=3 values each")
    a, b = groups
    t, p = stats.ttest_ind(a, b, equal_var=True)
    results = {"effect": _finite(np.mean(a) - np.mean(b)), "effectName": "mean_difference",
               "pValue": _finite(p), "cohensD": _finite(_cohens_d(a, b)), "statistic": _finite(t)}
    return _result("ok", results=results, n=len(a) + len(b), usable_n=len(a) + len(b))


def _mann_whitney_u(df, roles, profile, policies):
    groups = _two_groups(df, roles)
    if len(groups) != 2 or min(len(g) for g in groups) < 3:
        return _result("insufficient_data", reason="need 2 groups with >=3 values each")
    a, b = groups
    u, p = stats.mannwhitneyu(a, b, alternative="two-sided")
    rbc = 1.0 - (2.0 * u) / (len(a) * len(b))
    results = {"effect": _finite(rbc), "effectName": "rank_biserial", "pValue": _finite(p),
               "statistic": _finite(u)}
    return _result("ok", results=results, n=len(a) + len(b), usable_n=len(a) + len(b))


def _paired(df, roles):
    sub = df[[roles["a"], roles["b"]]].apply(pd.to_numeric, errors="coerce").dropna()
    return sub[roles["a"]].to_numpy(float), sub[roles["b"]].to_numpy(float)


def _paired_t_test(df, roles, profile, policies):
    a, b = _paired(df, roles)
    if a.size < 3:
        return _result("insufficient_data", n=a.size, reason="fewer than 3 paired values")
    t, p = stats.ttest_rel(a, b)
    diff = a - b
    d = np.mean(diff) / np.std(diff, ddof=1) if np.std(diff, ddof=1) > 0 else 0.0
    results = {"effect": _finite(np.mean(diff)), "effectName": "mean_difference",
               "pValue": _finite(p), "cohensD": _finite(d), "statistic": _finite(t)}
    return _result("ok", results=results, n=a.size, usable_n=a.size)


def _wilcoxon_signed_rank(df, roles, profile, policies):
    a, b = _paired(df, roles)
    if a.size < 3:
        return _result("insufficient_data", n=a.size, reason="fewer than 3 paired values")
    try:
        stat, p = stats.wilcoxon(a, b)
    except ValueError as exc:
        return _result("error", n=a.size, reason=str(exc))
    return _result("ok", results={"effect": _finite(stat), "effectName": "wilcoxon_w",
                                  "pValue": _finite(p)}, n=a.size, usable_n=a.size)


def _multi_groups(df, roles):
    sub = df[[roles["value"], roles["group"]]].copy()
    sub[roles["value"]] = pd.to_numeric(sub[roles["value"]], errors="coerce")
    sub = sub.dropna()
    groups = [g[roles["value"]].to_numpy(float) for _, g in sub.groupby(roles["group"])]
    return [g for g in groups if g.size > 0]


def _eta_squared(groups):
    all_v = np.concatenate(groups)
    grand = np.mean(all_v)
    ss_between = sum(len(g) * (np.mean(g) - grand) ** 2 for g in groups)
    ss_total = np.sum((all_v - grand) ** 2)
    return ss_between / ss_total if ss_total > 0 else 0.0


def _one_way_anova(df, roles, profile, policies):
    groups = _multi_groups(df, roles)
    if len(groups) < 3 or min(len(g) for g in groups) < 2:
        return _result("insufficient_data", reason="need >=3 groups with >=2 values each")
    f, p = stats.f_oneway(*groups)
    results = {"effect": _finite(f), "effectName": "f_statistic", "pValue": _finite(p),
               "etaSquared": _finite(_eta_squared(groups))}
    n = sum(len(g) for g in groups)
    return _result("ok", results=results, n=n, usable_n=n)


def _welch_anova(df, roles, profile, policies):
    groups = _multi_groups(df, roles)
    if len(groups) < 3 or min(len(g) for g in groups) < 2:
        return _result("insufficient_data", reason="need >=3 groups with >=2 values each")
    # Welch's ANOVA
    k = len(groups)
    n_i = np.array([len(g) for g in groups], float)
    m_i = np.array([np.mean(g) for g in groups])
    v_i = np.array([np.var(g, ddof=1) for g in groups])
    w_i = n_i / v_i
    w = np.sum(w_i)
    m = np.sum(w_i * m_i) / w
    num = np.sum(w_i * (m_i - m) ** 2) / (k - 1)
    denom = 1 + (2 * (k - 2) / (k**2 - 1)) * np.sum((1 - w_i / w) ** 2 / (n_i - 1))
    f = num / denom
    df1 = k - 1
    df2 = (k**2 - 1) / (3 * np.sum((1 - w_i / w) ** 2 / (n_i - 1)))
    p = stats.f.sf(f, df1, df2)
    n = int(np.sum(n_i))
    return _result("ok", results={"effect": _finite(f), "effectName": "welch_f",
                                  "pValue": _finite(p)}, n=n, usable_n=n)


def _kruskal_wallis(df, roles, profile, policies):
    groups = _multi_groups(df, roles)
    if len(groups) < 3 or min(len(g) for g in groups) < 2:
        return _result("insufficient_data", reason="need >=3 groups with >=2 values each")
    h, p = stats.kruskal(*groups)
    n = sum(len(g) for g in groups)
    return _result("ok", results={"effect": _finite(h), "effectName": "h_statistic",
                                  "pValue": _finite(p)}, n=n, usable_n=n)


def _chi_square_independence(df, roles, profile, policies):
    sub = df[[roles["a"], roles["b"]]].dropna()
    if len(sub) < _DEFAULT_MIN_N:
        return _result("insufficient_data", n=len(sub), reason="too few rows for contingency test")
    table = pd.crosstab(sub[roles["a"]], sub[roles["b"]])
    if table.shape[0] < 2 or table.shape[1] < 2:
        return _result("insufficient_data", n=len(sub), reason="need a 2x2 or larger table")
    chi2, p, dof, expected = stats.chi2_contingency(table)
    n = int(table.values.sum())
    cramer = math.sqrt(chi2 / (n * (min(table.shape) - 1))) if n > 0 else 0.0
    warnings = []
    if (expected < 5).any():
        warnings.append("Some expected cell counts < 5; consider Fisher's exact test")
    results = {"effect": _finite(cramer), "effectName": "cramers_v", "pValue": _finite(p),
               "statistic": _finite(chi2), "dof": int(dof)}
    return _result("ok", results=results, n=n, usable_n=n, warnings=warnings)


def _fisher_exact(df, roles, profile, policies):
    sub = df[[roles["a"], roles["b"]]].dropna()
    table = pd.crosstab(sub[roles["a"]], sub[roles["b"]])
    if table.shape != (2, 2):
        return _result("insufficient_data", n=len(sub), reason="Fisher's exact needs a 2x2 table")
    odds, p = stats.fisher_exact(table.values)
    return _result("ok", results={"effect": _finite(odds), "effectName": "odds_ratio",
                                  "pValue": _finite(p)}, n=int(table.values.sum()),
                   usable_n=int(table.values.sum()))


# --------------------------------------------------------------------------- #
# Regression (statsmodels)
# --------------------------------------------------------------------------- #
def _reg_frame(df, roles):
    cols = [roles["target"], *roles["predictors"]]
    sub = df[cols].apply(pd.to_numeric, errors="coerce").dropna()
    return sub


def _linear_regression(df, roles, profile, policies):
    import statsmodels.api as sm

    sub = _reg_frame(df, roles)
    p = len(roles["predictors"])
    if len(sub) < _REG_MIN_PER_PREDICTOR * p:
        return _result("insufficient_data", n=len(sub),
                       reason=f"need >= {_REG_MIN_PER_PREDICTOR} rows per predictor")
    y = sub[roles["target"]]
    X = sm.add_constant(sub[roles["predictors"]])
    model = sm.OLS(y, X).fit()
    results = {
        "rSquared": _finite(model.rsquared), "adjRSquared": _finite(model.rsquared_adj),
        "coefficients": {k: _finite(v) for k, v in model.params.items()},
        "pValues": {k: _finite(v) for k, v in model.pvalues.items()},
    }
    return _result("ok", results=results, n=len(sub), usable_n=len(sub),
                   caveats=["Coefficients are associational, not causal"])


def _logistic_regression(df, roles, profile, policies):
    import statsmodels.api as sm

    sub = _reg_frame(df, roles)
    if len(sub) < _DEFAULT_MIN_N or sub[roles["target"]].nunique() != 2:
        return _result("insufficient_data", n=len(sub), reason="binary target with enough rows required")
    y = pd.factorize(sub[roles["target"]])[0]
    X = sm.add_constant(sub[roles["predictors"]])
    try:
        model = sm.Logit(y, X).fit(disp=0)
    except Exception as exc:
        return _result("error", n=len(sub), reason=f"logistic fit failed: {exc}")
    results = {
        "coefficients": {k: _finite(v) for k, v in model.params.items()},
        "oddsRatios": {k: _finite(math.exp(v)) for k, v in model.params.items() if _finite(v) is not None},
        "pValues": {k: _finite(v) for k, v in model.pvalues.items()},
        "pseudoRSquared": _finite(model.prsquared),
    }
    return _result("ok", results=results, n=len(sub), usable_n=len(sub),
                   caveats=["Coefficients are associational, not causal"])


def _glm(df, roles, family_name):
    import statsmodels.api as sm

    sub = _reg_frame(df, roles)
    if len(sub) < _DEFAULT_MIN_N:
        return None, sub
    y = sub[roles["target"]]
    X = sm.add_constant(sub[roles["predictors"]])
    family = sm.families.Poisson() if family_name == "poisson" else sm.families.NegativeBinomial()
    try:
        return sm.GLM(y, X, family=family).fit(), sub
    except Exception:
        return None, sub


def _poisson_regression(df, roles, profile, policies):
    model, sub = _glm(df, roles, "poisson")
    if model is None:
        return _result("insufficient_data", n=len(sub), reason="count regression could not be fit")
    results = {
        "coefficients": {k: _finite(v) for k, v in model.params.items()},
        "pValues": {k: _finite(v) for k, v in model.pvalues.items()},
    }
    return _result("ok", results=results, n=len(sub), usable_n=len(sub))


def _negative_binomial_regression(df, roles, profile, policies):
    model, sub = _glm(df, roles, "negbin")
    if model is None:
        return _result("insufficient_data", n=len(sub), reason="count regression could not be fit")
    results = {
        "coefficients": {k: _finite(v) for k, v in model.params.items()},
        "pValues": {k: _finite(v) for k, v in model.pvalues.items()},
    }
    return _result("ok", results=results, n=len(sub), usable_n=len(sub))


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


EXECUTORS: dict[str, Callable[..., dict[str, Any]]] = {
    "describe_numeric": _describe_numeric,
    "normality_test": _normality_test,
    "pearson_correlation": _pearson_correlation,
    "spearman_correlation": _spearman_correlation,
    "kendall_correlation": _kendall_correlation,
    "one_sample_t_test": _one_sample_t_test,
    "welch_t_test": _welch_t_test,
    "students_t_test": _students_t_test,
    "mann_whitney_u": _mann_whitney_u,
    "paired_t_test": _paired_t_test,
    "wilcoxon_signed_rank": _wilcoxon_signed_rank,
    "one_way_anova": _one_way_anova,
    "welch_anova": _welch_anova,
    "kruskal_wallis": _kruskal_wallis,
    "chi_square_independence": _chi_square_independence,
    "fisher_exact": _fisher_exact,
    "linear_regression": _linear_regression,
    "logistic_regression": _logistic_regression,
    "poisson_regression": _poisson_regression,
    "negative_binomial_regression": _negative_binomial_regression,
    "trend_slope": _trend_slope,
    "mann_kendall_trend": _mann_kendall_trend,
    "sens_slope": _sens_slope,
    "stl_decomposition": _stl_decomposition,
}


def execute(
    executor_key: str,
    df: pd.DataFrame,
    roles: dict[str, Any],
    profile: dict[str, Any],
    policies: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fn = EXECUTORS.get(executor_key)
    if fn is None:
        return _result("error", reason=f"no executor bound for '{executor_key}'")
    try:
        out = fn(df, roles, profile, policies or {})
    except Exception as exc:
        logger.warning("Executor %s failed: %s", executor_key, exc)
        return _result("error", reason=str(exc))
    # Quality downgrade on small samples.
    if out["status"] == "ok" and out.get("usable_n", 0) and out["usable_n"] < 15:
        out["quality"] = "tentative"
        out["warnings"] = [*out.get("warnings", []), "Small sample; interpret with caution"]
    return out
