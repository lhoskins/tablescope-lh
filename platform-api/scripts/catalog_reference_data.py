"""Reference data for analytical catalog conversion."""

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
    ("compare_periods", "Time + numeric with periods", "period_change", []),
    ("compare_year_over_year", "Time + numeric with years", "period_change", []),
    ("compare_to_baseline", "Time + numeric with baseline", "period_change", []),
    ("measure_rate_of_change", "Time + numeric", "period_change", []),
    ("detect_change_point", "Ordered time with break", "detect_change_point", []),
    ("detect_anomalies", "Ordered time", "detect_anomalies", []),
    ("forecast_time_series", "Ordered time", "forecast_time_series", []),
    ("contribution_to_change", "Numeric + grouping + time", "contribution_to_change", []),
]


_GUARDRAILS = [
    "Do not choose the statistical method; explain the method Tablescope selected.",
    "Never invent statistical outputs; report only values present in the envelope.",
    "Do not use causal wording unless the method's causal gates pass.",
    "Always report effect size and confidence interval alongside any p-value.",
]


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


EXCLUDED_CATEGORIES = {
    "Recommended Tablescope Method-Selection Matrix",
    "Recommended Method-Selection Decision Factors",
    "Recommended Analytical Result Contract",
    "Recommended Implementation Tiers",
    "Recommended Architecture Principle",
}
