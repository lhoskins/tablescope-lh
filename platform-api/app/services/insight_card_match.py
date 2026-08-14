"""Match a conversational question to an existing precomputed insight card.

Ask Anything's fresh NL->SQL path (``_ask_and_run_core``) sometimes cannot
generate or execute a query for a question that an Insight Card already
answered in depth — the card's analysis ran the real multi-query, verified
pipeline; a single retry SQL guess is a downgrade, not an alternative. Rather
than falling straight to unattributed KG prose in that case, check whether an
already-computed card (business_insight_cache.py's ``BusinessInsightResult``
rows, plus the caller's own Project Insight snapshot) answers the same
question closely enough to point back to it.

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
import re
from dataclasses import dataclass
from statistics import mean
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.models import BusinessInsightResult
from app.services import ai_intelligence_client, insight_registry
from app.services.ai_intelligence_client import AIUnavailableError
from app.services.business_insight_project_resolver import _authorized_project_ids

logger = logging.getLogger(__name__)

# Bounds the prompt sent to the selector call, not the search itself -- a
# safety cap in case a widened search spans many projects' worth of cards,
# not a relevance cutoff. Cards beyond this count are simply never offered
# as candidates in that one call.
_MAX_CANDIDATES = 20

# The selector's own best-practices doc instructs it to decline (insight_id
# null, confidence 0.0) rather than force a tangential match -- but an LLM
# call is not guaranteed to follow that rule every time. A pick below this
# floor is treated as a decline here too, in code, the same defense-in-depth
# already applied to a hallucinated id: it costs nothing on a genuine match
# (the doc's own worked examples score 0.85-0.9), and it is what lets a
# resolved project's tangential candidate fall through to the cross-project
# widen instead of silently winning just because it was offered first.
_MIN_CONFIDENCE = 0.6


@dataclass
class InsightCardMatch:
    insight_id: str
    project_id: int
    project_name: str
    title: str
    summary: str
    chart: dict[str, Any] | None
    severity: str | None
    diagnostics: list[dict[str, Any]] | None = None
    proposed_actions: list[dict[str, Any]] | None = None
    score: float = 0.0


def _to_match(project_id: int, card: dict[str, Any], score: float = 0.0) -> InsightCardMatch:
    return InsightCardMatch(
        insight_id=str(card.get("insightId") or ""),
        project_id=project_id,
        project_name=str(card.get("projectName") or ""),
        title=str(card.get("title") or ""),
        summary=str(card.get("summary") or ""),
        chart=card.get("chart") if isinstance(card.get("chart"), dict) else None,
        severity=card.get("severity"),
        diagnostics=card.get("diagnostics") if isinstance(card.get("diagnostics"), list) else None,
        proposed_actions=card.get("proposedActions") if isinstance(card.get("proposedActions"), list) else None,
        score=score,
    )


# Stopwords for lightweight question/candidate token overlap.
_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "this", "that", "these", "those",
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her",
    "us", "them", "my", "your", "his", "its", "our", "their", "and", "or",
    "but", "if", "then", "of", "in", "on", "at", "to", "for", "with",
    "about", "by", "from", "as", "into", "through", "during", "before",
    "after", "above", "below", "between", "under", "again", "further",
    "why", "what", "which", "who", "when", "where", "how", "all", "any",
    "both", "each", "few", "more", "most", "other", "some", "such", "no",
    "not", "only", "own", "same", "so", "than", "too", "very", "just",
    "show", "tell", "give", "get", "see", "look", "find", "list",
}


_TREND_SYNONYMS = {
    "increasing": ["rising", "up", "growing", "higher", "climb"],
    "decreasing": ["falling", "down", "declining", "lower", "drop"],
    "stable": ["flat", "steady", "unchanged"],
}

# Generic measure words that appear across many unrelated series; matching on
# these alone (e.g. "cost") is not enough to say a card answers the subject.
_GENERIC_SUBJECT_TERMS = {
    "cost", "costs", "rate", "rates", "amount", "value", "values", "total",
    "count", "number", "time", "date", "id", "name", "job", "jobs",
    "system", "systems", "type", "types", "category", "categories", "item",
    "items", "status", "code", "level", "metric", "quantity", "qty",
    "score", "scores", "index", "percent", "percentage", "avg", "average",
    "min", "max", "sum", "data", "info",
}


def _extract_terms(text: str) -> set[str]:
    """Lowercased alphanumeric tokens with stopwords removed.

    Splits camelCase/PascalCase and snake_case so series like
    ``MaterialCosts`` or ``ScrapRate`` become ``material``, ``costs``,
    ``scrap``, ``rate``. Also includes a simple singular form for common
    plurals (``costs`` -> ``cost``) so questions and series labels match
    even when one uses the plural and the other does not.
    """
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    spaced = re.sub(r"_+", " ", spaced)
    tokens = set(re.findall(r"[a-z0-9]+", spaced.lower())) - _STOPWORDS
    singulars = {t[:-1] for t in tokens if len(t) > 3 and t.endswith("s")}
    return tokens | singulars


def _trend_word(value: float, threshold: float = 0.02) -> str:
    """Label a numeric direction as rising/falling/stable."""
    if value > threshold:
        return "rising"
    if value < -threshold:
        return "falling"
    return "stable"


def _series_trend(
    series: list[dict[str, Any]],
    key: str,
) -> tuple[str, str]:
    """Return (trend_word, note) for a numeric series.

    Trend is computed by comparing the mean of the first quarter of points to
    the mean of the last quarter; this is robust to noisy/seasonal data.
    """
    values: list[float] = []
    for point in series:
        if isinstance(point, dict):
            raw = point.get(key)
            if isinstance(raw, int | float):
                values.append(float(raw))
    if len(values) < 2:
        return "stable", "insufficient data"
    n = max(1, len(values) // 4)
    first = mean(values[:n])
    last = mean(values[-n:])
    if first == 0:
        delta = 0.0
    else:
        delta = (last - first) / abs(first)
    return _trend_word(delta, threshold=0.05), f"{delta:+.1%}"


def _chart_signature(card: dict[str, Any]) -> tuple[str, str, str]:
    """Build a concise data-shape signature for an insight card.

    Returns (chart_signature, series, trend) strings. These are fed to the
    LLM selector so it can judge from the actual chart data, not the title.
    """
    chart = card.get("chart") if isinstance(card.get("chart"), dict) else {}
    if not chart:
        return "", "", ""

    ctype = chart.get("type") or card.get("chartType") or "chart"
    title = chart.get("title") or ""
    roles = chart.get("roles") or {}
    series_labels = chart.get("seriesLabels") or {}
    x_label = roles.get("x") or series_labels.get("x") or ""
    y_label = roles.get("y") or series_labels.get("value") or ""
    y2_label = roles.get("y2") or series_labels.get("value2") or ""

    series = chart.get("data", {}).get("series", [])
    if not isinstance(series, list):
        series = []

    y1_trend, _ = _series_trend(series, "value")
    y2_trend, _ = _series_trend(series, "value2")

    signature_parts = [f"{ctype} chart"]
    if title:
        signature_parts.append(f"title={title}")
    if x_label:
        signature_parts.append(f"x={x_label}")
    if y_label:
        signature_parts.append(f"y={y_label}")
    if y2_label:
        signature_parts.append(f"y2={y2_label}")

    chart_signature = "; ".join(signature_parts)

    series_parts: list[str] = []
    trend_parts: list[str] = []
    if y_label:
        series_parts.append(y_label)
        trend_parts.append(f"{y_label} {y1_trend}")
    if y2_label:
        series_parts.append(y2_label)
        trend_parts.append(f"{y2_label} {y2_trend}")

    return chart_signature, ", ".join(series_parts), ", ".join(trend_parts)


def _question_trend_terms(question: str) -> set[str]:
    """Map trend words in the question to a normalized set."""
    terms = _extract_terms(question)
    expanded = set(terms)
    for term in list(terms):
        for direction, synonyms in _TREND_SYNONYMS.items():
            if term == direction or term in synonyms:
                expanded.update([direction, *synonyms])
    return expanded


def _question_subject_terms(question: str) -> set[str]:
    """Return the subject-specific (non-generic, non-direction) tokens."""
    q_terms = _extract_terms(question)
    direction_terms: set[str] = set()
    for direction, synonyms in _TREND_SYNONYMS.items():
        if direction in q_terms or any(s in q_terms for s in synonyms):
            direction_terms.add(direction)
            direction_terms.update(synonyms)
    return q_terms - direction_terms - _GENERIC_SUBJECT_TERMS


def _data_shape_score(question: str, card: dict[str, Any]) -> float:
    """Score a candidate by overlap between the question and chart data/summary.

    Title is deliberately not part of the score; the model must judge from the
    chart series, trend, and summary instead.
    """
    q_terms = _question_trend_terms(question)
    if not q_terms:
        return 0.0

    chart_signature, series, trend = _chart_signature(card)
    summary = str(card.get("summary") or "")
    haystack = " ".join([chart_signature, series, trend, summary]).lower()
    haystack_terms = _extract_terms(haystack)

    # Direct token overlap in series/trend/summary.
    overlap = len(q_terms & haystack_terms)
    score = float(overlap)

    # Bonus only when a series label contains a specific question subject.
    # Generic terms like "cost" or "rate" alone do not count as a subject match.
    subject_terms = _question_subject_terms(question)
    series_terms = _extract_terms(series)
    matching_subjects = subject_terms & series_terms
    has_subject_in_series = bool(subject_terms and matching_subjects)
    if has_subject_in_series:
        score += 2.0 + len(matching_subjects)

    # Trend-direction bonus only when the specific subject is also present.
    q_direction_terms: set[str] = set()
    for direction, synonyms in _TREND_SYNONYMS.items():
        if direction in q_terms or any(s in q_terms for s in synonyms):
            q_direction_terms.add(direction)
            q_direction_terms.update(synonyms)
    trend_terms = _extract_terms(trend)
    if has_subject_in_series and q_direction_terms and (q_direction_terms & trend_terms):
        score += 1.5

    return score


def _enriched_candidate(card: dict[str, Any]) -> dict[str, str]:
    """Candidate dict for the AI selector, including chart data shape."""
    chart_signature, series, trend = _chart_signature(card)
    return {
        "insight_id": str(card.get("insightId")),
        "title": str(card.get("title") or ""),
        "summary": str(card.get("summary") or ""),
        "chart_signature": chart_signature,
        "series": series,
        "trend": trend,
    }


async def _cards_for_projects(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_ids: list[int],
    user_id: int | None = None,
) -> list[tuple[int, dict[str, Any]]]:
    """Every (project_id, card) pair the caller could plausibly mean, across
    the given, already-scoped projects.

    Reads the shared Business Insight cache (``BusinessInsightResult``) plus,
    when ``user_id`` is known, each project's caller-specific Project Insight
    snapshot -- those risks/trends/opportunities/analysis cards are generated
    by a separate on-demand run and never land in the shared cache, so a card
    visible on a project's Insights page would otherwise never be offered to
    the selector. A snapshot card is skipped when its title already matches a
    cached card in the same project (the cache is authoritative there).
    """
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
    seen_titles_by_project: dict[int, set[str]] = {pid: set() for pid in project_ids}
    for row in rows:
        cards = (row.payload or {}).get("insights")
        if not isinstance(cards, list):
            continue
        for card in cards:
            if isinstance(card, dict) and card.get("insightId"):
                pairs.append((row.project_id, card))
                title = str(card.get("title") or "").strip().lower()
                if title:
                    seen_titles_by_project.setdefault(row.project_id, set()).add(
                        title
                    )

    if user_id is not None:
        for pid in project_ids:
            snapshot_cards = await insight_registry.load_project_insight_snapshot_cards(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                project_id=pid,
                exclude_titles=seen_titles_by_project.get(pid, set()),
                limit=_MAX_CANDIDATES,
            )
            pairs.extend((pid, card) for card in snapshot_cards)
    return pairs


def _ranked_pairs(
    question: str,
    pairs: list[tuple[int, dict[str, Any]]],
) -> list[tuple[float, int, dict[str, Any]]]:
    """Sort candidates by deterministic data-shape score descending."""
    scored = [
        (_data_shape_score(question, card), pid, card)
        for pid, card in pairs
    ]
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


async def _select_from_candidates(
    *,
    context: RequestContext,
    tenant_id: int,
    project_id: int,
    question: str,
    pairs: list[tuple[int, dict[str, Any]]],
    max_cards: int = 3,
    use_llm: bool = True,
) -> list[InsightCardMatch]:
    """Return the best matching insight card(s) for ``question``.

    When ``use_llm`` is true, the primary match is chosen by the LLM selector
    from the top data-shape candidates. Secondary matches are added from the same
    ranked list when their score is close to the primary's score. When
    ``use_llm`` is false, the function returns the top data-shape matches
    directly without an LLM call (used to cheaply suggest related cards
    alongside a successful live query result).
    """
    matches: list[InsightCardMatch] = []
    if not pairs:
        return matches

    # Order candidates by data-shape overlap so the LLM sees the strongest
    # chart/trend matches first, without relying on title.
    scored = _ranked_pairs(question, pairs)
    if not scored:
        return matches

    primary: InsightCardMatch | None = None
    decision: dict[str, Any] | None = None
    if use_llm and ai_intelligence_client.is_enabled():
        bounded = scored[:_MAX_CANDIDATES]
        candidates = [_enriched_candidate(card) for _score, _pid, card in bounded]

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
            decision = None

    chosen_id = (decision or {}).get("insight_id") if decision else None
    if chosen_id:
        try:
            confidence = float((decision or {}).get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < _MIN_CONFIDENCE:
            logger.info(
                "Insight-card selector picked %s below the confidence floor "
                "(%.2f < %.2f); treating as a decline",
                chosen_id, confidence, _MIN_CONFIDENCE,
            )
            chosen_id = None

    if chosen_id:
        for score, pid, card in scored:
            if str(card.get("insightId")) == chosen_id:
                primary = _to_match(pid, card, score=score)
                break
        if primary is None:
            logger.warning(
                "Insight-card selector returned an id not in the offered candidates: %s",
                chosen_id,
            )

    # If the LLM selector declined or returned an unknown id, fall back to the
    # deterministic top data-shape matches.
    if primary is None:
        top = scored[:max_cards]
        return [_to_match(pid, card, score=score) for score, pid, card in top if score > 0]

    matches.append(primary)

    # Add closely-related secondary cards: same data shape, within a fraction of
    # the primary score, and above a modest floor. This supports questions like
    # "Why are material costs increasing?" surfacing both the trend line and the
    # risk/combo card that explains the trend.
    primary_score = primary.score or 0.0
    if primary_score > 0:
        for score, pid, card in scored:
            if len(matches) >= max_cards:
                break
            if str(card.get("insightId")) == primary.insight_id:
                continue
            # Secondary must be genuinely related: score at least 75% of the
            # primary and above the raw floor. This prevents cross-project
            # filler-word matches from piggybacking on a strong primary.
            if score >= primary_score * 0.75 and score >= 1.5:
                matches.append(_to_match(pid, card, score=score))

    return matches


async def find_matching_insight_cards(
    session: AsyncSession,
    *,
    context: RequestContext,
    tenant_id: int,
    project_id: int,
    question: str,
    allow_cross_project: bool = True,
    max_cards: int = 3,
    use_llm: bool = True,
) -> list[InsightCardMatch]:
    """Best-matching cached insight cards the caller can reach.

    Tries the conversation's already-resolved project first; if nothing
    matches there and ``allow_cross_project`` is true, widens to every
    project ``context``'s user can access. Declines (empty list) whenever
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
        session,
        tenant_id=tenant_id,
        project_ids=[project_id],
        user_id=context.user_id,
    )
    pairs = list(resolved_pairs)

    if allow_cross_project:
        accessible = await _authorized_project_ids(session, context)
        other_ids = [pid for pid, _name in accessible if pid != project_id]
        if other_ids:
            other_pairs = await _cards_for_projects(
                session,
                tenant_id=tenant_id,
                project_ids=other_ids,
                user_id=context.user_id,
            )
            pairs.extend(other_pairs)

    return await _select_from_candidates(
        context=context,
        tenant_id=tenant_id,
        project_id=project_id,
        question=question,
        pairs=pairs,
        max_cards=max_cards,
        use_llm=use_llm,
    )


async def find_matching_insight_card(
    session: AsyncSession,
    *,
    context: RequestContext,
    tenant_id: int,
    project_id: int,
    question: str,
    allow_cross_project: bool = True,
) -> InsightCardMatch | None:
    """Single best-matching cached insight card; convenience wrapper."""
    matches = await find_matching_insight_cards(
        session,
        context=context,
        tenant_id=tenant_id,
        project_id=project_id,
        question=question,
        allow_cross_project=allow_cross_project,
        max_cards=1,
    )
    return matches[0] if matches else None
