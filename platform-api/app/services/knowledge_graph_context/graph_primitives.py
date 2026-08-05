
from __future__ import annotations

import json
from typing import Any

from app.models.reference_library import (
    TIER_COMPANY,
    TIER_INDUSTRY,
    TIER_PROJECT,
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

# Edge types that mean a document/process/family references or defines a KPI.
_KPI_EDGE_TYPES = ("supports_kpi", "measures", "defines", "tracks", "monitors")
_REF_REL_BY_TIER = {
    TIER_PROJECT: "project_reference",
    TIER_COMPANY: "company_reference",
    TIER_INDUSTRY: "industry_standard",
}


def _norm(value: str | None) -> str:
    return "".join(
        ch if ch.isalnum() else "_" for ch in (value or "").lower()
    ).strip("_")


# Minimum length for a KPI phrase to be matched against query/dashboard text,
# so short/ambiguous tokens never create spurious "measured" relationships.
_KPI_PHRASE_MIN = 4


def _kpi_phrases(name: str | None, props: dict[str, Any]) -> set[str]:
    """Normalized phrases that identify a KPI in free text (name + aliases)."""
    phrases: set[str] = set()
    candidates = [name, props.get("display_name"), props.get("kpi_key")]
    aliases = props.get("aliases")
    if isinstance(aliases, list):
        candidates.extend(aliases)
    for raw in candidates:
        if not isinstance(raw, str):
            continue
        norm = _norm(raw)
        if len(norm) >= _KPI_PHRASE_MIN:
            phrases.add(norm)
    return phrases


def _haystack(*parts: Any) -> str:
    """Normalized concatenation of text/JSON parts for substring matching."""
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
    return _norm(" ".join(chunks))


def _phrase_in(phrases: set[str], haystack: str) -> bool:
    return any(p in haystack for p in phrases)


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
