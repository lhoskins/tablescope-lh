"""Match a conversational question to an existing precomputed insight card.

Ask Anything's fresh NL->SQL path (``_ask_and_run_core``) sometimes cannot
generate or execute a query for a question that an Insight Card already
answered in depth — the card's analysis ran the real multi-query, verified
pipeline; a single retry SQL guess is a downgrade, not an alternative. Rather
than falling straight to unattributed KG prose in that case, check whether an
already-computed card (business_insight_cache.py's ``BusinessInsightResult``
rows) answers the same question closely enough to point back to it.

Deliberately cheap and deterministic: lexical term overlap between the
question and each card's title/summary, over cards already sitting in the
database. No LLM call, no new query — this only ever runs after a SQL
generation/execution failure, so it adds no latency to the common path.

Checked in two passes. The conversation's already-resolved project is tried
first (the common, cheap case — one row lookup). Project routing
(``resolve_business_insight_project``, which scores by data-source/column
terms) and Insight Card generation (a separate, independent pipeline) don't
always agree on which project "owns" a topic, so a card can legitimately
exist under a different project than the one routing picked for this
question. If the resolved project has no match, widen the search to every
project the *asking user* can access — never further; this mirrors the exact
access-filtering ``resolve_business_insight_project`` already applies via
``_authorized_project_ids``, re-derived from ``context`` alone rather than
trusted from anywhere else.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.models import BusinessInsightResult
from app.services.business_insight_project_resolver import _authorized_project_ids

# A minimum score is required so an unrelated card with one incidental shared
# word (e.g. both mention "project") never gets surfaced as a false match.
_MIN_SCORE = 0.34

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "have", "how", "in", "increasing", "is", "it", "of", "on", "or", "our",
    "rising", "than", "that", "the", "this", "to", "was", "we", "what",
    "when", "where", "which", "who", "why", "will", "with", "you", "your",
}

_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass
class InsightCardMatch:
    insight_id: str
    project_id: int
    project_name: str
    title: str
    summary: str
    chart: dict[str, Any] | None
    severity: str | None


def _terms(text: str) -> set[str]:
    words = _WORD_RE.findall(text.lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def _score(question_terms: set[str], card: dict[str, Any]) -> float:
    haystack = f"{card.get('title', '')} {card.get('summary', '')}"
    card_terms = _terms(haystack)
    if not question_terms or not card_terms:
        return 0.0
    overlap = question_terms & card_terms
    return len(overlap) / len(question_terms)


def _to_match(project_id: int, card: dict[str, Any]) -> InsightCardMatch:
    return InsightCardMatch(
        insight_id=str(card.get("insightId") or ""),
        project_id=project_id,
        project_name=str(card.get("projectName") or ""),
        title=str(card.get("title") or ""),
        summary=str(card.get("summary") or ""),
        chart=card.get("chart") if isinstance(card.get("chart"), dict) else None,
        severity=card.get("severity"),
    )


async def _best_match_in_projects(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_ids: list[int],
    question_terms: set[str],
    min_score: float,
) -> InsightCardMatch | None:
    if not project_ids:
        return None

    rows = (
        (
            await session.execute(
                select(BusinessInsightResult).where(
                    BusinessInsightResult.tenant_id == tenant_id,
                    BusinessInsightResult.project_id.in_(project_ids),
                )
            )
        )
        .scalars()
        .all()
    )

    best_score = 0.0
    best_card: dict[str, Any] | None = None
    best_project_id: int | None = None
    for row in rows:
        cards = (row.payload or {}).get("insights")
        if not isinstance(cards, list):
            continue
        for card in cards:
            if not isinstance(card, dict) or not card.get("insightId"):
                continue
            score = _score(question_terms, card)
            if score > best_score:
                best_score = score
                best_card = card
                best_project_id = row.project_id

    if best_card is None or best_project_id is None or best_score < min_score:
        return None
    return _to_match(best_project_id, best_card)


async def find_matching_insight_card(
    session: AsyncSession,
    *,
    context: RequestContext,
    tenant_id: int,
    project_id: int,
    question: str,
    min_score: float = _MIN_SCORE,
) -> InsightCardMatch | None:
    """Best-scoring cached insight card the caller can reach, or ``None``.

    Tries the conversation's already-resolved project first; if nothing
    matches there, widens to every project ``context``'s user can access.
    """
    question_terms = _terms(question)
    if not question_terms:
        return None

    match = await _best_match_in_projects(
        session,
        tenant_id=tenant_id,
        project_ids=[project_id],
        question_terms=question_terms,
        min_score=min_score,
    )
    if match is not None:
        return match

    accessible = await _authorized_project_ids(session, context)
    other_ids = [pid for pid, _name in accessible if pid != project_id]
    if not other_ids:
        return None
    return await _best_match_in_projects(
        session,
        tenant_id=tenant_id,
        project_ids=other_ids,
        question_terms=question_terms,
        min_score=min_score,
    )
