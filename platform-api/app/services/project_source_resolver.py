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

from __future__ import annotations

import difflib
import itertools
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.database_data_source import DatabaseDataSource
from app.models.file_source_meta import FileSourceMeta
from app.models.saved_query import SavedQuery

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

_STOPWORDS = {
    "the", "a", "an", "of", "for", "to", "and", "or", "in", "on", "by", "with",
    "what", "which", "how", "who", "are", "is", "was", "were", "has", "have",
    "had", "do", "does", "did", "my", "our", "their", "his", "her", "its",
    "this", "that", "these", "those", "each", "per", "based", "across", "over",
    "recent", "top", "highest", "lowest", "most", "least", "changed", "change",
    "show", "list", "give", "me", "all", "any", "from", "at", "as", "be",
    "using", "used", "vs", "versus", "into", "out", "up", "down", "many",
}

# Business-term synonym clusters. When a request term falls in a cluster, the
# whole cluster is used to look for a matching column — so "spend" matches an
# "Amount"/"Total" column and "defect rate" matches a "reject"/"quality" column.
# This is semantic *scoring* metadata (mirrors the Business Insight generators'
# keyword clusters), NOT a business-specific SQL template.
_SYNONYM_CLUSTERS: list[set[str]] = [
    {"spend", "amount", "cost", "total", "expense", "value", "price",
     "revenue", "budget", "sales", "spending"},
    {"defect", "defects", "reject", "rejects", "ncr", "nonconformance",
     "nonconform", "fail", "failure", "quality", "inspection", "inspections",
     "scrap"},
    {"delivery", "deliveries", "lead", "leadtime", "transit", "ship",
     "shipment", "shipments", "fulfillment", "ontime", "delay", "delays",
     "delayed", "late", "logistics"},
    {"supplier", "suppliers", "vendor", "vendors", "carrier", "carriers"},
    {"performance", "score", "scores", "rating", "ratings", "kpi", "metric"},
    {"contract", "contracts", "agreement", "agreements", "expiry", "expiration",
     "renewal", "document", "documents"},
    {"order", "orders", "purchase", "purchases", "po", "procurement"},
    {"customer", "customers", "client", "clients", "account", "accounts"},
    {"part", "parts", "product", "products", "item", "items", "sku"},
    {"period", "month", "months", "quarter", "quarterly", "week", "weekly",
     "date", "dates", "year", "yearly", "time"},
]

# Column-name fragments that mark an entity/dimension column (vs. a metric).
_ENTITY_HINTS = (
    "id", "name", "supplier", "vendor", "carrier", "customer", "client",
    "product", "part", "sku", "region", "country", "category", "code",
)


@dataclass
class ResolverCandidate:
    """One scored authorized source considered for a request."""

    source: str
    score: float
    matched_columns: list[str]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "score": round(self.score, 1),
            "matched_columns": self.matched_columns,
            "reason": self.reason,
        }


@dataclass
class ResolverResult:
    """Outcome of resolving a request onto authorized project sources."""

    status: str  # "resolved" | "no_match"
    preferred_sources: list[str] = field(default_factory=list)
    relevant_columns: list[str] = field(default_factory=list)
    intent: str = ""
    confidence: float = 0.0
    reason: str = ""
    candidates: list[ResolverCandidate] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "preferred_sources": self.preferred_sources,
            "relevant_columns": self.relevant_columns,
            "intent": self.intent,
            "confidence": round(self.confidence, 2),
            "reason": self.reason,
            "candidates": [c.to_dict() for c in self.candidates],
        }


@dataclass
class _Source:
    name: str
    columns: list[str]
    kind: str  # "table" | "db" | "query"
    description: str = ""


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    """Lowercase and strip everything but a-z0-9."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _tokens(text: str) -> list[str]:
    """Split into meaningful lowercase tokens (stopwords removed)."""
    raw = re.split(r"[^a-z0-9]+", (text or "").lower())
    return [t for t in raw if t and t not in _STOPWORDS and len(t) > 1]


def _request_terms(question: str, card_context: dict[str, Any] | None) -> set[str]:
    """Build the set of business terms to match against source columns.

    Includes single tokens, adjacent bigrams joined (so "defect rate" →
    "defectrate" matches a ``DefectRate`` column), any explicit ``metric`` from
    the card, and synonym-cluster expansion.
    """
    toks = _tokens(question)
    terms: set[str] = set(toks)
    for a, b in itertools.pairwise(toks):
        terms.add(a + b)
    if card_context:
        metric = card_context.get("metric")
        if isinstance(metric, str) and metric.strip():
            for t in _tokens(metric):
                terms.add(t)
            terms.add(_norm(metric))
    # Synonym expansion.
    expanded: set[str] = set(terms)
    for term in terms:
        for cluster in _SYNONYM_CLUSTERS:
            if term in cluster:
                expanded |= cluster
    return {t for t in expanded if t}


def _column_matches(term: str, col_norm: str) -> bool:
    """True when a request term plausibly refers to a column."""
    if not term or not col_norm:
        return False
    if term == col_norm:
        return True
    if len(term) >= 4 and (term in col_norm or col_norm in term):
        return True
    if (
        len(term) >= 4
        and len(col_norm) >= 4
        and difflib.SequenceMatcher(None, term, col_norm).ratio() >= 0.86
    ):
        return True
    return False


def _is_entity_column(col: str) -> bool:
    c = col.lower()
    return any(h in c for h in _ENTITY_HINTS)


# ---------------------------------------------------------------------------
# Source gathering (tenant + project scoped)
# ---------------------------------------------------------------------------

async def _gather_sources(
    session: AsyncSession, *, tenant_id: int, project_id: int
) -> list[_Source]:
    """Collect the project's authorized file + database sources with columns."""
    sources: list[_Source] = []

    files = (
        await session.scalars(
            select(FileSourceMeta).where(
                FileSourceMeta.tenant_id == tenant_id,
                FileSourceMeta.project_id == project_id,
                FileSourceMeta.archived.is_(False),
            )
        )
    ).all()
    for f in files:
        cols = [
            str(c.get("name"))
            for c in (f.column_types or [])
            if isinstance(c, dict) and c.get("name")
        ]
        description = ""
        if isinstance(f.ai_metadata, dict):
            description = str(f.ai_metadata.get("summary") or "")
        sources.append(
            _Source(name=f.view_name, columns=cols, kind="table",
                    description=description)
        )

    db_rows = (
        await session.scalars(
            select(DatabaseDataSource)
            .where(
                DatabaseDataSource.tenant_id == tenant_id,
                DatabaseDataSource.project_id == project_id,
                DatabaseDataSource.archived.is_(False),
            )
            .options(selectinload(DatabaseDataSource.columns))
        )
    ).all()
    for ds in db_rows:
        cols = [c.column_name for c in ds.columns if c.column_name]
        sources.append(
            _Source(name=ds.teiid_view_name, columns=cols, kind="db")
        )

    return sources


async def _saved_query_terms(
    session: AsyncSession, project_id: int
) -> set[str]:
    """Terms drawn from the project's saved query names/descriptions."""
    rows = (
        await session.scalars(
            select(SavedQuery).where(SavedQuery.project_id == project_id)
        )
    ).all()
    terms: set[str] = set()
    for q in rows:
        for t in _tokens(f"{q.name or ''} {q.description or ''}"):
            terms.add(t)
    return terms


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
