
from __future__ import annotations

import math

import pandas as pd
from scipy import stats

from .descriptive import _DEFAULT_MIN_N, _finite, _result


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
