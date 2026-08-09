"""Match a conversational question to an existing precomputed insight card.

Ask Anything's fresh NL->SQL path (``_ask_and_run_core``) sometimes cannot
generate or execute a query for a question that an Insight Card already
answered in depth — the card's analysis ran the real multi-query, verified
pipeline; a single retry SQL guess is a downgrade, not an alternative. Rather
than falling straight to unattributed KG prose in that case, check whether an
already-computed card (business_insight_cache.py's ``BusinessInsightResult``
rows) answers the same question closely enough to point back to it.

Relevance judgment is LLM-driven, governed by
``insight_card_match_best_practices.md`` on the AI server (see
``/ai/intelligence/select-insight-card``) — the same convention every other
generation/classification decision in this codebase follows, rather than a
bespoke local heuristic. This module's own job is strictly the part that
must stay deterministic and server-side: resolving which cards the caller is
even authorized to see. It never sends a card the caller cannot access, and
the model never decides that scope — it only judges relevance among
candidates this module already vetted.

Checked in two passes. The conversation's already-resolved project is tried
first (the common, cheap case — one row lookup, one LLM call at most).
Project routing (``resolve_business_insight_project``, which scores by
data-source/column terms) and Insight Card generation (a separate,
independent pipeline) don't always agree on which project "owns" a topic, so
a card can legitimately exist under a different project than the one routing
picked for this question. If the resolved project has no match, widen the
search to every project the *asking user* can access — never further; this
mirrors the exact access-filtering ``resolve_business_insight_project``
already applies via ``_authorized_project_ids``, re-derived from ``context``
alone rather than trusted from anywhere else.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.models import BusinessInsightResult
from app.services import ai_intelligence_client
from app.services.ai_intelligence_client import AIUnavailableError
from app.services.business_insight_project_resolver import _authorized_project_ids

logger = logging.getLogger(__name__)

# Bounds the prompt sent to the selector call, not the search itself -- a
# safety cap in case a widened search spans many projects' worth of cards,
# not a relevance cutoff. Cards beyond this count are simply never offered
# as candidates in that one call.
_MAX_CANDIDATES = 40


@dataclass
class InsightCardMatch:
    insight_id: str
    project_id: int
    project_name: str
    title: str
    summary: str
    chart: dict[str, Any] | None
    severity: str | None


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


async def _cards_for_projects(
    session: AsyncSession, *, tenant_id: int, project_ids: list[int]
) -> list[tuple[int, dict[str, Any]]]:
    """Every (project_id, card) pair cached under the given, already-scoped
    projects. This is the only place that reads BusinessInsightResult for
    this feature -- the LLM selector never sees anything this didn't fetch."""
    if not project_ids:
        return []
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
    pairs: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        cards = (row.payload or {}).get("insights")
        if not isinstance(cards, list):
            continue
        for card in cards:
            if isinstance(card, dict) and card.get("insightId"):
                pairs.append((row.project_id, card))
    return pairs


async def _select_from_candidates(
    *,
    context: RequestContext,
    tenant_id: int,
    project_id: int,
    question: str,
    pairs: list[tuple[int, dict[str, Any]]],
) -> InsightCardMatch | None:
    if not pairs or not ai_intelligence_client.is_enabled():
        return None

    bounded = pairs[:_MAX_CANDIDATES]
    candidates = [
        {
            "insight_id": str(card.get("insightId")),
            "title": str(card.get("title") or ""),
            "summary": str(card.get("summary") or ""),
        }
        for _pid, card in bounded
    ]

    try:
        decision = await ai_intelligence_client.select_matching_insight_card(
            tenant_id=tenant_id,
            user_id=context.user_id,
            project_id=project_id,
            question=question,
            candidates=candidates,
        )
    except AIUnavailableError as exc:
        logger.warning("Insight-card match selector unavailable: %s", exc)
        return None

    chosen_id = (decision or {}).get("insight_id")
    if not chosen_id:
        return None
    for pid, card in bounded:
        if str(card.get("insightId")) == chosen_id:
            return _to_match(pid, card)
    # The model must only pick an id it was actually offered -- the ai-server
    # endpoint already enforces this, but never trust a second time whether
    # a returned id maps to a real candidate before using it.
    logger.warning(
        "Insight-card selector returned an id not in the offered candidates: %s",
        chosen_id,
    )
    return None


async def find_matching_insight_card(
    session: AsyncSession,
    *,
    context: RequestContext,
    tenant_id: int,
    project_id: int,
    question: str,
    allow_cross_project: bool = True,
) -> InsightCardMatch | None:
    """Best-matching cached insight card the caller can reach, or ``None``.

    Tries the conversation's already-resolved project first; if nothing
    matches there and ``allow_cross_project`` is true, widens to every
    project ``context``'s user can access. Declines (returns None) whenever
    the AI service is disabled/unavailable or the model finds no candidate
    genuinely on-topic -- never guesses.

    ``allow_cross_project`` reflects the calling surface, not a preference:
    the AI Assistant and Business Insights ask boxes are cross-project by
    design (a user with access to several projects should get an answer from
    whichever one actually has it), while Project Insights and a card's own
    follow-up box are explicitly scoped to one project -- widening there
    would surface another project's data under a page the user picked
    specifically to stay inside one project.
    """
    resolved_pairs = await _cards_for_projects(
        session, tenant_id=tenant_id, project_ids=[project_id]
    )
    match = await _select_from_candidates(
        context=context,
        tenant_id=tenant_id,
        project_id=project_id,
        question=question,
        pairs=resolved_pairs,
    )
    if match is not None or not allow_cross_project:
        return match

    accessible = await _authorized_project_ids(session, context)
    other_ids = [pid for pid, _name in accessible if pid != project_id]
    if not other_ids:
        return None
    other_pairs = await _cards_for_projects(
        session, tenant_id=tenant_id, project_ids=other_ids
    )
    return await _select_from_candidates(
        context=context,
        tenant_id=tenant_id,
        project_id=project_id,
        question=question,
        pairs=other_pairs,
    )
