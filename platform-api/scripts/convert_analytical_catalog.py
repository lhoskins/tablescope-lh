#!/usr/bin/env python3
"""Convert the Tablescope Analytical Method Reference Catalog into the structured
seed the Analytical Method Engine consumes.

The source document (``Tablescope Analytical Method Reference Catalog.rtf``) is a
reference *taxonomy* — ~980 method names, each with at most a one-line
applicability condition. This script:

1. Reads a flat extract of that taxonomy (``source_taxonomy.json``: a list of
   ``{category, subcategory, method, condition?}`` produced by parsing the RTF).
2. Merges it with the **authored Tier-1 executable specs** below (method cards,
   selection/rejection rules, output contracts, executor bindings) — the small
   set of methods Tablescope can actually run today via scipy/statsmodels.
3. Tags every entry with a tier (from the catalog's own Tier 1/2/3 lists) and
   emits ``catalog.json`` — every method as a catalog entry, only Tier-1
   executable methods carrying full executable metadata.

Re-run after editing the authored specs::

    python -m scripts.convert_analytical_catalog

All entries land as catalog records; the seed loader decides status (Tier-1
executable -> active, everything else -> draft).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

SEED_DIR = Path(__file__).resolve().parent.parent / "app" / "seed_data" / "analytical_methods"
SOURCE = SEED_DIR / "source_taxonomy.json"
OUTPUT = SEED_DIR / "catalog.json"

SCIPY = ["scipy"]
STATSMODELS = ["scipy", "statsmodels"]
NUMPY = ["numpy"]


def slugify(name: str) -> str:
    s = name.lower()
    s = s.replace("\u2019", "").replace("'", "")
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


# ---------------------------------------------------------------------------
# Shared analytical policies (§ "Engine rule" / "Required wording controls").
# ---------------------------------------------------------------------------
SHARED_POLICIES = [
    {
        "policy_key": "missing_data",
        "name": "Missing-data handling",
        "description": "Missingness is an explicit analytical decision, never a silent row drop.",
        "rules": {
            "report": [
                "missing-data method used",
                "number and percentage of affected observations",
                "whether imputation occurred before or within validation",
                "whether conclusions materially changed under an alternate treatment",
            ],
            "max_null_rate_default": 0.5,
            "fit_transforms_inside_validation": True,
        },
    },
    {
        "policy_key": "outliers",
        "name": "Outlier and influence handling",
        "description": "Fit with and without influential observations and compare.",
        "rules": {
            "detect": ["iqr_tukey_fences", "z_score", "modified_z_score"],
            "compare_with_without": True,
            "mark_sensitive_if_conclusion_changes": True,
        },
    },
    {
        "policy_key": "multiple_testing",
        "name": "Multiple-testing control",
        "description": "Correct for multiplicity when many tests are performed.",
        "rules": {
            "default_method": "benjamini_hochberg",
            "report": [
                "number of tests performed",
                "original p-value",
                "adjusted p-value",
                "correction method",
                "whether the conclusion survived adjustment",
            ],
        },
    },
    {
        "policy_key": "significance_reporting",
        "name": "Significance reporting",
        "description": "A p-value alone is never the primary explanation.",
        "rules": {
            "require_effect_size": True,
            "require_confidence_interval": True,
        },
    },
    {
        "policy_key": "causal_language",
        "name": "Causal-language control",
        "description": "Causal wording is gated behind verified identification assumptions.",
        "rules": {
            "allowed_without_causal_gates": [
                "associated with",
                "predictive of",
                "candidate driver",
                "consistent with",
                "may help explain",
            ],
            "forbidden_without_causal_gates": [
                "caused",
                "led to",
                "resulted in",
                "because of",
            ],
        },
    },
    {
        "policy_key": "minimum_sample_size",
        "name": "Minimum sample size",
        "description": "Return insufficient_data rather than forcing a method on too few rows.",
        "rules": {"default_min_n": 8, "correlation_min_n": 10, "regression_min_n_per_predictor": 10},
    },
]


# ---------------------------------------------------------------------------
# Method-selection matrix (§29). Method ids reference authored executable
# methods below (or Tier-2/3 draft ids for not-yet-executable rows).
# ---------------------------------------------------------------------------
SELECTION_MATRIX = [
    ("describe_numeric", "Numeric", "describe_numeric", ["robust_descriptive_statistics"]),
    ("compare_to_target", "Numeric + fixed target", "one_sample_t_test",
     ["wilcoxon_signed_rank_test", "sign_test"]),
    ("compare_two_groups", "Numeric + binary group", "welch_t_test",
     ["mann_whitney_u_test", "permutation_test"]),
    ("compare_paired", "Paired numeric", "paired_t_test", ["wilcoxon_signed_rank_test"]),
    ("compare_multiple_groups", "Numeric + categorical group", "one_way_anova",
     ["welch_anova", "kruskal_wallis_test"]),
    ("compare_category_rates", "Categorical contingency table", "chi_square_test_of_independence",
     ["fishers_exact_test"]),
    ("relationship_numeric", "Linear, low-outlier", "pearson_correlation",
     ["spearman_rank_correlation"]),
    ("relationship_monotonic", "Numeric/ordinal, non-normal", "spearman_rank_correlation",
     ["kendalls_tau", "mutual_information"]),
    ("binary_outcome", "Binary target", "binary_logistic_regression", ["decision_tree"]),
    ("count_outcome", "Count target", "poisson_regression", ["negative_binomial_regression"]),
    ("zero_heavy_count", "Count + excess zeros", "negative_binomial_regression",
     ["zero_inflated_or_hurdle_model"]),
    ("continuous_prediction", "Numeric target", "multiple_linear_regression",
     ["huber_regression", "ridge_regression"]),
    ("detect_trend", "Ordered time", "ols_trend_slope", ["mann_kendall_trend_test", "sens_slope"]),
    ("trend_seasonality", "Regular time series", "stl_decomposition", ["seasonal_regression"]),
    ("normality", "Numeric", "shapiro_wilk_test",
     ["anderson_darling_test", "dagostino_pearson_normality_test"]),
]


# ---------------------------------------------------------------------------
# Authored Tier-1 executable methods.
# ---------------------------------------------------------------------------
def _card(use_when, dont, checks, fallback, output):
    return {
        "use_when": use_when,
        "do_not_use_when": dont,
        "required_checks": checks,
        "fallback": fallback,
        "output": output,
    }


_GUARDRAILS = [
    "Do not choose the statistical method; explain the method Tablescope selected.",
    "Never invent statistical outputs; report only values present in the envelope.",
    "Do not use causal wording unless the method's causal gates pass.",
    "Always report effect size and confidence interval alongside any p-value.",
]

EXECUTABLE = [
    {
        "method_id": "describe_numeric",
        "display_name": "Descriptive statistics + distribution profile",
        "category": "Data Profiling and Descriptive Statistics",
        "subcategory": "Dataset-level profiling",
        "executor_key": "describe_numeric",
        "dependencies": SCIPY,
        "supported_intents": ["describe_numeric"],
        "selection_rules": ["Exactly one numeric field requested"],
        "rejection_rules": ["No numeric field present"],
        "required_checks": ["n count", "null rate"],
        "fallback_methods": ["robust_descriptive_statistics"],
        "output_contract": {
            "fields": ["n", "mean", "median", "std", "min", "max",
                       "quantiles", "skewness", "kurtosis"]
        },
        "card": _card(
            ["A single numeric field needs summarizing"],
            ["The field is categorical or an identifier"],
            ["n count", "null rate", "distribution shape"],
            ["Robust statistics (median, IQR, MAD)"],
            ["mean", "median", "std", "quantiles", "skew", "kurtosis"],
        ),
    },
    {
        "method_id": "pearson_correlation",
        "display_name": "Pearson correlation + OLS regression",
        "category": "Correlation and Association Analysis",
        "subcategory": "Numeric-to-numeric",
        "executor_key": "pearson_correlation",
        "dependencies": STATSMODELS,
        "supported_intents": ["relationship_numeric"],
        "selection_rules": [
            "Two numeric continuous fields",
            "Relationship appears linear",
            "Outliers are low",
            "Sample size is sufficient",
            "Observations are independent",
        ],
        "rejection_rules": [
            "Relationship is nonlinear or only monotonic",
            "Heavy outliers exist",
            "Data is ordinal",
            "Strong missing-data bias exists",
        ],
        "required_checks": ["n count", "null rate", "outlier rate",
                            "normality/residual check", "leverage/influence check"],
        "fallback_methods": ["spearman_rank_correlation", "kendalls_tau"],
        "output_contract": {
            "fields": ["effect", "effectName", "pValue", "rSquared",
                       "confidenceInterval", "slope", "intercept"]
        },
        "card": _card(
            ["Two numeric continuous fields", "Relationship appears linear",
             "Outliers are low", "Sample size is sufficient"],
            ["Relationship is nonlinear or only monotonic", "Heavy outliers exist",
             "Data is ordinal"],
            ["n count", "null rate", "outlier rate", "normality/residual check",
             "leverage/influence check"],
            ["Spearman correlation", "Kendall correlation", "Huber/Theil-Sen regression"],
            ["slope", "intercept", "correlation coefficient", "R^2", "p-value",
             "confidence interval", "outlier count", "assumption warnings"],
        ),
    },
    {
        "method_id": "spearman_rank_correlation",
        "display_name": "Spearman rank correlation + robust regression",
        "category": "Correlation and Association Analysis",
        "subcategory": "Numeric-to-numeric",
        "executor_key": "spearman_correlation",
        "dependencies": SCIPY,
        "supported_intents": ["relationship_monotonic", "relationship_numeric"],
        "selection_rules": ["Ordinal or continuous", "Monotonic relationship",
                            "Non-normal or outlier-prone"],
        "rejection_rules": ["Relationship is non-monotonic"],
        "required_checks": ["n count", "null rate", "monotonicity"],
        "fallback_methods": ["kendalls_tau"],
        "output_contract": {"fields": ["effect", "effectName", "pValue", "confidenceInterval"]},
        "card": _card(
            ["Ordinal or continuous fields", "Monotonic relationship",
             "Non-normal or outlier-prone data"],
            ["Relationship is non-monotonic"],
            ["n count", "null rate", "monotonicity"],
            ["Kendall's tau"],
            ["spearman rho", "p-value", "confidence interval"],
        ),
    },
    {
        "method_id": "kendalls_tau",
        "display_name": "Kendall's tau correlation",
        "category": "Correlation and Association Analysis",
        "subcategory": "Numeric-to-numeric",
        "executor_key": "kendall_correlation",
        "dependencies": SCIPY,
        "supported_intents": ["relationship_monotonic"],
        "selection_rules": ["Ordinal", "Small samples", "Many ties", "Monotonic relationships"],
        "rejection_rules": ["Large samples where Spearman suffices"],
        "required_checks": ["n count", "null rate"],
        "fallback_methods": ["spearman_rank_correlation"],
        "output_contract": {"fields": ["effect", "effectName", "pValue"]},
        "card": _card(
            ["Ordinal data", "Small samples", "Many ties"],
            ["Non-monotonic relationship"],
            ["n count", "null rate"],
            ["Spearman correlation"],
            ["kendall tau", "p-value"],
        ),
    },
    {
        "method_id": "one_sample_t_test",
        "display_name": "One-sample t-test",
        "category": "Statistical Significance Testing",
        "subcategory": "One-sample tests",
        "executor_key": "one_sample_t_test",
        "dependencies": SCIPY,
        "supported_intents": ["compare_to_target"],
        "selection_rules": ["One numeric field", "Fixed comparison target",
                            "Approximately normal or n large"],
        "rejection_rules": ["Heavily skewed with small n"],
        "required_checks": ["n count", "null rate", "normality check"],
        "fallback_methods": ["wilcoxon_signed_rank_test", "sign_test"],
        "output_contract": {"fields": ["effect", "effectName", "pValue",
                                       "confidenceInterval", "cohensD"]},
        "card": _card(
            ["One numeric field compared to a fixed target",
             "Approximately normal or large n"],
            ["Heavily skewed with small n"],
            ["n count", "null rate", "normality check"],
            ["Wilcoxon signed-rank test", "Sign test"],
            ["mean difference", "p-value", "confidence interval", "Cohen's d"],
        ),
    },
    {
        "method_id": "welch_t_test",
        "display_name": "Welch's t-test (two independent groups)",
        "category": "Statistical Significance Testing",
        "subcategory": "Two independent samples",
        "executor_key": "welch_t_test",
        "dependencies": SCIPY,
        "supported_intents": ["compare_two_groups"],
        "selection_rules": ["Numeric outcome", "Binary independent group",
                            "Unequal variances tolerated"],
        "rejection_rules": ["Paired observations", "Heavily non-normal small samples"],
        "required_checks": ["n count", "null rate", "normality check"],
        "fallback_methods": ["mann_whitney_u_test", "permutation_test"],
        "output_contract": {"fields": ["effect", "effectName", "pValue",
                                       "confidenceInterval", "cohensD"]},
        "card": _card(
            ["Numeric outcome split by a binary group", "Independent samples"],
            ["Paired observations", "Heavily non-normal small samples"],
            ["n count per group", "null rate", "normality check"],
            ["Mann-Whitney U", "Permutation test"],
            ["mean difference", "p-value", "confidence interval", "Cohen's d"],
        ),
    },
    {
        "method_id": "students_t_test",
        "display_name": "Student's independent t-test",
        "category": "Statistical Significance Testing",
        "subcategory": "Two independent samples",
        "executor_key": "students_t_test",
        "dependencies": SCIPY,
        "supported_intents": ["compare_two_groups"],
        "selection_rules": ["Numeric outcome", "Binary group", "Equal variances"],
        "rejection_rules": ["Unequal variances", "Paired observations"],
        "required_checks": ["n count", "equal-variance check"],
        "fallback_methods": ["welch_t_test", "mann_whitney_u_test"],
        "output_contract": {"fields": ["effect", "pValue", "confidenceInterval", "cohensD"]},
        "card": _card(
            ["Numeric outcome, binary group, equal variances"],
            ["Unequal variances", "Paired data"],
            ["n count", "equal-variance check (Levene)"],
            ["Welch's t-test", "Mann-Whitney U"],
            ["mean difference", "p-value", "Cohen's d"],
        ),
    },
    {
        "method_id": "mann_whitney_u_test",
        "display_name": "Mann-Whitney U test",
        "category": "Statistical Significance Testing",
        "subcategory": "Two independent samples",
        "executor_key": "mann_whitney_u",
        "dependencies": SCIPY,
        "supported_intents": ["compare_two_groups"],
        "selection_rules": ["Numeric or ordinal outcome", "Binary group", "Non-normal"],
        "rejection_rules": ["Paired observations"],
        "required_checks": ["n count", "null rate"],
        "fallback_methods": ["welch_t_test"],
        "output_contract": {"fields": ["effect", "effectName", "pValue"]},
        "card": _card(
            ["Non-normal numeric/ordinal outcome by binary group"],
            ["Paired observations"],
            ["n count per group", "null rate"],
            ["Welch's t-test"],
            ["rank-biserial effect", "p-value"],
        ),
    },
    {
        "method_id": "paired_t_test",
        "display_name": "Paired t-test",
        "category": "Statistical Significance Testing",
        "subcategory": "Paired samples",
        "executor_key": "paired_t_test",
        "dependencies": SCIPY,
        "supported_intents": ["compare_paired"],
        "selection_rules": ["Two paired numeric measurements", "Approximately normal differences"],
        "rejection_rules": ["Independent groups", "Non-normal differences, small n"],
        "required_checks": ["n count", "normality of differences"],
        "fallback_methods": ["wilcoxon_signed_rank_test"],
        "output_contract": {"fields": ["effect", "pValue", "confidenceInterval", "cohensD"]},
        "card": _card(
            ["Two paired numeric measurements", "Normal differences"],
            ["Independent groups"],
            ["n count", "normality of differences"],
            ["Wilcoxon signed-rank test"],
            ["mean difference", "p-value", "Cohen's d"],
        ),
    },
    {
        "method_id": "wilcoxon_signed_rank_test",
        "display_name": "Wilcoxon signed-rank test",
        "category": "Statistical Significance Testing",
        "subcategory": "Paired samples",
        "executor_key": "wilcoxon_signed_rank",
        "dependencies": SCIPY,
        "supported_intents": ["compare_paired", "compare_to_target"],
        "selection_rules": ["Paired numeric/ordinal", "Non-normal differences"],
        "rejection_rules": ["Independent groups"],
        "required_checks": ["n count"],
        "fallback_methods": ["sign_test"],
        "output_contract": {"fields": ["effect", "pValue"]},
        "card": _card(
            ["Paired numeric/ordinal, non-normal differences"],
            ["Independent groups"],
            ["n count"],
            ["Sign test"],
            ["statistic", "p-value"],
        ),
    },
    {
        "method_id": "one_way_anova",
        "display_name": "One-way ANOVA",
        "category": "Statistical Significance Testing",
        "subcategory": "Three or more independent groups",
        "executor_key": "one_way_anova",
        "dependencies": SCIPY,
        "supported_intents": ["compare_multiple_groups"],
        "selection_rules": ["Numeric outcome", "3+ groups", "Equal variances", "Normal residuals"],
        "rejection_rules": ["Unequal variances", "Non-normal small samples"],
        "required_checks": ["n count", "equal-variance check", "normality check"],
        "fallback_methods": ["welch_anova", "kruskal_wallis_test"],
        "output_contract": {"fields": ["effect", "effectName", "pValue", "etaSquared"]},
        "card": _card(
            ["Numeric outcome across 3+ groups", "Equal variances, normal residuals"],
            ["Unequal variances", "Non-normal small samples"],
            ["n per group", "equal-variance check", "normality check"],
            ["Welch ANOVA", "Kruskal-Wallis"],
            ["F statistic", "p-value", "eta squared"],
        ),
    },
    {
        "method_id": "welch_anova",
        "display_name": "Welch ANOVA",
        "category": "Statistical Significance Testing",
        "subcategory": "Three or more independent groups",
        "executor_key": "welch_anova",
        "dependencies": STATSMODELS,
        "supported_intents": ["compare_multiple_groups"],
        "selection_rules": ["Numeric outcome", "3+ groups", "Unequal variances"],
        "rejection_rules": ["Non-normal small samples"],
        "required_checks": ["n count", "normality check"],
        "fallback_methods": ["kruskal_wallis_test"],
        "output_contract": {"fields": ["effect", "pValue"]},
        "card": _card(
            ["Numeric outcome across 3+ groups", "Unequal variances"],
            ["Non-normal small samples"],
            ["n per group", "normality check"],
            ["Kruskal-Wallis"],
            ["F statistic", "p-value"],
        ),
    },
    {
        "method_id": "kruskal_wallis_test",
        "display_name": "Kruskal-Wallis test",
        "category": "Statistical Significance Testing",
        "subcategory": "Three or more independent groups",
        "executor_key": "kruskal_wallis",
        "dependencies": SCIPY,
        "supported_intents": ["compare_multiple_groups"],
        "selection_rules": ["Numeric/ordinal outcome", "3+ groups", "Non-normal"],
        "rejection_rules": ["Repeated measures"],
        "required_checks": ["n count"],
        "fallback_methods": ["one_way_anova"],
        "output_contract": {"fields": ["effect", "pValue"]},
        "card": _card(
            ["Non-normal numeric/ordinal outcome across 3+ groups"],
            ["Repeated measures"],
            ["n per group"],
            ["One-way ANOVA"],
            ["H statistic", "p-value"],
        ),
    },
    {
        "method_id": "chi_square_test_of_independence",
        "display_name": "Chi-square test of independence",
        "category": "Correlation and Association Analysis",
        "subcategory": "Categorical-to-categorical",
        "executor_key": "chi_square_independence",
        "dependencies": SCIPY,
        "supported_intents": ["compare_category_rates"],
        "selection_rules": ["Two categorical fields", "Expected cell counts >= 5"],
        "rejection_rules": ["Sparse table with low expected counts"],
        "required_checks": ["n count", "expected cell counts"],
        "fallback_methods": ["fishers_exact_test"],
        "output_contract": {"fields": ["effect", "effectName", "pValue"]},
        "card": _card(
            ["Two categorical fields", "Expected cell counts >= 5"],
            ["Sparse table with low expected counts"],
            ["n count", "expected cell counts"],
            ["Fisher's exact test"],
            ["chi-square", "Cramer's V", "p-value"],
        ),
    },
    {
        "method_id": "fishers_exact_test",
        "display_name": "Fisher's exact test",
        "category": "Correlation and Association Analysis",
        "subcategory": "Categorical-to-categorical",
        "executor_key": "fisher_exact",
        "dependencies": SCIPY,
        "supported_intents": ["compare_category_rates"],
        "selection_rules": ["2x2 categorical table", "Small or sparse counts"],
        "rejection_rules": ["Table larger than 2x2"],
        "required_checks": ["n count"],
        "fallback_methods": ["chi_square_test_of_independence"],
        "output_contract": {"fields": ["effect", "effectName", "pValue"]},
        "card": _card(
            ["2x2 categorical table, small/sparse counts"],
            ["Table larger than 2x2"],
            ["n count"],
            ["Chi-square test"],
            ["odds ratio", "p-value"],
        ),
    },
    {
        "method_id": "multiple_linear_regression",
        "display_name": "Multiple linear regression (OLS)",
        "category": "Regression Methods",
        "subcategory": "Standard continuous-outcome regression",
        "executor_key": "linear_regression",
        "dependencies": STATSMODELS,
        "supported_intents": ["continuous_prediction", "explain_change"],
        "selection_rules": ["Numeric target", "One or more predictors", "Approximately linear"],
        "rejection_rules": ["Non-linear relationships", "Severe collinearity"],
        "required_checks": ["n count", "collinearity (VIF)", "homoscedasticity", "residual normality"],
        "fallback_methods": ["huber_regression", "ridge_regression"],
        "output_contract": {"fields": ["rSquared", "adjRSquared", "coefficients",
                                       "pValues", "confidenceInterval"]},
        "card": _card(
            ["Numeric target with numeric predictors", "Approximately linear"],
            ["Non-linear relationships", "Severe collinearity"],
            ["n per predictor", "VIF", "homoscedasticity", "residual normality"],
            ["Huber regression", "Ridge regression"],
            ["R^2", "adjusted R^2", "coefficients", "p-values", "confidence intervals"],
        ),
    },
    {
        "method_id": "binary_logistic_regression",
        "display_name": "Binary logistic regression",
        "category": "Regression Methods",
        "subcategory": "Generalized linear models",
        "executor_key": "logistic_regression",
        "dependencies": STATSMODELS,
        "supported_intents": ["binary_outcome"],
        "selection_rules": ["Binary target", "One or more predictors"],
        "rejection_rules": ["Multiclass target", "Perfect separation"],
        "required_checks": ["n count", "class balance", "collinearity (VIF)"],
        "fallback_methods": ["decision_tree"],
        "output_contract": {"fields": ["coefficients", "oddsRatios", "pValues", "pseudoRSquared"]},
        "card": _card(
            ["Binary target with predictors"],
            ["Multiclass target", "Perfect separation"],
            ["n count", "class balance", "VIF"],
            ["Decision tree with explanation"],
            ["coefficients", "odds ratios", "p-values", "pseudo R^2"],
        ),
    },
    {
        "method_id": "poisson_regression",
        "display_name": "Poisson regression",
        "category": "Regression Methods",
        "subcategory": "Generalized linear models",
        "executor_key": "poisson_regression",
        "dependencies": STATSMODELS,
        "supported_intents": ["count_outcome"],
        "selection_rules": ["Count target", "Mean approximately equals variance"],
        "rejection_rules": ["Overdispersion", "Excess zeros"],
        "required_checks": ["n count", "overdispersion check"],
        "fallback_methods": ["negative_binomial_regression"],
        "output_contract": {"fields": ["coefficients", "rateRatios", "pValues"]},
        "card": _card(
            ["Count target, mean ~ variance"],
            ["Overdispersion", "Excess zeros"],
            ["n count", "overdispersion check"],
            ["Negative-binomial regression"],
            ["coefficients", "rate ratios", "p-values"],
        ),
    },
    {
        "method_id": "negative_binomial_regression",
        "display_name": "Negative-binomial regression",
        "category": "Regression Methods",
        "subcategory": "Generalized linear models",
        "executor_key": "negative_binomial_regression",
        "dependencies": STATSMODELS,
        "supported_intents": ["count_outcome", "zero_heavy_count"],
        "selection_rules": ["Overdispersed count target"],
        "rejection_rules": ["Excess structural zeros needing hurdle model"],
        "required_checks": ["n count", "overdispersion check"],
        "fallback_methods": ["poisson_regression"],
        "output_contract": {"fields": ["coefficients", "rateRatios", "pValues"]},
        "card": _card(
            ["Overdispersed count target"],
            ["Excess structural zeros"],
            ["n count", "overdispersion check"],
            ["Poisson regression", "Zero-inflated/hurdle model"],
            ["coefficients", "rate ratios", "p-values"],
        ),
    },
    {
        "method_id": "ols_trend_slope",
        "display_name": "OLS trend slope",
        "category": "Time-Series Analysis and Forecasting",
        "subcategory": "Trend and seasonality tests",
        "executor_key": "trend_slope",
        "dependencies": STATSMODELS,
        "supported_intents": ["detect_trend"],
        "selection_rules": ["Ordered time index", "Numeric measure"],
        "rejection_rules": ["Strong seasonality dominating trend"],
        "required_checks": ["n count", "autocorrelation"],
        "fallback_methods": ["mann_kendall_trend_test", "sens_slope"],
        "output_contract": {"fields": ["slope", "pValue", "rSquared", "confidenceInterval"]},
        "card": _card(
            ["Ordered time index with a numeric measure"],
            ["Strong seasonality dominating the trend"],
            ["n count", "autocorrelation"],
            ["Mann-Kendall trend test", "Sen's slope"],
            ["slope", "p-value", "R^2", "confidence interval"],
        ),
    },
    {
        "method_id": "mann_kendall_trend_test",
        "display_name": "Mann-Kendall trend test",
        "category": "Time-Series Analysis and Forecasting",
        "subcategory": "Trend and seasonality tests",
        "executor_key": "mann_kendall_trend",
        "dependencies": SCIPY,
        "supported_intents": ["detect_trend"],
        "selection_rules": ["Ordered time index", "Monotonic trend suspected", "Non-normal"],
        "rejection_rules": ["Strong seasonality"],
        "required_checks": ["n count"],
        "fallback_methods": ["sens_slope"],
        "output_contract": {"fields": ["effect", "pValue", "trend"]},
        "card": _card(
            ["Ordered time index, non-normal, monotonic trend suspected"],
            ["Strong seasonality"],
            ["n count"],
            ["Sen's slope"],
            ["tau", "p-value", "trend direction"],
        ),
    },
    {
        "method_id": "sens_slope",
        "display_name": "Sen's slope estimator",
        "category": "Time-Series Analysis and Forecasting",
        "subcategory": "Trend and seasonality tests",
        "executor_key": "sens_slope",
        "dependencies": SCIPY,
        "supported_intents": ["detect_trend"],
        "selection_rules": ["Ordered time index", "Robust slope needed"],
        "rejection_rules": ["Strong seasonality"],
        "required_checks": ["n count"],
        "fallback_methods": ["ols_trend_slope"],
        "output_contract": {"fields": ["slope", "confidenceInterval"]},
        "card": _card(
            ["Ordered time index, robust slope needed"],
            ["Strong seasonality"],
            ["n count"],
            ["OLS trend slope"],
            ["slope", "confidence interval"],
        ),
    },
    {
        "method_id": "shapiro_wilk_test",
        "display_name": "Shapiro-Wilk normality test",
        "category": "Distribution Analysis and Distribution Fitting",
        "subcategory": "Goodness-of-fit methods",
        "executor_key": "normality_test",
        "dependencies": SCIPY,
        "supported_intents": ["normality"],
        "selection_rules": ["One numeric field", "n between 3 and 5000"],
        "rejection_rules": ["n > 5000 (use Anderson-Darling)"],
        "required_checks": ["n count", "null rate"],
        "fallback_methods": ["anderson_darling_test", "dagostino_pearson_normality_test"],
        "output_contract": {"fields": ["statistic", "pValue", "isNormal"]},
        "card": _card(
            ["One numeric field, 3 <= n <= 5000"],
            ["Very large n"],
            ["n count", "null rate"],
            ["Anderson-Darling", "D'Agostino-Pearson"],
            ["W statistic", "p-value", "normal?"],
        ),
    },
    {
        "method_id": "stl_decomposition",
        "display_name": "STL seasonal-trend decomposition",
        "category": "Time-Series Analysis and Forecasting",
        "subcategory": "Decomposition and smoothing",
        "executor_key": "stl_decomposition",
        "dependencies": STATSMODELS,
        "supported_intents": ["trend_seasonality"],
        "selection_rules": ["Regular time series", "At least two full seasonal cycles"],
        "rejection_rules": ["Irregular spacing", "Too few periods"],
        "required_checks": ["n count", "regular spacing", "period detected"],
        "fallback_methods": ["ols_trend_slope"],
        "output_contract": {"fields": ["trendStrength", "seasonalStrength", "period"]},
        "card": _card(
            ["Regular time series with >= 2 seasonal cycles"],
            ["Irregular spacing", "Too few periods"],
            ["n count", "regular spacing", "period detected"],
            ["OLS trend slope"],
            ["trend strength", "seasonal strength", "period"],
        ),
    },
]


# ---------------------------------------------------------------------------
# Tier lists (§32). Fuzzy substring matching against method names.
# ---------------------------------------------------------------------------
TIER1_HINTS = [
    "profiling", "descriptive", "central tendency", "dispersion", "distribution shape",
    "missing", "outlier", "z-score", "iqr", "tukey", "normality", "shapiro", "anderson",
    "pearson", "spearman", "kendall", "point-biserial",
    "linear regression", "multiple linear", "robust", "huber", "theil", "logistic",
    "poisson", "negative-binomial", "negative binomial",
    "t-test", "welch", "mann-whitney", "wilcoxon", "sign test",
    "anova", "kruskal", "chi-square", "chi square", "fisher",
    "effect size", "cohen", "hedges", "cramer", "confidence interval",
    "bonferroni", "holm", "benjamini", "false-discovery", "false discovery",
    "mann-kendall", "mann kendall", "sen", "ols time", "trend",
    "stl decomposition", "change-point", "change point",
    "residual", "durbin", "breusch", "variance inflation",
]
TIER3_HINTS = [
    "bayesian", "mcmc", "hamiltonian", "variational", "deep", "lstm", "gru",
    "transformer", "neural", "graph neural", "causal forest", "double machine",
    "conformal", "kriging", "variogram", "geographically weighted", "autoencoder",
    "umap", "t-sne", "node2vec", "deepwalk", "gaussian-process",
]


def classify_tier(method: str) -> int:
    m = method.lower()
    for hint in TIER3_HINTS:
        if hint in m:
            return 3
    for hint in TIER1_HINTS:
        if hint in m:
            return 1
    return 2


# Non-method meta-sections in the source taxonomy (matrix / tiers / principle /
# contract / decision factors) — imported as structure elsewhere, not as methods.
EXCLUDED_CATEGORIES = {
    "Recommended Tablescope Method-Selection Matrix",
    "Recommended Method-Selection Decision Factors",
    "Recommended Analytical Result Contract",
    "Recommended Implementation Tiers",
    "Recommended Architecture Principle",
}


def build() -> dict:
    taxonomy = json.loads(SOURCE.read_text())

    exec_by_id = {e["method_id"]: e for e in EXECUTABLE}
    # Map common taxonomy names onto executable ids so we don't duplicate them.
    name_to_exec = {
        "descriptive statistics": "describe_numeric",
        "pearson correlation": "pearson_correlation",
        "spearman rank correlation": "spearman_rank_correlation",
        "kendalls tau": "kendalls_tau",
        "kendall's tau": "kendalls_tau",
        "one-sample t-test": "one_sample_t_test",
        "welchs t-test": "welch_t_test",
        "welch's t-test": "welch_t_test",
        "students independent t-test": "students_t_test",
        "student's independent t-test": "students_t_test",
        "mann-whitney u test": "mann_whitney_u_test",
        "paired t-test": "paired_t_test",
        "wilcoxon signed-rank test": "wilcoxon_signed_rank_test",
        "one-way anova": "one_way_anova",
        "welch anova": "welch_anova",
        "kruskal-wallis test": "kruskal_wallis_test",
        "chi-square test of independence": "chi_square_test_of_independence",
        "fishers exact test": "fishers_exact_test",
        "fisher's exact test": "fishers_exact_test",
        "multiple linear regression": "multiple_linear_regression",
        "binary logistic regression": "binary_logistic_regression",
        "poisson regression": "poisson_regression",
        "negative-binomial regression": "negative_binomial_regression",
        "shapiro-wilk test": "shapiro_wilk_test",
        "mann-kendall trend test": "mann_kendall_trend_test",
        "sens slope": "sens_slope",
        "sen's slope": "sens_slope",
        "stl decomposition": "stl_decomposition",
    }

    methods: dict[str, dict] = {}

    # 1. Authored executable methods (Tier 1, executable).
    for e in EXECUTABLE:
        methods[e["method_id"]] = {
            "method_id": e["method_id"],
            "display_name": e["display_name"],
            "category": e["category"],
            "subcategory": e.get("subcategory"),
            "tier": 1,
            "summary": e["display_name"],
            "applicability_condition": "; ".join(e["selection_rules"]),
            "supported_intents": e["supported_intents"],
            "selection_rules": e["selection_rules"],
            "rejection_rules": e["rejection_rules"],
            "required_checks": e["required_checks"],
            "fallback_methods": e["fallback_methods"],
            "output_contract": e["output_contract"],
            "method_card": e["card"],
            "llm_guardrails": _GUARDRAILS,
            "executor_key": e["executor_key"],
            "dependencies": e["dependencies"],
            "is_executable": True,
        }

    # 2. Reference taxonomy — every remaining method as a draft (non-executable)
    #    catalog entry so the whole document is imported.
    for entry in taxonomy:
        if entry.get("category") in EXCLUDED_CATEGORIES:
            continue
        name = entry["method"].strip()
        if not name:
            continue
        norm = slugify(name).replace("_", " ")
        mapped = name_to_exec.get(norm)
        if mapped and mapped in methods:
            # already an executable method; enrich its applicability if present
            if entry.get("condition") and not methods[mapped].get("applicability_condition"):
                methods[mapped]["applicability_condition"] = entry["condition"]
            continue
        mid = slugify(name)
        if not mid or mid in methods or mid in exec_by_id:
            continue
        methods[mid] = {
            "method_id": mid,
            "display_name": name,
            "category": entry.get("category"),
            "subcategory": entry.get("subcategory"),
            "tier": classify_tier(name),
            "summary": name,
            "applicability_condition": entry.get("condition"),
            "supported_intents": [],
            "selection_rules": [],
            "rejection_rules": [],
            "required_checks": [],
            "fallback_methods": [],
            "output_contract": {},
            "method_card": {},
            "llm_guardrails": _GUARDRAILS,
            "executor_key": None,
            "dependencies": [],
            "is_executable": False,
        }

    method_list = sorted(methods.values(), key=lambda m: (m["tier"], m["method_id"]))

    return {
        "catalog_key": "tablescope_analytical_methods",
        "name": "Tablescope Analytical Method Reference Catalog",
        "description": (
            "Governed catalog of statistical/ML methods. The LLM explains "
            "results; Tablescope selects and executes the method."
        ),
        "source_document": "Tablescope Analytical Method Reference Catalog.rtf",
        "version": "1.0",
        "shared_policies": SHARED_POLICIES,
        "selection_matrix": [
            {
                "analysis_intent": intent,
                "data_profile": profile,
                "primary_method_id": primary,
                "alternative_method_ids": alts,
                "priority": 100 - i,
            }
            for i, (intent, profile, primary, alts) in enumerate(SELECTION_MATRIX)
        ],
        "methods": method_list,
    }


def main() -> None:
    catalog = build()
    OUTPUT.write_text(json.dumps(catalog, indent=2))
    tiers: dict[int, int] = {}
    execs = 0
    for m in catalog["methods"]:
        tiers[m["tier"]] = tiers.get(m["tier"], 0) + 1
        if m["is_executable"]:
            execs += 1
    print(f"Wrote {OUTPUT} — {len(catalog['methods'])} methods "
          f"(tier1={tiers.get(1,0)} tier2={tiers.get(2,0)} tier3={tiers.get(3,0)}), "
          f"{execs} executable, {len(catalog['selection_matrix'])} matrix rows, "
          f"{len(catalog['shared_policies'])} policies.")


if __name__ == "__main__":
    main()
