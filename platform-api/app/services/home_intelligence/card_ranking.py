from __future__ import annotations

from typing import Any

from app.services.insight_evidence_fingerprint import (
    build_plan_fingerprint,
    deduplicate_by_evidence,
    fingerprint_for_card,
)

# ─────────────────────────────────────────────────────────────────────────────
# Severity calibration, ranking & dedup
# ─────────────────────────────────────────────────────────────────────────────

# Severity values the Home UI renders (an unknown value falls back to "info"
# client-side, but we normalise here so cards stay calibrated).
_ALLOWED_SEVERITIES = (
    "critical", "urgent", "warning", "watch", "opportunity", "info",
)
_SEVERITY_RANK = {
    "critical": 6, "urgent": 5, "warning": 4, "watch": 3,
    "opportunity": 3, "info": 1,
}


def _normalize_severity(value: Any) -> str:
    v = str(value or "").strip().lower()
    return v if v in _ALLOWED_SEVERITIES else "info"


def _card_priority(card: dict[str, Any]) -> float:
    """Score a card for ranking: severity first, then evidence strength."""
    score = _SEVERITY_RANK.get(card.get("severity", "info"), 1) * 10.0
    conf = card.get("confidenceScore")
    score += (float(conf) if isinstance(conf, int | float) else 0.5) * 3.0
    if card.get("chart"):
        score += 1.0
    if card.get("kpiReferences") or card.get("referenceDocuments"):
        score += 2.0
    if card.get("relationshipMetadata"):
        # Evidence-backed cross-table findings are the scarcest signal class;
        # weight them so they rank alongside same-severity single-table cards
        # rather than at the bottom of the page.
        score += 2.5
    pri = card.get("priorityScore")
    if isinstance(pri, int | float) and pri > 0:
        return float(pri)
    return score


def _dedupe_key(card: dict[str, Any]) -> str | None:
    """Return the canonical evidence fingerprint key for a card, if available."""
    fp = fingerprint_for_card(card)
    return fp.dedupe_key


def _pre_execution_dedupe(
    analyses: list[dict[str, Any]],
    *,
    project_id: int,
    tenant_id: int,
    tables: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Collapse planned analyses with identical intent + source scope before SQL.

    The plan LLM may rephrase the same analytical question twice; a plan
    fingerprint catches identical SQL/columns/label/value pairs even when the
    title or rationale differs.
    """
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for a in analyses:
        fp = build_plan_fingerprint(
            project_id=project_id,
            tenant_id=tenant_id,
            analysis=a,
            tables=tables,
            method_id=a.get("method"),
            source_columns=a.get("sourceColumns"),
        )
        if fp in seen:
            continue
        seen.add(fp)
        a["planFingerprint"] = fp
        unique.append(a)
    return unique


def rank_and_dedupe_cards(
    cards: list[dict[str, Any]], *, max_cards: int = 8
) -> list[dict[str, Any]]:
    """Return the strongest, de-duplicated cards (best-practices §Insight
    Selection / §Card Ranking). Duplicates that share canonical evidence
    (result set, series, or semantic interpretation) are collapsed to the
    highest-scoring one, regardless of title wording.

    Multi-table (relationship-evidence) cards are exempt from the cap: they
    are the rarest, highest-effort findings, so every one that executed and
    passed the quality gates is surfaced. Only single-table cards compete for
    the ``max_cards`` slots.
    """
    unique = deduplicate_by_evidence(cards, priority_fn=_card_priority)

    def _is_multi(c: dict[str, Any]) -> bool:
        return len(c.get("sources", {}).get("tables", [])) >= 2

    multi = [c for c in unique if _is_multi(c)]
    single = [c for c in unique if not _is_multi(c)]
    return sorted(multi + single[:max_cards], key=_card_priority, reverse=True)
