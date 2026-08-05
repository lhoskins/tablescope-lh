#!/usr/bin/env python3
"""Convert the Tablescope Analytical Method Reference Catalog into the structured
seed the Analytical Method Engine consumes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .analytical_methods_data import EXECUTABLE, EXECUTABLE_R
from .catalog_reference_data import (
    _GUARDRAILS,
    EXCLUDED_CATEGORIES,
    SELECTION_MATRIX,
    SHARED_POLICIES,
    TIER1_HINTS,
    TIER3_HINTS,
)

SEED_DIR = Path(__file__).resolve().parent.parent / "app" / "seed_data" / "analytical_methods"
SOURCE = SEED_DIR / "source_taxonomy.json"
OUTPUT = SEED_DIR / "catalog.json"


def slugify(name: str) -> str:
    s = name.lower()
    s = s.replace("\u2019", "").replace("'", "")
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def classify_tier(method: str) -> int:
    m = method.lower()
    for hint in TIER3_HINTS:
        if hint in m:
            return 3
    for hint in TIER1_HINTS:
        if hint in m:
            return 1
    return 2


def build() -> dict:
    taxonomy = json.loads(SOURCE.read_text())

    exec_by_id = {e["method_id"]: e for e in (*EXECUTABLE, *EXECUTABLE_R)}
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
        "period over period": "period_change",
        "period change": "period_change",
        "change point detection": "detect_change_point",
        "change point": "detect_change_point",
        "anomaly detection": "detect_anomalies",
        "anomalies": "detect_anomalies",
        "forecast": "forecast_time_series",
        "time series forecast": "forecast_time_series",
        "contribution to change": "contribution_to_change",
    }

    methods: dict[str, dict] = {}

    # 1. Authored executable methods (Tier 1, executable).
    for e in (*EXECUTABLE, *EXECUTABLE_R):
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
            "execution_engine": e.get("execution_engine", "r"),
            "result_schema_version": 1,
            "chart_contract": {},
            "max_rows": 10000,
            "timeout_seconds": 30,
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
        "version": "1.1",
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
