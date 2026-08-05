
from __future__ import annotations

import difflib
import re

from .terms import _column_matches, _is_entity_column, _norm, _tokens
from .types import ResolverCandidate, _Source

# ---------------------------------------------------------------------------
# Resolution thresholds
# ---------------------------------------------------------------------------
# A source must score at least this to be considered a candidate at all.
_MIN_CANDIDATE_SCORE = 25.0
# The top candidate is accepted outright when it clears this score. When
# several sources clear it, the highest-scoring one is always chosen (the user
# is never asked to disambiguate).
_RESOLVE_SCORE = 40.0

# Weighted evidence contributions (see plan scoring model).
_W_METRIC_COLUMN = 40.0
_W_ENTITY_COLUMN = 30.0
_W_METADATA = 25.0
_W_SOURCE_NAME = 20.0
_W_CARD_EVIDENCE = 55.0
_W_NO_COLUMNS = -30.0


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_source(
    source: _Source,
    *,
    terms: set[str],
    name_tokens: set[str],
    kpi_terms: set[str],
    card_sources_norm: set[str],
) -> ResolverCandidate:
    """Score one authorized source against the request evidence."""
    score = 0.0
    reasons: list[str] = []
    matched_columns: list[str] = []

    # Column evidence — the strongest signal.
    metric_hit = False
    entity_hit = False
    for col in source.columns:
        col_norm = _norm(col)
        if any(_column_matches(term, col_norm) for term in terms):
            matched_columns.append(col)
            if _is_entity_column(col):
                entity_hit = True
            else:
                metric_hit = True
    if metric_hit:
        score += _W_METRIC_COLUMN
        reasons.append("relevant metric column")
    if entity_hit:
        score += _W_ENTITY_COLUMN
        reasons.append("entity column")
    if not matched_columns:
        score += _W_NO_COLUMNS

    # KPI / metadata evidence.
    desc_norm = _norm(source.description)
    if kpi_terms and any(k and k in desc_norm for k in kpi_terms):
        score += _W_METADATA
        reasons.append("KPI/metadata match")
    elif source.description and any(
        term in desc_norm for term in terms if len(term) >= 4
    ):
        score += _W_METADATA * 0.6
        reasons.append("description match")

    # Source-name evidence.
    src_tokens = set(_tokens(source.name))
    if name_tokens and (name_tokens & src_tokens):
        score += _W_SOURCE_NAME
        reasons.append("source-name match")

    # Business Insight / Project Insight card evidence (a card already knows the
    # exact authorized table its finding came from).
    if _norm(source.name) in card_sources_norm:
        score += _W_CARD_EVIDENCE
        reasons.append("card source evidence")

    reason = ", ".join(reasons) if reasons else "no strong evidence"
    return ResolverCandidate(
        source=source.name,
        score=score,
        matched_columns=matched_columns[:8],
        reason=reason,
    )


def _classify(
    candidates: list[ResolverCandidate],
) -> tuple[str, float]:
    """Decide resolved / no_match from ranked candidates.

    The highest-scoring candidate is always chosen when it clears the confidence
    floor — several close scores never produce an "ambiguous" outcome, because
    the user is never asked to pick a source. If nothing clears the floor the
    request is ``no_match`` (it cannot be answered from an authorized source).
    """
    viable = [c for c in candidates if c.score >= _MIN_CANDIDATE_SCORE]
    if not viable:
        return "no_match", 0.0
    top = viable[0]
    confidence = max(0.0, min(1.0, top.score / 100.0))
    if top.score < _RESOLVE_SCORE:
        return "no_match", confidence
    return "resolved", confidence


def _best_authorized_match(name: str, sources: list[_Source]) -> _Source | None:
    """Suffix-insensitive / fuzzy match of a name onto an authorized source."""
    target = _norm(re.sub(r"(_csv|_xlsx|_xls|_json|_parquet|_tsv)$", "",
                          name.lower()))
    best: _Source | None = None
    best_ratio = 0.0
    for s in sources:
        cand = _norm(re.sub(r"(_csv|_xlsx|_xls|_json|_parquet|_tsv)$", "",
                            s.name.lower()))
        if not cand or not target:
            continue
        if cand == target:
            return s
        ratio = difflib.SequenceMatcher(None, target, cand).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best = s
    return best if best_ratio >= 0.8 else None
