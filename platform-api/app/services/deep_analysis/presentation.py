
from __future__ import annotations

from typing import Any

from .planning import DeepAnalysisSpec, Materiality

# ── How to show it ───────────────────────────────────────────────────────────

#: Chart family + analytical layers that render each intent's evidence. These
#: families are registered in the ECharts renderer and declared in
#: ``chart_selection_best_practices.md``.
EVIDENCE_PRESENTATION: dict[str, dict[str, Any]] = {
    "compare_periods": {"chart": "combo", "layers": ["reference_line"]},
    "compare_to_baseline": {"chart": "combo", "layers": ["reference_line"]},
    "continuous_prediction": {"chart": "bar", "layers": []},
    "compare_year_over_year": {"chart": "combo", "layers": ["reference_line"]},
    "measure_rate_of_change": {"chart": "line", "layers": ["reference_line"]},
    "detect_trend": {"chart": "line", "layers": ["regression_line"]},
    "trend_seasonality": {"chart": "line", "layers": []},
    "detect_anomalies": {"chart": "line", "layers": ["confidence_band", "anomaly_marker"]},
    "detect_change_point": {"chart": "line", "layers": ["change_point"]},
    "forecast_time_series": {"chart": "line", "layers": ["prediction_band"]},
    "contribution_to_change": {"chart": "bar", "layers": []},
    "relationship_numeric": {"chart": "scatter", "layers": ["regression_line"]},
    "relationship_monotonic": {"chart": "scatter", "layers": ["regression_line"]},
    "compare_multiple_groups": {"chart": "boxplot", "layers": []},
    "compare_two_groups": {"chart": "boxplot", "layers": []},
}


def spec_presentation(spec: DeepAnalysisSpec) -> dict[str, Any]:
    """Presentation for a planned analysis, honouring an explicit override."""
    base = evidence_presentation(spec.intent)
    if spec.presentation:
        return {"chart": spec.presentation, "layers": base.get("layers", [])}
    return base


def evidence_presentation(intent: str) -> dict[str, Any]:
    """Chart family + analytical layers for an intent's evidence.

    Falls back to a table so an uncatalogued intent degrades honestly rather
    than being force-fitted into a chart that misrepresents it.
    """
    return EVIDENCE_PRESENTATION.get(intent, {"chart": "table", "layers": []})


def card_summary(spec: DeepAnalysisSpec, materiality: Materiality, envelope: dict[str, Any]) -> str:
    """Business-language summary: the finding first, the method as provenance."""
    parts = [materiality.reason]
    n = envelope.get("usableN") or envelope.get("n")
    if n:
        parts.append(f"Based on {n} observations.")
    engine = str(envelope.get("executionEngine") or "").lower()
    method = envelope.get("method")
    if method:
        label = f"Method: {method}"
        if engine == "r":
            label += " (R)"
        parts.append(label + ".")
    return " ".join(p for p in parts if p)
