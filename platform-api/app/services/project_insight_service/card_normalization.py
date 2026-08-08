from __future__ import annotations

from typing import Any

# Allowed severity values per card group (Package 3 unified schema).
_RISK_SEVERITIES = {"critical", "urgent", "warning", "watch"}
_TREND_SEVERITIES = {"watch", "warning", "informational"}
_OPPORTUNITY_SEVERITIES = {"opportunity", "recommendation"}

# A concrete, data-grounded question per built-in card type. Clicking a card
# opens the same AI Answer modal (Package 1) seeded with this question, so the
# investigation runs real SQL against the project's authorized sources.
_INVESTIGATION_QUESTIONS = {
    "risk_sla": (
        "Which suppliers have the highest average delivery lead times, and "
        "which exceed the SLA threshold?"
    ),
    "risk_threshold": (
        "Which records breach their target/threshold, or sit in a risk "
        "status, and how large is that share?"
    ),
    "risk_expiry": (
        "Which contracts or documents are expiring within the next 90 days?"
    ),
    "risk_upcoming": (
        "How many records are approaching an upcoming due/renewal/end date, "
        "and how soon?"
    ),
    "trend_spend": "How has total spend changed across recent periods?",
    "trend_metric": "How has this metric changed across recent periods?",
    "opportunity_supplier": (
        "Which suppliers have the highest performance scores?"
    ),
    "opportunity_performance": (
        "Which entities are the top and bottom performers on this metric, "
        "and how large is the gap?"
    ),
}


def _card_group(insight_type: str) -> str:
    """Map a built-in insight type onto risks / trends / opportunities / analysis.

    Anything that does not fit the three executive buckets lands in analysis
    (e.g. shape-template cards) so no generated card is silently dropped.
    """
    if insight_type.startswith("risk"):
        return "risks"
    if insight_type.startswith(("trend", "relationship")):
        return "trends"
    if insight_type.startswith("opportunity"):
        return "opportunities"
    return "analysis"


def _normalize_severity(severity: str, group: str) -> str:
    """Coerce a card's severity onto the allowed values for its group."""
    sev = (severity or "").strip().lower()
    if group == "risks":
        return sev if sev in _RISK_SEVERITIES else "watch"
    if group == "trends":
        if sev in ("urgent", "critical"):
            return "warning"
        return sev if sev in _TREND_SEVERITIES else "informational"
    if group == "analysis":
        return sev if sev in _TREND_SEVERITIES else "informational"
    return sev if sev in _OPPORTUNITY_SEVERITIES else "opportunity"


def _to_insight_card(card: dict[str, Any], group: str) -> dict[str, Any]:
    """Map a deterministic Business Insight card onto the unified card schema."""
    insight_type = str(card.get("insightType", ""))
    callout = card.get("callout")
    recommended_action = (
        str(callout.get("text", "")) if isinstance(callout, dict) else ""
    )
    sources = card.get("sources") or {}
    source_tables = [str(t) for t in (sources.get("tables") or [])]
    supporting = [
        *source_tables,
        *(str(d) for d in (sources.get("documents") or [])),
    ]
    ctx = card.get("sourceContext") or {}
    metric = str(ctx.get("metric") or "")
    period_column = str(ctx.get("periodColumn") or "")
    source_columns = [str(c) for c in (ctx.get("sourceColumns") or [])]
    # Prefer the stable server-generated insightId; legacy ids are a fallback.
    stable_id = str(card.get("insightId") or card.get("id") or "")
    return {
        "id": stable_id,
        "insightId": stable_id,
        "insightType": insight_type,
        "title": str(card.get("title", "")),
        "summary": str(card.get("summary", "")),
        "severity": _normalize_severity(str(card.get("severity", "")), group),
        "recommendedAction": recommended_action,
        "question": _INVESTIGATION_QUESTIONS.get(
            insight_type, str(card.get("title", ""))
        ),
        "supportingSources": supporting,
        "sourceTables": source_tables,
        "sourceColumns": source_columns,
        "metric": metric,
        "periodColumn": period_column,
        "sql": card.get("sql"),
        "chartType": card.get("chartType"),
        "labelColumn": card.get("labelColumn"),
        "valueColumn": card.get("valueColumn"),
        "valueColumn2": card.get("valueColumn2"),
        "chart": card.get("chart"),
        "explanation": card.get("explanation"),
        "executedAt": card.get("executedAt"),
        "evidenceFingerprint": card.get("evidenceFingerprint"),
        "confidenceScore": card.get("confidenceScore"),
        "confidenceEvaluation": card.get("confidenceEvaluation"),
        "visualizationDecision": card.get("visualizationDecision"),
        "chartCandidates": card.get("chartCandidates"),
        "analyticalMethod": card.get("analyticalMethod"),
        "insightMethod": card.get("insightMethod"),
    }


def _is_relationship_card(card: dict[str, Any]) -> bool:
    """A multi-table relationship analysis with two populated series."""
    if not str(card.get("insightType", "")).startswith("relationship"):
        return False
    if card.get("chartType") not in ("dual_line", "scatter"):
        return False
    return bool(card.get("valueColumn2"))
