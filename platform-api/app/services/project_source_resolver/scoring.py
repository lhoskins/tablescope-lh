
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
SOURCE_RESOLUTION_MIN_SCORE = 40.0
_RESOLVE_SCORE = SOURCE_RESOLUTION_MIN_SCORE

# Weighted evidence contributions (see plan scoring model).
_W_METRIC_COLUMN = 40.0
_W_ENTITY_COLUMN = 30.0
_W_METADATA = 25.0
_W_SOURCE_NAME = 20.0
_W_STRONG_SOURCE_NAME = 55.0
_W_CARD_EVIDENCE = 55.0
_W_NO_COLUMNS = -30.0

# Technical/domain labels occur in many source names and cannot identify the
# subject by themselves. For example, every table in an IT project may start
# with ``IT_``; counting that token made an incidents table look relevant to a
# backup-jobs question merely because it also had the requested ``SiteID``
# grouping column.
_GENERIC_SOURCE_NAME_TERMS = {
    "it", "data", "dataset", "source", "table", "file", "csv", "tsv",
    "xls", "xlsx", "json", "parquet",
}


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

    # Source-name evidence. A distinctive subject named by the user is strong
    # evidence even when the requested grouping field/filter column is absent.
    # This keeps source selection topic-first: a dimension-only match in an
    # unrelated table must not outrank a source explicitly named by subject.
    src_tokens = set(_tokens(source.name)) - _GENERIC_SOURCE_NAME_TERMS
    request_name_tokens = name_tokens - _GENERIC_SOURCE_NAME_TERMS
    source_name_overlap = request_name_tokens & src_tokens
    strong_source_name = bool(
        len(source_name_overlap) >= 2
        or any(len(term) >= 6 for term in source_name_overlap)
    )
    if strong_source_name:
        score += _W_STRONG_SOURCE_NAME
        reasons.append("strong source-name subject match")
    elif source_name_overlap:
        score += _W_SOURCE_NAME
        reasons.append("source-name match")

    # Column evidence — normally the strongest signal, but a requested
    # grouping dimension alone cannot override a strong subject-name match.
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
    if not matched_columns and not strong_source_name:
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
