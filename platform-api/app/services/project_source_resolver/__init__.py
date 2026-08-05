
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .gather import _gather_sources, _saved_query_terms
from .scoring import _MIN_CANDIDATE_SCORE as _MIN_CANDIDATE_SCORE
from .scoring import _RESOLVE_SCORE as _RESOLVE_SCORE
from .scoring import _W_CARD_EVIDENCE as _W_CARD_EVIDENCE
from .scoring import _W_ENTITY_COLUMN as _W_ENTITY_COLUMN
from .scoring import _W_METADATA as _W_METADATA
from .scoring import _W_METRIC_COLUMN as _W_METRIC_COLUMN
from .scoring import _W_NO_COLUMNS as _W_NO_COLUMNS
from .scoring import _W_SOURCE_NAME as _W_SOURCE_NAME
from .scoring import _best_authorized_match, _classify, _score_source
from .terms import _ENTITY_HINTS as _ENTITY_HINTS
from .terms import _STOPWORDS as _STOPWORDS
from .terms import _SYNONYM_CLUSTERS as _SYNONYM_CLUSTERS
from .terms import _column_matches as _column_matches
from .terms import _is_entity_column as _is_entity_column
from .terms import _norm, _request_terms, _tokens
from .types import ResolverCandidate, ResolverResult
from .types import _Source as _Source

"""Project Semantic Source Resolver.

One shared, deterministic service that maps a natural-language request (a
question, a card investigation, a recommended query) onto the best authorized
project source(s) and the relevant columns *before* any AI SQL generation runs.

Every Project Insight AI action funnels through this resolver so a business
concept ("defect rate", "total spend", "late deliveries") is grounded in a real
authorized table/column rather than being re-inferred by the model on each
click. The resolver never emits SQL and never uses hard-coded business SQL
templates — it only scores authorized sources by their real columns, metadata,
and any card-supplied source context, and returns one of:

    resolved   — the highest-confidence authorized source (+ relevant columns).
                 When several sources score close together the top-ranked one is
                 chosen automatically; the user is never asked to pick.
    no_match   — nothing scored above the confidence floor, so the request
                 cannot be answered from an authorized source.

Supports both file (``FileSourceMeta``) and database (``DatabaseDataSource``)
sources, scoped to the caller's tenant + project so an unauthorized source can
never be selected.
"""


async def resolve_project_source(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
    question: str,
    intent: str = "question_answer",
    card_context: dict[str, Any] | None = None,
    kpi_names: list[str] | None = None,
) -> ResolverResult:
    """Resolve a request onto the best authorized project source(s).

    ``card_context`` may carry ``sourceTables``/``sourceColumns``/``metric``
    from a Business Insight or Project Insight card; when it names an authorized
    source the resolver prefers it directly (the card already grounded the
    finding in real data).
    """
    card_context = card_context or {}
    sources = await _gather_sources(
        session, tenant_id=tenant_id, project_id=project_id
    )
    if not sources:
        return ResolverResult(
            status="no_match",
            intent=intent,
            reason="This project has no authorized data sources.",
        )

    authorized_by_norm = {_norm(s.name): s for s in sources}

    # 1) Card-supplied source context: if the card names an authorized source,
    #    prefer it outright (deterministic, already grounded).
    card_sources = [
        str(s) for s in (card_context.get("sourceTables") or []) if str(s).strip()
    ]
    card_sources_norm = {_norm(s) for s in card_sources}
    matched_card_sources: list[str] = []
    for cs in card_sources:
        src = authorized_by_norm.get(_norm(cs))
        if src is None:
            # Suffix-insensitive / fuzzy fallback to an authorized source.
            best = _best_authorized_match(cs, sources)
            src = best
        if src is not None and src.name not in matched_card_sources:
            matched_card_sources.append(src.name)
    if matched_card_sources:
        card_cols = [
            str(c) for c in (card_context.get("sourceColumns") or []) if str(c)
        ]
        if not card_cols:
            # Fall back to the preferred source's own columns.
            first = authorized_by_norm.get(_norm(matched_card_sources[0]))
            card_cols = list(first.columns[:8]) if first else []
        return ResolverResult(
            status="resolved",
            preferred_sources=matched_card_sources,
            relevant_columns=card_cols,
            intent=intent,
            confidence=0.95,
            reason="Card supplied an authorized source for this finding.",
            candidates=[
                ResolverCandidate(
                    source=name, score=95.0, matched_columns=card_cols,
                    reason="card source evidence",
                )
                for name in matched_card_sources
            ],
        )

    # 2) Score every authorized source by the request evidence.
    terms = _request_terms(question, card_context)
    name_tokens = set(_tokens(question))
    if isinstance(card_context.get("metric"), str):
        name_tokens |= set(_tokens(card_context["metric"]))
    kpi_terms: set[str] = set()
    for kpi in kpi_names or []:
        for t in _tokens(kpi):
            kpi_terms.add(t)
    kpi_terms |= await _saved_query_terms(session, project_id)

    candidates = [
        _score_source(
            s,
            terms=terms,
            name_tokens=name_tokens,
            kpi_terms=kpi_terms,
            card_sources_norm=card_sources_norm,
        )
        for s in sources
    ]
    candidates.sort(key=lambda c: (-c.score, c.source))

    status, confidence = _classify(candidates)

    if status == "resolved":
        top = candidates[0]
        return ResolverResult(
            status="resolved",
            preferred_sources=[top.source],
            relevant_columns=top.matched_columns,
            intent=intent,
            confidence=confidence,
            reason=f"Best match: {top.reason}.",
            candidates=candidates[:5],
        )
    return ResolverResult(
        status="no_match",
        preferred_sources=[],
        relevant_columns=[],
        intent=intent,
        confidence=confidence,
        reason="No authorized source confidently matches this request.",
        candidates=candidates[:5],
    )
