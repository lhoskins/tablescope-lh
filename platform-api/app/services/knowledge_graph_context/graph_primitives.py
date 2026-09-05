
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from sqlalchemy import ColumnElement, and_, or_

from app.models.reference_library import (
    TIER_COMPANY,
    TIER_INDUSTRY,
    TIER_PROJECT,
    ReferenceDocument,
)

# Caps keep the structural graph readable for very large projects.
_MAX_PER_KIND = 40

# Relationship labels for the project-hub → asset edges (shown on the canvas).
_REL_DOCUMENT = "documents"
_REL_DATA_SOURCE = "data_source"
_REL_QUERY = "query"
_REL_DASHBOARD = "dashboard"
_REL_QUERY_READS = "reads_from"
_REL_SUPPORTS_KPI = "supports_kpi"
# A recommended KPI keeps a (low-noise) link to the hub so it stays on the
# canvas, but the relationship is hidden by default — the FE only draws it when
# detailed/inferred relationships are enabled.
_REL_RECOMMENDED_KPI = "recommended_kpi"
# Measured KPIs are connected to the query/dashboard that depicts them.
_REL_QUERY_MEASURES = "measures"
_REL_DASHBOARD_VISUALIZES = "visualizes"
# KG-18: a dashboard widget's own stored ``dataSource.queryId`` binding,
# resolved to a direct edge -- distinct from ``_REL_DASHBOARD_VISUALIZES``,
# which is inferred from KPI phrase matching rather than a stored reference.
_REL_DASHBOARD_USES_QUERY = "uses_query"
# KG-16: a document's own chunk/passage-level evidence, so a claim can be
# traced to the specific passage that supports it instead of only "this
# document, somewhere."
_REL_HAS_PASSAGE = "has_passage"

# Edge types that mean a document/process/family references or defines a KPI.
_KPI_EDGE_TYPES = ("supports_kpi", "measures", "defines", "tracks", "monitors")
_REF_REL_BY_TIER = {
    TIER_PROJECT: "project_reference",
    TIER_COMPANY: "company_reference",
    TIER_INDUSTRY: "industry_standard",
}


def active_reference_document_conditions(
    tenant_id: int, project_id: int,
) -> list[ColumnElement[bool]]:
    """KG-20: the tier/status/supersession/expiration filter for a reference
    document currently authoritative for this tenant/project.

    Shared by ``collect_structural_graph`` (what's actually included in the
    graph) and the lifecycle fingerprint/watermark (what would make it
    stale) so the two can't silently diverge on which reference documents
    count -- a document that expires or gets superseded must both drop out
    of the graph *and* mark it stale, and a document that stays current must
    never be excluded from either.
    """
    return [
        ReferenceDocument.status == "active",
        # A document that has itself been superseded must never outrank the
        # version that replaced it, even if whatever created the newer
        # version forgot to flip this one's own status.
        ReferenceDocument.superseded_by_id.is_(None),
        # A version past its own expiration date is equally obsolete, even
        # with no successor recorded yet.
        or_(
            ReferenceDocument.expiration_date.is_(None),
            ReferenceDocument.expiration_date >= date.today(),
        ),
        or_(
            ReferenceDocument.tier == TIER_INDUSTRY,
            and_(
                ReferenceDocument.tier == TIER_COMPANY,
                ReferenceDocument.tenant_id == tenant_id,
            ),
            and_(
                ReferenceDocument.tier == TIER_PROJECT,
                ReferenceDocument.project_id == project_id,
            ),
        ),
    ]


def _norm(value: str | None) -> str:
    return "".join(
        ch if ch.isalnum() else "_" for ch in (value or "").lower()
    ).strip("_")


def _norm_words(value: str | None) -> str:
    """Like ``_norm``, but collapses non-alphanumeric runs to a single space
    instead of deleting them, so word boundaries survive punctuation (e.g.
    "On-time Delivery" -> "on time delivery", not "ontimedelivery"). Used for
    KPI phrase matching (KG-19) -- ``_norm`` itself stays untouched since
    other callers rely on its no-space form for exact-match graph keys."""
    collapsed = re.sub(r"[^a-z0-9]+", " ", (value or "").lower())
    return collapsed.strip()


# Minimum length for a KPI phrase to be matched against query/dashboard text,
# so short/ambiguous tokens never create spurious "measured" relationships.
_KPI_PHRASE_MIN = 4


def _kpi_phrases(name: str | None, props: dict[str, Any]) -> set[str]:
    """Word-boundary-safe phrases that identify a KPI in free text (name +
    aliases). Kept space-separated (not squashed like ``_norm``) so
    ``_phrase_in`` can require whole-word/whole-phrase matches -- KG-19: a
    KPI named "Rate" must not match inside unrelated text like "corporate"."""
    phrases: set[str] = set()
    candidates = [name, props.get("display_name"), props.get("kpi_key")]
    aliases = props.get("aliases")
    if isinstance(aliases, list):
        candidates.extend(aliases)
    for raw in candidates:
        if not isinstance(raw, str):
            continue
        norm = _norm_words(raw)
        if len(norm.replace(" ", "")) >= _KPI_PHRASE_MIN:
            phrases.add(norm)
    return phrases


def _haystack(*parts: Any) -> str:
    """Word-boundary-preserving concatenation of text/JSON parts for KPI
    phrase matching (see ``_phrase_in``)."""
    chunks: list[str] = []
    for part in parts:
        if part is None:
            continue
        if isinstance(part, (dict | list)):
            try:
                chunks.append(json.dumps(part, default=str))
            except (TypeError, ValueError):
                continue
        else:
            chunks.append(str(part))
    return _norm_words(" ".join(chunks))


def _phrase_in(phrases: set[str], haystack: str) -> bool:
    """Whole-word/whole-phrase containment, not raw substring containment
    (KG-19). Both ``phrases`` and ``haystack`` are space-separated word
    sequences (see ``_norm_words``); padding each with boundary spaces turns
    a plain substring check into one that only matches on word boundaries --
    a KPI phrase can never match as a fragment inside an unrelated word."""
    padded = f" {haystack} "
    return any(f" {p} " in padded for p in phrases)


def _node(
    node_id: str,
    node_type: str,
    name: str,
    *,
    source_type: str | None,
    source_id: int | None,
    properties: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": node_id,
        "node_type": node_type,
        "name": name,
        "source_type": source_type,
        "source_id": source_id,
        "properties": properties,
    }


def _edge(
    edge_id: str,
    from_id: Any,
    to_id: Any,
    relationship_type: str,
    summary: str,
    *,
    confidence: float = 1.0,
) -> dict[str, Any]:
    return {
        "id": edge_id,
        "from_node_id": from_id,
        "to_node_id": to_id,
        "relationship_type": relationship_type,
        "confidence": confidence,
        "evidence": {"evidence_summary": summary, "structural": True},
    }
