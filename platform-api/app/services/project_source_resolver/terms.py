
from __future__ import annotations

import difflib
import itertools
import re
from typing import Any

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
