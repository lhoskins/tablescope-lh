"""Knowledge graph insight card/gap generation."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from .constants import (
    _ACTION_TYPES,
    _CARD_CATEGORY_BY_TYPE,
    _SEVERITY_RANK,
    MAX_CARDS,
)

logger = logging.getLogger(__name__)

def _connected(
    node_id: Any, edges: list[dict[str, Any]], nodes_by_id: dict[Any, dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Return (neighbor_node, edge) pairs for a node id."""
    out: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for e in edges:
        other_id: Any | None = None
        if e["from_node_id"] == node_id:
            other_id = e["to_node_id"]
        elif e["to_node_id"] == node_id:
            other_id = e["from_node_id"]
        if other_id is None:
            continue
        other = nodes_by_id.get(other_id)
        if other is not None:
            out.append((other, e))
    return out


def _bucket_sources(
    neighbors: list[tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, list[str]]:
    sources: dict[str, list[str]] = {
        "documents": [], "tables": [], "queries": [], "dashboards": [], "kpis": [],
    }
    for other, _edge in neighbors:
        t = other["type"]
        label = other["label"]
        if t in ("document", "reference_document", "policy", "procedure", "standard", "document_family"):
            sources["documents"].append(label)
        elif t in ("data_source", "datasource", "table"):
            sources["tables"].append(label)
        elif t in ("query", "saved_query"):
            sources["queries"].append(label)
        elif t == "dashboard":
            sources["dashboards"].append(label)
        elif t in ("kpi", "metric"):
            sources["kpis"].append(label)
    for k in sources:
        sources[k] = _dedupe(sources[k])
    return sources


def _dedupe(items: list[str]) -> list[str]:
    """Stable de-duplication preserving first-seen order."""
    seen: set[str] = set()
    result: list[str] = []
    for x in items:
        if x not in seen:
            seen.add(x)
            result.append(x)
    return result


def _hops(
    neighbors: list[tuple[dict[str, Any], dict[str, Any]]],
) -> list[dict[str, Any]]:
    """KG-34: an ordered, direction-aware hop per evidence edge, so a trace
    path is a real walk (edge direction + relationship meaning per hop),
    not only a flat list of evidence node ids. Built directly from the
    real edges gathered for this card -- never invented -- in the same
    order the evidence itself was gathered, so a UI can render/verify
    each hop from the finding to its source.
    """
    return [
        {
            "fromNodeId": e["from_node_id"],
            "toNodeId": e["to_node_id"],
            "relationshipType": e.get("relationship_type") or "",
        }
        for _other, e in neighbors
    ]


def _evidence_has_expired_reference(
    evidence_neighbors: list[tuple[dict[str, Any], dict[str, Any]]],
) -> bool:
    """KG-29: true if any evidence neighbor is a reference document whose
    own ``expiration_date`` has passed.

    A freshly-built graph already excludes an expired reference document
    from the *active* set (KG-20, ``active_reference_document_conditions``)
    -- but a card built and cached before that document expired keeps
    citing it as evidence until the project's next rebuild, with nothing
    marking the citation stale in between. Re-checking the document's own
    date here, at card-render time, catches exactly that window.
    """
    today = date.today().isoformat()
    for other, _e in evidence_neighbors:
        if other.get("type") != "reference_document":
            continue
        expiration = (other.get("properties") or {}).get("expiration_date")
        if expiration and str(expiration) < today:
            return True
    return False


def _build_card_for_node(
    node: dict[str, Any],
    edges: list[dict[str, Any]],
    nodes_by_id: dict[Any, dict[str, Any]],
) -> dict[str, Any] | None:
    """Derive a Knowledge Graph insight card from an insight/finding node.

    Returns ``None`` when the node has no evidence connections (cards must trace
    to evidence — never fabricated).
    """
    neighbors = _connected(node["id"], edges, nodes_by_id)
    evidence_neighbors = [
        (other, e) for other, e in neighbors
        if other["layer"] in ("evidence", "kpi", "semantic")
    ]
    if not evidence_neighbors:
        return None

    props = node["properties"]
    category = _CARD_CATEGORY_BY_TYPE.get(node["type"], "business_insight")
    sources = _bucket_sources(evidence_neighbors)

    # Recommended action: a connected action/recommendation node or an explicit
    # property; never invented.
    recommended = str(props.get("recommended_action") or "")
    for other, _e in neighbors:
        if other["type"] in _ACTION_TYPES and other["label"]:
            recommended = other["label"]
            break

    evidence_node_ids = [node["id"], *[o["id"] for o, _e in evidence_neighbors]]
    evidence_edge_ids = [e["id"] for _o, e in evidence_neighbors]
    evidence_path = [nodes_by_id[i]["graphKey"] for i in evidence_node_ids if i in nodes_by_id]

    summary = node["summary"] or node["label"]
    return {
        "id": f"kgcard:{node['graphKey']}",
        "nodeKey": node["graphKey"],
        "category": category,
        "severity": node["severity"],
        "title": node["label"],
        "summary": summary,
        "businessQuestion": node["businessQuestion"],
        "businessImpact": node["businessValue"],
        "confidence": node["confidence"] if node["confidence"] is not None else 0.0,
        "evidencePath": evidence_path,
        "sourceDocuments": sources["documents"],
        "sourceTables": sources["tables"],
        "sourceQueries": sources["queries"],
        "sourceDashboards": sources["dashboards"],
        "supportedKpis": sources["kpis"],
        "recommendedAction": recommended,
        # KG-29: surfaces when this card's evidence includes a reference
        # document past its own expiration_date -- an insight must not be
        # presented as currently justified by guidance that has expired.
        "evidenceExpired": _evidence_has_expired_reference(evidence_neighbors),
        "traceToEvidence": {
            "nodeIds": evidence_node_ids,
            "edgeIds": evidence_edge_ids,
            "nodeKeys": evidence_path,
            "hops": _hops(evidence_neighbors),
        },
    }


def _gap_is_supported(
    node: dict[str, Any],
    neighbors: list[tuple[dict[str, Any], dict[str, Any]]],
) -> bool:
    """A gap is only valid with an authoritative source backing it."""
    if str(node["properties"].get("authoritative_source") or "").strip():
        return True
    for other, _e in neighbors:
        if other["type"] in (
            "reference_document", "policy", "procedure", "standard",
            "document", "document_family",
        ):
            return True
    return False


def _build_gap_finding(
    node: dict[str, Any],
    edges: list[dict[str, Any]],
    nodes_by_id: dict[Any, dict[str, Any]],
) -> dict[str, Any] | None:
    neighbors = _connected(node["id"], edges, nodes_by_id)
    if not _gap_is_supported(node, neighbors):
        return None
    props = node["properties"]
    authoritative = str(props.get("authoritative_source") or "")
    if not authoritative:
        for other, _e in neighbors:
            if other["type"] in ("reference_document", "policy", "procedure", "standard"):
                authoritative = other["label"]
                break
    affected_processes = [o["label"] for o, _e in neighbors if o["type"] == "process"]
    affected_kpis = [o["label"] for o, _e in neighbors if o["type"] in ("kpi", "metric")]
    recommended = str(props.get("recommended_action") or "")
    for other, _e in neighbors:
        if other["type"] in _ACTION_TYPES and other["label"]:
            recommended = other["label"]
            break
    return {
        "id": f"gap:{node['graphKey']}",
        "nodeKey": node["graphKey"],
        "gapType": str(props.get("gap_type") or node["type"]),
        "title": node["label"],
        "severity": node["severity"],
        "whyItMatters": str(props.get("why_it_matters") or node["summary"]),
        "authoritativeSource": authoritative,
        "expectedEvidence": str(props.get("expected_evidence") or ""),
        "missingOrWeakComponent": str(props.get("missing_or_weak_component") or node["label"]),
        "affectedProcesses": affected_processes,
        "affectedKpis": affected_kpis,
        "recommendedAction": recommended,
        "confidence": node["confidence"] if node["confidence"] is not None else 0.0,
    }


def _card_priority(card: dict[str, Any]) -> float:
    sev = _SEVERITY_RANK.get(card.get("severity", "info"), 1)
    conf = float(card.get("confidence") or 0.0)
    return sev * 10 + conf * 3


def _rank_and_dedupe_cards(
    cards: list[dict[str, Any]], *, max_cards: int = MAX_CARDS,
) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    unique: list[dict[str, Any]] = []
    for card in sorted(cards, key=_card_priority, reverse=True):
        key = (card.get("category"), card.get("nodeKey"), card.get("title"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(card)
    return unique[:max_cards]


# ── Pure builder ─────────────────────────────────────────────────────

def _center_overview_card(
    center: dict[str, Any],
    edges: list[dict[str, Any]],
    nodes_by_id: dict[Any, dict[str, Any]],
) -> dict[str, Any] | None:
    neighbors = _connected(center["id"], edges, nodes_by_id)
    if not neighbors:
        return None
    sources = _bucket_sources(neighbors)
    counts = {k: len(v) for k, v in sources.items() if v}
    if not counts:
        return None
    parts = [f"**{count}** {label}" for label, count in counts.items()]
    summary = (
        f"{center['label']} is connected to " + ", ".join(parts) + " in the graph."
    )
    return {
        "id": f"kgcard:overview:{center['graphKey']}",
        "nodeKey": center["graphKey"],
        "category": "business_insight",
        "severity": "info",
        "title": f"{center['label']} — graph overview",
        "summary": summary,
        "businessQuestion": center["businessQuestion"],
        "businessImpact": center["businessValue"],
        "confidence": center["confidence"] if center["confidence"] is not None else 0.0,
        "evidencePath": [center["graphKey"]],
        "sourceDocuments": sources["documents"],
        "sourceTables": sources["tables"],
        "sourceQueries": sources["queries"],
        "sourceDashboards": sources["dashboards"],
        "supportedKpis": sources["kpis"],
        "recommendedAction": "",
        "traceToEvidence": {
            "nodeIds": [center["id"], *[o["id"] for o, _e in neighbors]],
            "edgeIds": [e["id"] for _o, e in neighbors],
            "nodeKeys": [],
            "hops": _hops(neighbors),
        },
    }


def _kpi_measurement_gap_card(
    center: dict[str, Any],
    edges: list[dict[str, Any]],
    nodes_by_id: dict[Any, dict[str, Any]],
) -> dict[str, Any] | None:
    """Gap card for a centred KPI that no query or dashboard measures.

    Returns ``None`` when a query or dashboard already measures the KPI (no
    gap). The gap is grounded in the KPI's own supporting documents — never
    fabricated.
    """
    neighbors = _connected(center["id"], edges, nodes_by_id)
    sources = _bucket_sources(neighbors)
    if sources["queries"] or sources["dashboards"]:
        return None
    return {
        "id": f"kgcard:gap:kpi:{center['graphKey']}",
        "nodeKey": center["graphKey"],
        "category": "gap",
        "severity": "warning",
        "title": f"{center['label']} is not measured",
        "summary": (
            f"No saved query or dashboard measures {center['label']}. "
            "Build a query or dashboard so this KPI can be tracked against its "
            "documented target."
        ),
        "businessQuestion": f"How is {center['label']} currently tracked?",
        "businessImpact": "Unmeasured KPIs cannot be monitored or trended.",
        "confidence": center["confidence"] if center["confidence"] is not None else 0.9,
        "evidencePath": [center["graphKey"]],
        "sourceDocuments": sources["documents"],
        "sourceTables": sources["tables"],
        "sourceQueries": [],
        "sourceDashboards": [],
        "supportedKpis": [center["label"]],
        "recommendedAction": f"Create a query or dashboard that measures {center['label']}.",
        "traceToEvidence": {
            "nodeIds": [center["id"], *[o["id"] for o, _e in neighbors]],
            "edgeIds": [e["id"] for _o, e in neighbors],
            "nodeKeys": [],
            "hops": _hops(neighbors),
        },
    }


def _card_bundle(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract the cacheable insight-card bundle from an enriched payload."""
    return {
        "insightCards": payload.get("insightCards", []),
        "gaps": payload.get("gaps", []),
        "recommendedActions": payload.get("recommendedActions", []),
        "tracePaths": payload.get("tracePaths", []),
        "aiGenerated": payload.get("aiGenerated", False),
        # KG-40: "ok" when AI enrichment produced the cards above, or
        # "unavailable" when they're the deterministic structural fallback
        # (see knowledge_graph_ai._clear_cards) -- persisted alongside the
        # cards themselves so a later cache read can still tell them apart.
        "aiEnrichmentStatus": payload.get("aiEnrichmentStatus", "ok"),
    }


def _overlay_card_bundle(payload: dict[str, Any], bundle: dict[str, Any]) -> None:
    """Overlay a cached insight-card bundle onto a freshly-built payload.

    KG-40: the bundle's own cards may themselves be a structural fallback
    (``aiEnrichmentStatus == "unavailable"``, see ``_clear_cards``), not
    only AI-enriched cards -- either way, whatever the bundle holds is
    what a centre shows, since it's already the best available (grounded)
    content for that centre.
    """
    payload["insightCards"] = bundle.get("insightCards") or []
    payload["gaps"] = bundle.get("gaps", payload["gaps"])
    payload["recommendedActions"] = bundle.get(
        "recommendedActions", payload["recommendedActions"]
    )
    payload["tracePaths"] = bundle.get("tracePaths") or []
    payload["aiGenerated"] = bool(bundle.get("aiGenerated"))
    payload["aiEnrichmentStatus"] = bundle.get("aiEnrichmentStatus", "ok")


