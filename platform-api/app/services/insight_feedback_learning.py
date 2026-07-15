"""Normalize stored human feedback into a learning-ready training record.

This module is intentionally isolated from the public feedback API: records are
meant for future model-evaluation and learning workflows, not for real-time
retraining or automatic behavior changes. Records contain no secrets, prompts,
chain-of-thought, or other-user feedback.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.models.insight_feedback import InsightFeedback

# Card keys that are safe to keep in a training record. Everything else is
# summarized or omitted so we never ship secrets, prompts, or hidden metadata.
_SAFE_CARD_KEYS = frozenset({
    "insightId",
    "id",
    "insightType",
    "severity",
    "title",
    "summary",
    "executedAt",
    "projectId",
    "projectName",
    "sql",
    "chartType",
    "labelColumn",
    "valueColumn",
    "valueColumn2",
    "sources",
    "chart",
})

# Explanation keys safe to export. We keep the factual method/evidence/assumption
# surface, not hidden prompts.
_SAFE_EXPLANATION_KEYS = frozenset({
    "summary",
    "method",
    "methodLabel",
    "steps",
    "source",
    "filters",
    "metrics",
    "comparison",
    "evidence",
    "sql",
    "chart",
    "assumptions",
    "limitations",
    "confidence",
    "generatedAt",
})


def _safe_card_snapshot(card: dict[str, Any] | None) -> dict[str, Any]:
    if not card:
        return {}
    return {k: v for k, v in card.items() if k in _SAFE_CARD_KEYS}


def _safe_explanation_snapshot(explanation: dict[str, Any] | None) -> dict[str, Any]:
    if not explanation:
        return {}
    return {k: v for k, v in explanation.items() if k in _SAFE_EXPLANATION_KEYS}


def build_feedback_training_record(feedback: InsightFeedback) -> dict[str, Any]:
    """Build a normalized, privacy-safe training record from one feedback row."""
    explanation = feedback.explanation_snapshot or {}
    card = _safe_card_snapshot(feedback.card_snapshot)
    safe_explanation = _safe_explanation_snapshot(explanation)

    confidence = explanation.get("confidence") or {}
    if isinstance(confidence, dict):
        confidence_level = confidence.get("level")
        confidence_basis = confidence.get("basis")
    else:
        confidence_level = None
        confidence_basis = None

    model_metadata = feedback.model_metadata or {}
    model_name = model_metadata.get("modelName") or model_metadata.get("model")
    model_version = model_metadata.get("modelVersion") or model_metadata.get("version")

    return {
        "record_type": "insight_feedback",
        "tenant_id": feedback.tenant_id,
        "user_id": feedback.user_id,
        "project_id": feedback.project_id,
        "insight_id": feedback.insight_id,
        "insight_type": feedback.insight_type,
        "sentiment": feedback.sentiment,
        "reason_codes": feedback.reason_codes or [],
        "comment": feedback.comment,
        "status": feedback.status,
        "insight_fingerprint": feedback.insight_fingerprint,
        "card": card,
        "explanation": safe_explanation,
        "method": explanation.get("method") or safe_explanation.get("method"),
        "method_label": explanation.get("methodLabel"),
        "confidence_level": confidence_level,
        "confidence_basis": confidence_basis,
        "model_name": model_name,
        "model_version": model_version,
        "card_summary": (feedback.card_snapshot or {}).get("summary"),
        "card_title": (feedback.card_snapshot or {}).get("title"),
        "feedback_timestamp": feedback.created_at.isoformat() if feedback.created_at else None,
        "exported_at": datetime.now(UTC).isoformat(),
        "privacy_safe": True,
    }
