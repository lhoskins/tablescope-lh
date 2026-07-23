"""Multi-entity intent detection and entity-name extraction.

Deterministic keyword-driven classifier that returns both the intent category
and any explicitly named business entities from the user question.
"""

from __future__ import annotations

import re
from typing import Any

_INTENT_KEYWORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(compare\s+.*(?:entities?|suppliers?|vendors?|customers?|clients?|plants?|products?|accounts?))\b", re.IGNORECASE), "compare_entities"),
    (re.compile(r"\b(compare\s+.*across\s+.*domains?|cross\s+domain|across\s+(?:spend|quality|delivery|revenue|support|renewal))\b", re.IGNORECASE), "compare_entities_across_domains"),
    (re.compile(r"\b(contribution\s+to\s+change|what\s+drove|driver\s+of\s+change|drove\s+the\s+change)\b", re.IGNORECASE), "entity_contribution_to_change"),
    (re.compile(r"\b(relationship\s+between|correlat|associat)\s+.*(?:entities?|suppliers?|customers?)\b", re.IGNORECASE), "cross_entity_relationship"),
    (re.compile(r"\b(trend\s+(?:for|across|of)|compare\s+trends)\s+.*(?:entities?|suppliers?|customers?|plants?)\b", re.IGNORECASE), "compare_entity_trends"),
]


def _split_entity_list(match_text: str) -> list[str]:
    """Split a captured comma/and list of entity names."""
    text = match_text.replace(" and ", ", ").replace(" or ", ", ")
    parts = [p.strip() for p in text.split(",") if p.strip()]
    return [re.sub(r"\s+", " ", p) for p in parts]


def extract_entity_names(question: str) -> list[str]:
    """Return the explicit named entities requested in the question."""
    q = question or ""
    names: list[str] = []
    # Capture lists after "Compare X, Y, and Z" or "X vs Y vs Z"
    for pat in [
        re.compile(
            r"compare\s+(?:our\s+|the\s+)?(.+?)(?:\s+(?:using|with|for|over|in|from|and|across|between)\s)",
            re.IGNORECASE,
        ),
        re.compile(r"compare\s+(.+)$", re.IGNORECASE),
    ]:
        m = pat.search(q)
        if m:
            names = _split_entity_list(m.group(1))
            break
    if not names:
        # Try "X vs Y vs Z" pattern
        vs = re.split(r"\s+(?:vs\.?|versus)\s+", q, flags=re.IGNORECASE)
        if len(vs) >= 2:
            names = [re.sub(r"\s+", " ", p.strip()) for p in vs if p.strip()]
    # Clean trailing prepositions
    return [re.sub(r"\s+(?:and|using|with|for|over|in|from|across|between)\s+.*$", "", n, flags=re.IGNORECASE).strip() for n in names]


def infer_multi_entity_intent(question: str, profile: dict[str, Any] | None = None) -> tuple[str | None, list[str]]:
    """Return (intent, entity_names)."""
    q = (question or "").lower()
    names = extract_entity_names(question)
    for pattern, intent in _INTENT_KEYWORDS:
        if pattern.search(q):
            return intent, names
    # Fallback: generic "compare" with 2+ names in the question.
    if "compare" in q and len(names) >= 2:
        return "compare_entities", names
    return None, names
