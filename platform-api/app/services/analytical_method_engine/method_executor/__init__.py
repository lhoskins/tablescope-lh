
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd

from .categorical_tests import _chi_square_independence, _fisher_exact
from .correlation import _CORR_MIN_N as _CORR_MIN_N
from .correlation import _kendall_correlation, _pearson_correlation, _spearman_correlation
from .descriptive import _DEFAULT_MIN_N as _DEFAULT_MIN_N
from .descriptive import _assumption as _assumption
from .descriptive import _clean as _clean
from .descriptive import _describe_numeric, _normality_test, _result, logger
from .descriptive import _finite as _finite
from .descriptive import _pair as _pair
from .group_comparison import _cohens_d as _cohens_d
from .group_comparison import _eta_squared as _eta_squared
from .group_comparison import (
    _kruskal_wallis,
    _mann_whitney_u,
    _one_way_anova,
    _paired_t_test,
    _students_t_test,
    _welch_anova,
    _welch_t_test,
    _wilcoxon_signed_rank,
)
from .group_comparison import _multi_groups as _multi_groups
from .group_comparison import _paired as _paired
from .group_comparison import _two_groups as _two_groups
from .regression import _REG_MIN_PER_PREDICTOR as _REG_MIN_PER_PREDICTOR
from .regression import _glm as _glm
from .regression import _linear_regression, _logistic_regression, _negative_binomial_regression, _poisson_regression
from .regression import _reg_frame as _reg_frame
from .trend_timeseries import _mann_kendall_trend, _one_sample_t_test, _sens_slope, _stl_decomposition, _trend_slope
from .trend_timeseries import _ordered_series as _ordered_series

"""Stage C — Method Executor.

Runs the deterministic scipy/statsmodels computation for a selected method after
applying assumption gates (minimum-n floor, null policy, outlier handling). Each
executor returns a normalized ``ExecResult`` dict; it never raises — failures
become an ``error``/``insufficient_data`` status the envelope reports safely.
"""


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
