
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnalyticalMethodDefinition:
    key: str
    display_name: str
    description: str
    category: str
    risk_level: str
    supports_fallback: bool
    fallback_method_keys: tuple[str, ...]
    default_enabled: bool
    requires_sql: bool
    experimental: bool = False
    # Heuristic patterns that map lower-level catalog method_ids / intents to
    # this governance key.  These are used when a component only knows the
    # statistical method selected by the Method Engine.
    catalog_method_patterns: tuple[str, ...] = ()
    intent_patterns: tuple[str, ...] = ()


METHOD_REGISTRY: tuple[AnalyticalMethodDefinition, ...] = (
    AnalyticalMethodDefinition(
        key="aggregation",
        display_name="Aggregation",
        description="Summarize values with counts, sums, averages, or other rollups.",
        category="descriptive",
        risk_level="low",
        supports_fallback=False,
        fallback_method_keys=(),
        default_enabled=True,
        requires_sql=True,
        catalog_method_patterns=("sum", "count", "mean", "average", "aggregation", "group_by"),
        intent_patterns=("describe_numeric", "compare_to_target", "total"),
    ),
    AnalyticalMethodDefinition(
        key="trend_analysis",
        display_name="Trend analysis",
        description="Identify direction and rate of change over ordered time.",
        category="diagnostic",
        risk_level="low",
        supports_fallback=True,
        fallback_method_keys=("aggregation", "distribution_analysis"),
        default_enabled=True,
        requires_sql=True,
        catalog_method_patterns=("trend", "slope", "mann_kendall", "sens"),
        intent_patterns=("detect_trend", "trend"),
    ),
    AnalyticalMethodDefinition(
        key="period_over_period_comparison",
        display_name="Period-over-period comparison",
        description="Compare a metric across two or more time periods.",
        category="comparative",
        risk_level="low",
        supports_fallback=True,
        fallback_method_keys=("trend_analysis", "aggregation"),
        default_enabled=True,
        requires_sql=True,
        catalog_method_patterns=("period", "yoy", "year_over_year", "pop"),
        intent_patterns=("compare", "period"),
    ),
    AnalyticalMethodDefinition(
        key="variance_analysis",
        display_name="Variance analysis",
        description="Measure and explain differences between groups or against a target.",
        category="comparative",
        risk_level="medium",
        supports_fallback=True,
        fallback_method_keys=("aggregation", "distribution_analysis"),
        default_enabled=True,
        requires_sql=True,
        catalog_method_patterns=("anova", "variance", "welch", "kruskal", "mann_whitney", "t_test"),
        intent_patterns=("compare_two_groups", "compare_multiple_groups", "compare_paired", "compare_to_target"),
    ),
    AnalyticalMethodDefinition(
        key="ranking",
        display_name="Ranking",
        description="Order entities by a metric and surface top or bottom performers.",
        category="descriptive",
        risk_level="low",
        supports_fallback=False,
        fallback_method_keys=(),
        default_enabled=True,
        requires_sql=True,
        catalog_method_patterns=("rank", "top", "bottom"),
        intent_patterns=("rank", "top", "bottom"),
    ),
    AnalyticalMethodDefinition(
        key="segmentation",
        display_name="Segmentation",
        description="Divide data into meaningful groups for comparison.",
        category="diagnostic",
        risk_level="low",
        supports_fallback=True,
        fallback_method_keys=("distribution_analysis", "aggregation"),
        default_enabled=True,
        requires_sql=True,
        catalog_method_patterns=("segment", "cluster", "group"),
        intent_patterns=("segment", "group_by", "breakdown"),
    ),
    AnalyticalMethodDefinition(
        key="anomaly_detection",
        display_name="Anomaly detection",
        description="Flag values or patterns that deviate markedly from the norm.",
        category="diagnostic",
        risk_level="medium",
        supports_fallback=True,
        fallback_method_keys=("distribution_analysis", "ranking"),
        default_enabled=True,
        requires_sql=True,
        catalog_method_patterns=("anomaly", "outlier", "iqr", "z_score"),
        intent_patterns=("anomaly", "outlier"),
    ),
    AnalyticalMethodDefinition(
        key="distribution_analysis",
        display_name="Distribution analysis",
        description="Describe the shape, spread, and frequency of values.",
        category="descriptive",
        risk_level="low",
        supports_fallback=False,
        fallback_method_keys=(),
        default_enabled=True,
        requires_sql=True,
        catalog_method_patterns=("distribution", "histogram", "normality", "shapiro", "anderson", "goodness"),
        intent_patterns=("normality", "distribution"),
    ),
    AnalyticalMethodDefinition(
        key="correlation_analysis",
        display_name="Correlation analysis",
        description="Measure statistical association between two or more variables.",
        category="diagnostic",
        risk_level="medium",
        supports_fallback=True,
        fallback_method_keys=("distribution_analysis", "aggregation"),
        default_enabled=True,
        requires_sql=True,
        catalog_method_patterns=("correlation", "pearson", "spearman", "kendall", "mutual_information"),
        intent_patterns=("relationship_numeric", "relationship_monotonic", "correlation"),
    ),
    AnalyticalMethodDefinition(
        key="forecast",
        display_name="Forecast",
        description="Project future values from historical patterns.",
        category="predictive",
        risk_level="high",
        supports_fallback=True,
        fallback_method_keys=("trend_analysis", "period_over_period_comparison"),
        default_enabled=True,
        requires_sql=True,
        experimental=True,
        catalog_method_patterns=("forecast", "arima", "prophet", "exponential_smoothing"),
        intent_patterns=("forecast", "predict"),
    ),
    AnalyticalMethodDefinition(
        key="document_synthesis",
        display_name="Document synthesis",
        description="Synthesize an answer from project or reference documents without executable SQL.",
        category="document",
        risk_level="low",
        supports_fallback=False,
        fallback_method_keys=(),
        default_enabled=True,
        requires_sql=False,
        catalog_method_patterns=(),
        intent_patterns=("document", "policy", "synthesis"),
    ),
    AnalyticalMethodDefinition(
        key="rule_based_detection",
        display_name="Rule-based detection",
        description="Identify records that violate a threshold, SLA, or status rule.",
        category="rule-based",
        risk_level="low",
        supports_fallback=False,
        fallback_method_keys=(),
        default_enabled=True,
        requires_sql=True,
        catalog_method_patterns=("threshold", "sla", "rule", "breach", "status"),
        intent_patterns=("rule", "threshold", "sla", "breach"),
    ),
    AnalyticalMethodDefinition(
        key="other",
        display_name="Other",
        description="An analytical approach not covered by the standard taxonomy.",
        category="other",
        risk_level="low",
        supports_fallback=False,
        fallback_method_keys=("aggregation",),
        default_enabled=True,
        requires_sql=False,
        catalog_method_patterns=(),
        intent_patterns=(),
    ),
)

