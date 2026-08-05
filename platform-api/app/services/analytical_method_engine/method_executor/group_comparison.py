
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats

from .descriptive import _finite, _result


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
