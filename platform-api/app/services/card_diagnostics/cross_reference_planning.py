
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# ── Cross-referencing other sources and documents ────────────────────────────


@dataclass(frozen=True)
class CrossReference:
    """A corroborating source to check the finding against."""

    kind: str  # "table" | "document"
    name: str
    question: str
    rationale: str


def plan_cross_references(
    card: dict[str, Any],
    *,
    tables: list[str] | None = None,
    documents: list[dict[str, Any]] | None = None,
    max_refs: int = 4,
) -> list[CrossReference]:
    """Other sources worth checking the card's finding against.

    A finding measured in one table is a hypothesis until something else agrees.
    Documents matter as much as tables here: a board minute or monthly review
    often states the *reason* a metric moved, which no query can recover.
    """
    subject_terms = _subject_terms(card)
    own_tables = set()
    sources = card.get("sources") or {}
    if isinstance(sources, dict):
        own_tables = {str(t) for t in (sources.get("tables") or [])}

    refs: list[CrossReference] = []
    for table in tables or []:
        if str(table) in own_tables:
            continue  # already the card's own evidence
        if not subject_terms or _mentions(str(table), subject_terms):
            refs.append(
                CrossReference(
                    kind="table",
                    name=str(table),
                    question=f"Does {table!s} show the same pattern?",
                    rationale=(
                        "An independent table carrying the same measure either "
                        "corroborates the finding or narrows it to one source."
                    ),
                )
            )
        if len(refs) >= max_refs:
            return refs

    for doc in documents or []:
        title = str(doc.get("title") or doc.get("name") or "").strip()
        if not title:
            continue
        if not subject_terms or _mentions(title + " " + str(doc.get("summary") or ""), subject_terms):
            refs.append(
                CrossReference(
                    kind="document",
                    name=title,
                    question=f"Does {title} explain this finding?",
                    rationale=(
                        "Documents record decisions and causes — the explanation "
                        "behind a movement that the data alone cannot supply."
                    ),
                )
            )
        if len(refs) >= max_refs:
            break
    return refs[:max_refs]


def _subject_terms(card: dict[str, Any]) -> set[str]:
    text = " ".join(str(card.get(k) or "") for k in ("title", "summary", "metric"))
    words = re.findall(r"[a-z]{4,}", text.lower())
    stop = {"this", "that", "with", "from", "have", "than", "were", "where", "which", "insight"}
    return {w for w in words if w not in stop}


def _mentions(text: str, terms: set[str]) -> bool:
    lowered = str(text or "").lower()
    return any(t in lowered for t in terms)