_METHOD_BY_KEY: dict[str, AnalyticalMethodDefinition] = {m.key: m for m in METHOD_REGISTRY}

# Mapping from the built-in deterministic prompt types used by home intelligence.
_INSIGHT_TYPE_METHOD: dict[str, str] = {
    "risk_sla": "rule_based_detection",
    "risk_threshold": "rule_based_detection",
    "risk_expiry": "document_synthesis",
    "risk_upcoming": "trend_analysis",
    "trend_spend": "period_over_period_comparison",
    "trend_metric": "trend_analysis",
    "opportunity_supplier": "ranking",
    "opportunity_performance": "ranking",
    "opportunity_top_performer": "ranking",
}


def get_method_definition(key: str) -> AnalyticalMethodDefinition | None:
    return _METHOD_BY_KEY.get(key)


def get_method_label(key: str | None) -> str:
    return _METHOD_BY_KEY.get(key or "other", _METHOD_BY_KEY["other"]).display_name


def list_method_definitions() -> list[AnalyticalMethodDefinition]:
    return list(METHOD_REGISTRY)


def infer_governance_key(
    *,
    question: str | None = None,
    insight_type: str | None = None,
    chart_type: str | None = None,
    sql: str | None = None,
    documents: list[str] | None = None,
    category: str | None = None,
    method_id: str | None = None,
    analysis_intent: str | None = None,
) -> str:
    """Map available signals to a single governance method key."""
    q = (question or "").lower()
    if q:
        # Direct user phrasing takes precedence when the query is explicit.
        if "forecast" in q or "predict" in q:
            return "forecast"
        if re.search(r"\b(total|sum|average|mean|aggregat|amount)\b", q):
            return "aggregation"
        if re.search(r"\bcorrelat(?:e|ion)?\b", q):
            return "correlation_analysis"
        if re.search(r"\b(anomal(?:y|ies)|outlier(?:s)?)\b", q):
            return "anomaly_detection"
        if re.search(r"\b(?:variance|anova|t-test|significant difference)\b", q):
            return "variance_analysis"
        if re.search(r"\bsegment\b", q):
            return "segmentation"
        if re.search(r"\bcompare\b", q) and re.search(r"\bperiod|year|month|quarter\b", q):
            return "period_over_period_comparison"

    if method_id:
        mid = method_id.lower()
        for definition in METHOD_REGISTRY:
            for pattern in definition.catalog_method_patterns:
                if pattern in mid:
                    return definition.key

    if analysis_intent:
        intent = analysis_intent.lower()
        for definition in METHOD_REGISTRY:
            for pattern in definition.intent_patterns:
                if pattern in intent:
                    return definition.key

    if insight_type:
        exact = _INSIGHT_TYPE_METHOD.get(insight_type)
        if exact:
            return exact
        base = insight_type.split("_", 1)[0] if insight_type else ""
        if category == "relationship" or "relationship" in insight_type:
            return "correlation_analysis"
        if documents and not sql:
            return "document_synthesis"
        if chart_type in ("line", "area"):
            return "trend_analysis"
        if chart_type in ("bar", "radial_bar") and base == "opportunity":
            return "ranking"
        if chart_type == "bar" and (base == "risk" or "status" in insight_type):
            return "distribution_analysis"
        if chart_type == "kpi_grid" and base in ("trend", "spend"):
            return "period_over_period_comparison"
        if base == "risk":
            return "rule_based_detection"
        if base == "opportunity":
            return "ranking"
        if base == "trend":
            return "trend_analysis"

    if chart_type in ("line", "area"):
        return "trend_analysis"
    if chart_type in ("bar", "radial_bar"):
        return "ranking"
    if documents and not sql:
        return "document_synthesis"

    return "other"
