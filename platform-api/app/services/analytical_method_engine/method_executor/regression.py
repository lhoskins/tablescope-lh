
from __future__ import annotations

import math

import pandas as pd

from .descriptive import _DEFAULT_MIN_N, _finite, _result

_REG_MIN_PER_PREDICTOR = 10


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
