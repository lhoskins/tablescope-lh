
from __future__ import annotations

from typing import Any

from .canonicalization import EvidenceFingerprint
from .fingerprint_builders import fingerprint_for_card


def are_evidence_duplicates(a: EvidenceFingerprint, b: EvidenceFingerprint) -> bool:
    """Return True when two evidence fingerprints describe the same evidence."""
    if a.result_fingerprint and a.result_fingerprint == b.result_fingerprint:
        return True
    if a.series_fingerprint and a.series_fingerprint == b.series_fingerprint:
        return True
    # For document-only or failed-query cards, fall back to semantic fingerprint.
    if (
        a.semantic_fingerprint
        and a.semantic_fingerprint == b.semantic_fingerprint
        and not (a.result_fingerprint or b.result_fingerprint)
    ):
        return True
    return False


def merge_card_evidence(winner: dict[str, Any], duplicate: dict[str, Any]) -> dict[str, Any]:
    """Merge a duplicate card into the winner, preserving supporting evidence.

    The winner keeps its own chart and explanation; supporting source tables,
    documents, and provenance are unioned so nothing is lost.
    """
    winner.setdefault("sources", {"tables": [], "documents": []})
    dup_sources = duplicate.get("sources") or {"tables": [], "documents": []}
    winner["sources"]["tables"] = sorted(
        set(winner["sources"].get("tables", [])) | set(dup_sources.get("tables", []))
    )
    winner["sources"]["documents"] = sorted(
        set(winner["sources"].get("documents", [])) | set(dup_sources.get("documents", []))
    )
    # Preserve any additional provenance that helps explain the merged evidence.
    for key in ("referenceDocuments", "kpiReferences"):
        if duplicate.get(key):
            existing = winner.get(key) or []
            winner[key] = sorted(set(existing) | set(duplicate[key]))
    return winner


def select_duplicate_winner(
    candidates: list[dict[str, Any]],
    priority_fn=None,
) -> dict[str, Any]:
    """Select the representative card from a set of evidence duplicates.

    Higher-scoring cards win; when scores tie, the earliest candidate in the
    input list is kept so deduplication is stable and deterministic.
    """
    if not candidates:
        raise ValueError("empty duplicate group")

    def _score(card: dict[str, Any]) -> float:
        if priority_fn:
            return float(priority_fn(card))
        # Prefer: data-backed > document-backed, higher confidence, richer chart.
        score = 0.0
        if card.get("chart"):
            score += 10.0
        conf = card.get("confidenceScore") or card.get("confidenceEvaluation", {}).get("score")
        if isinstance(conf, int | float):
            score += conf
        # Prefer cards with SQL/provenance over bare summaries.
        if card.get("sql"):
            score += 1.0
        return score

    best = candidates[0]
    best_key = (_score(best), 0)
    for idx, cand in enumerate(candidates[1:], 1):
        key = (_score(cand), -idx)
        if key > best_key:
            best = cand
            best_key = key
    return best


def deduplicate_by_evidence(
    cards: list[dict[str, Any]],
    *,
    priority_fn=None,
) -> list[dict[str, Any]]:
    """Collapse cards that share canonical evidence, preserving the best one."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for card in cards:
        fp = fingerprint_for_card(card)
        key = fp.dedupe_key
        if not key:
            # Cannot fingerprint safely; pass through.
            groups.setdefault(f"passthrough-{id(card)}", []).append(card)
            continue
        groups.setdefault(key, []).append(card)

    winners: list[dict[str, Any]] = []
    for group in groups.values():
        winner = select_duplicate_winner(group, priority_fn=priority_fn)
        for dup in group:
            if dup is not winner:
                winner = merge_card_evidence(winner, dup)
        winners.append(winner)
    return winners
