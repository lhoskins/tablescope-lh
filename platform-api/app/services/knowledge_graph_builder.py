"""Insight-First Knowledge Graph builder.

Builds a node-centric graph neighborhood from the existing
``ai_project_graph_nodes`` / ``ai_project_graph_edges`` tables (no new graph
store) and derives AI Home-style Knowledge Graph insight cards, gap findings,
recommended actions and trace-to-evidence paths.

The build is deterministic and evidence-gated: cards/gaps are derived only from
nodes and edges that actually exist in the project graph, so the feature works
without the AI server and never invents evidence. AI enrichment can layer on top
later via the same response shape.

Design note: the heavy lifting lives in pure functions that take plain node/edge
dicts so they are trivially unit-testable; :func:`build_node_centric_graph` is a
thin async wrapper that loads the tenant/project-scoped graph from the database
and calls them.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

PIPELINE_VERSION = "knowledge_graph_node_centric_v2"
# Cached full-graph snapshot pipeline version.
SNAPSHOT_PIPELINE_VERSION = "knowledge_graph_snapshot_v1"

# Default edge/node confidence floor for the visible graph.
DEFAULT_MIN_CONFIDENCE = 0.70
# Below this an edge is only shown when include_inferred is set.
INFERRED_FLOOR = 0.50
# Keep the canvas readable.
MAX_NEIGHBORHOOD_NODES = 60
MAX_CARDS = 8

# ── Node taxonomy ────────────────────────────────────────────────────

_LAYER_BY_TYPE: dict[str, str] = {
    "project": "project",
    "document": "evidence",
    "document_family": "semantic",
    "reference_document": "evidence",
    "policy": "evidence",
    "procedure": "evidence",
    "standard": "evidence",
    "control": "evidence",
    "data_source": "evidence",
    "datasource": "evidence",
    "table": "evidence",
    "column": "evidence",
    "saved_query": "evidence",
    "query": "evidence",
    "dashboard": "evidence",
    "kpi": "kpi",
    "metric": "kpi",
    "threshold": "kpi",
    "benchmark": "kpi",
    "process": "semantic",
    "business_entity": "semantic",
    "entity": "semantic",
    "supplier": "semantic",
    "customer": "semantic",
    "product": "semantic",
    "facility": "semantic",
    "contract": "semantic",
    "tag": "semantic",
    "risk": "insight",
    "warning": "insight",
    "opportunity": "insight",
    "anomaly": "insight",
    "audit_finding": "insight",
    "compliance_gap": "insight",
    "process_gap": "insight",
    "data_gap": "insight",
    "gap": "insight",
    "insight": "insight",
    "relationship_insight": "insight",
    "recommendation": "action",
    "action": "action",
}

_DISPLAY_GROUP_BY_TYPE: dict[str, str] = {
    "project": "Project",
    "document": "Supporting & Governing Documents",
    "document_family": "Supporting & Governing Documents",
    "reference_document": "Authoritative Reference Library",
    "policy": "Governing Policies / SOPs",
    "procedure": "Governing Policies / SOPs",
    "standard": "Governing Policies / SOPs",
    "control": "Governing Policies / SOPs",
    "kpi": "KPIs & Metrics",
    "metric": "KPIs & Metrics",
    "threshold": "KPIs & Metrics",
    "benchmark": "KPIs & Metrics",
    "saved_query": "Queries",
    "query": "Queries",
    "dashboard": "Dashboards",
    "data_source": "Linked Data Sources",
    "datasource": "Linked Data Sources",
    "table": "Linked Data Sources",
    "column": "Linked Data Sources",
    "process": "Related Processes",
    "business_entity": "Related Entities",
    "entity": "Related Entities",
    "supplier": "Related Entities",
    "customer": "Related Entities",
    "product": "Related Entities",
    "facility": "Related Entities",
    "contract": "Related Entities",
    "tag": "Related Entities",
    "risk": "Insights / Findings",
    "warning": "Insights / Findings",
    "opportunity": "Insights / Findings",
    "anomaly": "Insights / Findings",
    "audit_finding": "Insights / Findings",
    "compliance_gap": "Insights / Findings",
    "process_gap": "Insights / Findings",
    "data_gap": "Insights / Findings",
    "gap": "Insights / Findings",
    "insight": "Insights / Findings",
    "relationship_insight": "Insights / Findings",
    "recommendation": "Recommendations",
    "action": "Recommendations",
}

# Default severity per node type when properties.severity is absent.
_SEVERITY_BY_TYPE: dict[str, str] = {
    "risk": "urgent",
    "audit_finding": "urgent",
    "compliance_gap": "warning",
    "warning": "warning",
    "anomaly": "warning",
    "process_gap": "warning",
    "data_gap": "warning",
    "gap": "warning",
    "opportunity": "opportunity",
}

_ALLOWED_SEVERITIES = ("critical", "urgent", "warning", "watch", "opportunity", "info")
_SEVERITY_RANK = {
    "critical": 6, "urgent": 5, "warning": 4, "watch": 3, "opportunity": 3, "info": 1,
}

# Node types that are themselves a "finding" the right panel surfaces as a card.
_INSIGHT_TYPES = {
    "risk", "warning", "opportunity", "anomaly", "audit_finding",
    "compliance_gap", "process_gap", "data_gap", "gap", "insight",
    "relationship_insight",
}
_GAP_TYPES = {"gap", "process_gap", "data_gap", "compliance_gap"}
_ACTION_TYPES = {"recommendation", "action"}

# Edge types that point an insight/gap/recommendation at its evidence.
_EVIDENCE_EDGE_TYPES = {
    "evidence_for", "governs", "governed_by", "references", "supports",
    "measures", "calculated_from", "derived_from", "visualizes", "uses",
    "defines", "indicates", "drives", "follows_from", "recommends",
    "mitigates", "threshold_from", "benchmarked_against",
}

# Maps a node type onto a Knowledge Graph card category.
_CARD_CATEGORY_BY_TYPE: dict[str, str] = {
    "risk": "risk",
    "audit_finding": "risk",
    "warning": "warning",
    "anomaly": "warning",
    "opportunity": "opportunity",
    "gap": "gap",
    "process_gap": "gap",
    "data_gap": "gap",
    "compliance_gap": "gap",
    "insight": "business_insight",
    "relationship_insight": "business_insight",
}

# Best lens to switch to when a node of the given type is selected.
_LENS_BY_TYPE: dict[str, str] = {
    "document": "document-centric",
    "document_family": "family-centric",
    "reference_document": "document-centric",
    "policy": "process-centric",
    "procedure": "process-centric",
    "process": "process-centric",
    "kpi": "kpi-centric",
    "metric": "kpi-centric",
    "dashboard": "lineage",
    "query": "lineage",
    "saved_query": "lineage",
    "data_source": "lineage",
    "table": "lineage",
    "risk": "insight-first",
    "warning": "insight-first",
    "opportunity": "insight-first",
    "gap": "evidence",
}


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _layer_for(node_type: str) -> str:
    return _LAYER_BY_TYPE.get(node_type, "semantic")


def _display_group_for(node_type: str) -> str:
    return _DISPLAY_GROUP_BY_TYPE.get(node_type, "Related Entities")


def _normalize_severity(value: Any) -> str:
    if isinstance(value, str) and value.lower() in _ALLOWED_SEVERITIES:
        return value.lower()
    return ""


def _severity_for(node_type: str, props: dict[str, Any]) -> str:
    explicit = _normalize_severity(props.get("severity"))
    if explicit:
        return explicit
    return _SEVERITY_BY_TYPE.get(node_type, "info")


def graph_key_for(node: dict[str, Any]) -> str:
    """Return a stable graph key for a raw node row.

    Prefers an explicit ``properties.graph_key``; otherwise derives one from the
    node type and its most stable identifier so clicks/URLs survive rebuilds.
    """
    props = _as_dict(node.get("properties"))
    explicit = str(props.get("graph_key") or "").strip()
    if explicit:
        return explicit

    ntype = str(node.get("node_type") or node.get("type") or "node")
    name = str(node.get("name") or node.get("label") or "")
    source_id = node.get("source_id")
    node_id = node.get("id")

    if ntype == "project":
        return f"project:{props.get('project_id', node_id)}"
    if ntype in ("document", "reference_document"):
        return f"document:{source_id or node_id}"
    if ntype == "document_family":
        return f"document_family:{props.get('family_key') or _norm(name) or node_id}"
    if ntype in ("data_source", "datasource", "table"):
        return f"datasource:{_norm(name) or node_id}"
    if ntype in ("saved_query", "query"):
        return f"query:{source_id or node_id}"
    if ntype == "dashboard":
        return f"dashboard:{source_id or node_id}"
    if ntype in ("kpi", "metric"):
        return f"kpi:{props.get('kpi_key') or _norm(name) or node_id}"
    if ntype == "process":
        return f"process:{_norm(name) or node_id}"
    if ntype in _GAP_TYPES:
        return f"gap:{props.get('gap_key') or _norm(name) or node_id}"
    if ntype in _ACTION_TYPES:
        return f"action:{node_id}"
    if ntype in _INSIGHT_TYPES:
        return f"insight:{node_id}"
    if _layer_for(ntype) == "semantic":
        return f"entity:{_norm(name) or node_id}"
    return f"{ntype}:{node_id}"


# ── Enrichment ───────────────────────────────────────────────────────

def enrich_node(node: dict[str, Any]) -> dict[str, Any]:
    """Augment a raw node row with graph metadata used by the UI."""
    props = _as_dict(node.get("properties"))
    ntype = str(node.get("node_type") or node.get("type") or "node")
    name = str(node.get("name") or node.get("label") or "")
    key = graph_key_for(node)

    confidence = props.get("confidence")
    try:
        confidence = round(float(confidence), 4) if confidence is not None else None
    except (TypeError, ValueError):
        confidence = None

    return {
        "id": node.get("id"),
        "type": ntype,
        "label": name,
        "source_type": node.get("source_type"),
        "source_id": node.get("source_id"),
        "properties": props,
        "graphKey": key,
        "layer": _layer_for(ntype),
        "displayGroup": _display_group_for(ntype),
        "severity": _severity_for(ntype, props),
        "summary": str(props.get("summary") or props.get("description") or ""),
        "businessValue": str(props.get("business_value") or ""),
        "businessQuestion": str(props.get("business_question") or ""),
        "confidence": confidence,
        "isCenterEligible": True,
        "clickAction": "center_graph",
        "recommendedLens": _LENS_BY_TYPE.get(ntype, "insight-first"),
    }


def _edge_confidence(edge: dict[str, Any]) -> float:
    try:
        return float(edge.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _evidence_summary(edge: dict[str, Any]) -> str:
    ev = edge.get("evidence")
    d = _as_dict(ev)
    if d:
        return str(d.get("evidence_summary") or d.get("reason") or d.get("text") or "")
    return str(ev or "")


# ── Neighborhood selection ───────────────────────────────────────────

def _pick_center(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    center_node: str | None,
) -> dict[str, Any] | None:
    """Resolve the center node from a graph key / id, with sensible defaults."""
    if not nodes:
        return None
    by_key = {n["graphKey"]: n for n in nodes}
    by_id = {str(n["id"]): n for n in nodes}

    if center_node:
        if center_node in by_key:
            return by_key[center_node]
        if center_node in by_id:
            return by_id[center_node]

    # Default 1: the project hub — its overview radiates to every related
    # source (documents, reference library, data sources, queries, dashboards),
    # so the first view shows the full neighbourhood with directional edges.
    projects = [n for n in nodes if n["type"] == "project"]
    if projects:
        return _highest_degree(projects, edges)
    # Default 2: a process node (the mockup centers on a process).
    processes = [n for n in nodes if n["type"] == "process"]
    if processes:
        return _highest_degree(processes, edges)
    # Default 3: the highest-degree node overall.
    return _highest_degree(nodes, edges)


def _highest_degree(
    candidates: list[dict[str, Any]], edges: list[dict[str, Any]],
) -> dict[str, Any]:
    degree: dict[Any, int] = {}
    for e in edges:
        degree[e["from_node_id"]] = degree.get(e["from_node_id"], 0) + 1
        degree[e["to_node_id"]] = degree.get(e["to_node_id"], 0) + 1
    return max(candidates, key=lambda n: degree.get(n["id"], 0))


def _neighborhood(
    center: dict[str, Any],
    nodes_by_id: dict[Any, dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    max_nodes: int = MAX_NEIGHBORHOOD_NODES,
) -> tuple[set[Any], list[dict[str, Any]]]:
    """BFS up to 2 hops from the center, keeping the strongest edges first.

    Returns the set of kept node ids and the edges fully inside that set.
    """
    adjacency: dict[Any, list[tuple[Any, dict[str, Any]]]] = {}
    for e in edges:
        adjacency.setdefault(e["from_node_id"], []).append((e["to_node_id"], e))
        adjacency.setdefault(e["to_node_id"], []).append((e["from_node_id"], e))

    kept: set[Any] = {center["id"]}
    frontier = [center["id"]]
    for _hop in range(2):
        next_frontier: list[Any] = []
        for nid in frontier:
            neighbors = sorted(
                adjacency.get(nid, []),
                key=lambda pair: _edge_confidence(pair[1]),
                reverse=True,
            )
            for other_id, _edge in neighbors:
                if other_id in kept:
                    continue
                if other_id not in nodes_by_id:
                    continue
                if len(kept) >= max_nodes:
                    break
                kept.add(other_id)
                next_frontier.append(other_id)
            if len(kept) >= max_nodes:
                break
        frontier = next_frontier
        if not frontier or len(kept) >= max_nodes:
            break

    kept_edges = [
        e for e in edges if e["from_node_id"] in kept and e["to_node_id"] in kept
    ]
    return kept, kept_edges


# ── Insight cards / gaps / recommendations ───────────────────────────

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
        "traceToEvidence": {
            "nodeIds": evidence_node_ids,
            "edgeIds": evidence_edge_ids,
            "nodeKeys": evidence_path,
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

def build_graph_payload(
    raw_nodes: list[dict[str, Any]],
    raw_edges: list[dict[str, Any]],
    *,
    center_node: str | None = None,
    lens: str = "insight-first",
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    include_inferred: bool = False,
    severity: str = "all",
) -> dict[str, Any]:
    """Build the node-centric graph response from raw node/edge rows.

    Backward compatible: the returned ``nodes``/``edges`` keep the existing
    shape (with extra optional fields) so old callers keep working.
    """
    enriched = [enrich_node(n) for n in raw_nodes]
    nodes_by_id = {n["id"]: n for n in enriched}

    floor = INFERRED_FLOOR if include_inferred else min_confidence
    norm_edges: list[dict[str, Any]] = []
    for e in raw_edges:
        if e["from_node_id"] not in nodes_by_id or e["to_node_id"] not in nodes_by_id:
            continue
        conf = _edge_confidence(e)
        # Family/structural edges with no confidence are always kept.
        if conf and conf < floor:
            continue
        norm_edges.append(e)

    center = _pick_center(enriched, norm_edges, center_node)
    if center is None:
        return {
            "centerNode": None,
            "nodes": [],
            "edges": [],
            "insightCards": [],
            "gaps": [],
            "recommendedActions": [],
            "tracePaths": [],
            "stats": _empty_stats(),
            "generated_at": datetime.now(UTC).isoformat(),
            "pipeline_version": PIPELINE_VERSION,
        }

    kept_ids, kept_edges = _neighborhood(center, nodes_by_id, norm_edges)
    kept_nodes = [n for n in enriched if n["id"] in kept_ids]
    kept_by_id = {n["id"]: n for n in kept_nodes}

    # Insight / gap / recommendation cards from finding + action nodes.
    cards: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    recommended_actions: list[dict[str, Any]] = []
    trace_paths: list[dict[str, Any]] = []

    for node in kept_nodes:
        if node["type"] in _INSIGHT_TYPES:
            card = _build_card_for_node(node, kept_edges, kept_by_id)
            if card:
                cards.append(card)
                trace_paths.append({
                    "id": f"trace:{node['graphKey']}",
                    "fromNodeKey": node["graphKey"],
                    "nodeIds": card["traceToEvidence"]["nodeIds"],
                    "edgeIds": card["traceToEvidence"]["edgeIds"],
                })
        if node["type"] in _GAP_TYPES:
            gap = _build_gap_finding(node, kept_edges, kept_by_id)
            if gap:
                gaps.append(gap)
        if node["type"] in _ACTION_TYPES:
            recommended_actions.append({
                "id": f"action:{node['graphKey']}",
                "nodeKey": node["graphKey"],
                "title": node["label"],
                "summary": node["summary"],
                "severity": node["severity"],
                "confidence": node["confidence"] if node["confidence"] is not None else 0.0,
            })
            cards.append({
                "id": f"kgcard:{node['graphKey']}",
                "nodeKey": node["graphKey"],
                "category": "recommendation",
                "severity": node["severity"] if node["severity"] != "info" else "watch",
                "title": node["label"],
                "summary": node["summary"] or node["label"],
                "businessQuestion": node["businessQuestion"],
                "businessImpact": node["businessValue"],
                "confidence": node["confidence"] if node["confidence"] is not None else 0.0,
                "evidencePath": [center["graphKey"]],
                "sourceDocuments": [],
                "sourceTables": [],
                "sourceQueries": [],
                "sourceDashboards": [],
                "supportedKpis": [],
                "recommendedAction": node["label"],
                "traceToEvidence": {"nodeIds": [node["id"], center["id"]], "edgeIds": [], "nodeKeys": []},
            })

    # A center business-insight card summarizing governance coverage when the
    # center has supporting evidence but isn't itself a finding.
    if center["type"] not in _INSIGHT_TYPES:
        overview = _center_overview_card(center, kept_edges, kept_by_id)
        if overview:
            cards.append(overview)

    cards = _rank_and_dedupe_cards(cards)

    if severity and severity != "all":
        cards = [c for c in cards if c["severity"] == severity]
        gaps = [g for g in gaps if g["severity"] == severity]

    stats = _stats(kept_nodes, kept_edges, cards, gaps)

    return {
        "centerNode": center,
        "nodes": kept_nodes,
        "edges": [_edge_payload(e, kept_by_id) for e in kept_edges],
        "insightCards": cards,
        "gaps": gaps,
        "recommendedActions": recommended_actions,
        "tracePaths": trace_paths,
        "stats": stats,
        "lens": lens,
        "minConfidence": min_confidence,
        "includeInferred": include_inferred,
        "generated_at": datetime.now(UTC).isoformat(),
        "pipeline_version": PIPELINE_VERSION,
    }


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
        },
    }


def _edge_payload(edge: dict[str, Any], nodes_by_id: dict[Any, dict[str, Any]]) -> dict[str, Any]:
    ev = _as_dict(edge.get("evidence"))
    return {
        "id": edge["id"],
        "source": edge["from_node_id"],
        "target": edge["to_node_id"],
        "type": edge.get("relationship_type") or edge.get("edge_type") or "",
        "confidence": _edge_confidence(edge),
        "evidence": _evidence_summary(edge),
        "validationStatus": str(ev.get("validation_status") or ""),
    }


def _stats(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    cards: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    by_group: dict[str, int] = {}
    for n in nodes:
        by_group[n["displayGroup"]] = by_group.get(n["displayGroup"], 0) + 1
    return {
        "nodeCount": len(nodes),
        "edgeCount": len(edges),
        "cardCount": len(cards),
        "gapCount": len(gaps),
        "byDisplayGroup": by_group,
    }


def _empty_stats() -> dict[str, Any]:
    return {"nodeCount": 0, "edgeCount": 0, "cardCount": 0, "gapCount": 0, "byDisplayGroup": {}}


def merge_graph_sources(
    stored_nodes: list[dict[str, Any]],
    stored_edges: list[dict[str, Any]],
    extra_nodes: list[dict[str, Any]],
    extra_edges: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Merge stored (AI) graph rows with structural rows, deduped by graph key.

    Stored nodes win on collision (they carry AI summaries / properties); the
    structural twin's id is remapped onto the stored node so its edges survive.
    Edges are deduped by (from, to, relationship_type), keeping the strongest.
    """
    canonical_by_key: dict[str, dict[str, Any]] = {}
    id_remap: dict[Any, Any] = {}
    merged_nodes: list[dict[str, Any]] = []

    for n in [*stored_nodes, *extra_nodes]:
        key = graph_key_for(n)
        existing = canonical_by_key.get(key)
        if existing is None:
            canonical_by_key[key] = n
            merged_nodes.append(n)
            id_remap[n["id"]] = n["id"]
        else:
            id_remap[n["id"]] = existing["id"]

    valid_ids = {n["id"] for n in merged_nodes}
    seen: dict[tuple[Any, Any, str], int] = {}
    merged_edges: list[dict[str, Any]] = []
    for e in [*stored_edges, *extra_edges]:
        f = id_remap.get(e["from_node_id"], e["from_node_id"])
        t = id_remap.get(e["to_node_id"], e["to_node_id"])
        if f == t or f not in valid_ids or t not in valid_ids:
            continue
        remapped = {**e, "from_node_id": f, "to_node_id": t}
        ekey = (f, t, str(e.get("relationship_type") or ""))
        prev = seen.get(ekey)
        if prev is not None:
            if _edge_confidence(remapped) > _edge_confidence(merged_edges[prev]):
                merged_edges[prev] = remapped
            continue
        seen[ekey] = len(merged_edges)
        merged_edges.append(remapped)
    return merged_nodes, merged_edges


# ── Snapshot persistence (cache) ─────────────────────────────────────

async def _load_stored_graph(
    session: AsyncSession, *, tenant_id: int, project_id: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load the stored AI graph rows merged with the structural Evidence graph."""
    node_rows = await session.execute(
        text(
            """
            SELECT id, node_type, name, source_type, source_id, properties
            FROM ai_project_graph_nodes
            WHERE tenant_id=:tid AND project_id=:pid AND is_active=true
            ORDER BY id
            """
        ),
        {"tid": tenant_id, "pid": project_id},
    )
    raw_nodes = [
        {
            "id": r[0], "node_type": r[1], "name": r[2],
            "source_type": r[3], "source_id": r[4], "properties": r[5],
        }
        for r in node_rows.fetchall()
    ]

    edge_rows = await session.execute(
        text(
            """
            SELECT id, from_node_id, to_node_id, relationship_type, confidence, evidence
            FROM ai_project_graph_edges
            WHERE tenant_id=:tid AND project_id=:pid AND is_active=true
            """
        ),
        {"tid": tenant_id, "pid": project_id},
    )
    raw_edges = [
        {
            "id": r[0], "from_node_id": r[1], "to_node_id": r[2],
            "relationship_type": r[3], "confidence": r[4], "evidence": r[5],
        }
        for r in edge_rows.fetchall()
    ]

    # Evidence Collector: fold the project's real assets (documents, reference
    # library, data sources, queries, dashboards) into the graph so every node's
    # related sources are present with directional, labelled edges.
    from app.services.knowledge_graph_context import collect_structural_graph

    extra_nodes, extra_edges, _hub_key = await collect_structural_graph(
        session, tenant_id=tenant_id, project_id=project_id,
    )
    return merge_graph_sources(raw_nodes, raw_edges, extra_nodes, extra_edges)


def _json_safe(obj: Any) -> Any:
    """Recursively coerce a value into JSON-serializable primitives.

    Postgres ``NUMERIC`` columns (e.g. edge confidence) come back as ``Decimal``
    and datetimes as ``datetime`` — neither is JSON-serializable for the JSONB
    snapshot payload, so convert them to ``float`` / ISO strings.
    """
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


async def rebuild_project_graph_snapshot(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
    user_id: int | None = None,
    enrich_with_ai: bool = True,
) -> dict[str, Any]:
    """Rebuild and persist the full project Knowledge Graph snapshot.

    Collects the stored graph rows + structural Evidence graph, runs AI
    enrichment for the default-centre view (so the first load shows AI-Home-style
    cards instantly from cache), and upserts the snapshot row. Returns the
    in-memory snapshot dict.
    """
    from app.models.knowledge_graph_snapshot import (
        SNAPSHOT_KEY_FULL,
        AIProjectGraphSnapshot,
    )

    raw_nodes, raw_edges = await _load_stored_graph(
        session, tenant_id=tenant_id, project_id=project_id,
    )

    # Default-centre payload (project hub) — used to cache AI-enriched cards.
    default_payload = build_graph_payload(raw_nodes, raw_edges)
    ai_center_key: str | None = None
    ai_cards: dict[str, Any] | None = None
    if enrich_with_ai and user_id is not None and default_payload.get("centerNode"):
        from app.services.knowledge_graph_ai import enrich_payload_with_ai

        enriched = await enrich_payload_with_ai(
            default_payload, tenant_id=tenant_id, user_id=user_id,
            project_id=project_id,
        )
        center = enriched.get("centerNode") or {}
        ai_center_key = center.get("graphKey")
        ai_cards = {
            "insightCards": enriched.get("insightCards", []),
            "gaps": enriched.get("gaps", []),
            "recommendedActions": enriched.get("recommendedActions", []),
            "tracePaths": enriched.get("tracePaths", []),
            "aiGenerated": enriched.get("aiGenerated", False),
        }

    generated_at = datetime.now(UTC).isoformat()
    payload = _json_safe({
        "fullGraph": {"nodes": raw_nodes, "edges": raw_edges},
        "sourceCounts": _snapshot_source_counts(raw_nodes),
        "aiCenterKey": ai_center_key,
        "aiCards": ai_cards,
        "pipelineVersion": SNAPSHOT_PIPELINE_VERSION,
        "generatedAt": generated_at,
    })

    gen_dt = datetime.now(UTC)
    try:
        row = await session.scalar(
            select(AIProjectGraphSnapshot).where(
                AIProjectGraphSnapshot.tenant_id == tenant_id,
                AIProjectGraphSnapshot.project_id == project_id,
                AIProjectGraphSnapshot.snapshot_key == SNAPSHOT_KEY_FULL,
            )
        )
        if row is None:
            row = AIProjectGraphSnapshot(
                tenant_id=tenant_id,
                project_id=project_id,
                snapshot_key=SNAPSHOT_KEY_FULL,
                payload=payload,
                pipeline_version=SNAPSHOT_PIPELINE_VERSION,
                generated_at=gen_dt,
                created_by=user_id,
            )
            session.add(row)
        else:
            row.payload = payload
            row.pipeline_version = SNAPSHOT_PIPELINE_VERSION
            row.generated_at = gen_dt
        await session.flush()
        await session.commit()
        snapshot_id: int | None = row.id
    except Exception:
        # Never let a persistence failure break the graph: roll back and serve
        # the freshly-computed payload from memory (uncached).
        logger.exception("Failed to persist Knowledge Graph snapshot")
        await session.rollback()
        snapshot_id = None

    return {"id": snapshot_id, **payload}


def _snapshot_source_counts(raw_nodes: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for n in raw_nodes:
        t = str(n.get("node_type") or "unknown")
        counts[t] = counts.get(t, 0) + 1
    return counts


async def get_project_graph_snapshot(
    session: AsyncSession, *, tenant_id: int, project_id: int,
) -> dict[str, Any] | None:
    """Return the latest cached full-graph snapshot, or ``None`` if absent."""
    from app.models.knowledge_graph_snapshot import (
        SNAPSHOT_KEY_FULL,
        AIProjectGraphSnapshot,
    )

    row = await session.scalar(
        select(AIProjectGraphSnapshot).where(
            AIProjectGraphSnapshot.tenant_id == tenant_id,
            AIProjectGraphSnapshot.project_id == project_id,
            AIProjectGraphSnapshot.snapshot_key == SNAPSHOT_KEY_FULL,
        )
    )
    if row is None:
        return None
    payload = dict(row.payload or {})
    payload.setdefault("fullGraph", {"nodes": [], "edges": []})
    generated_at = payload.get("generatedAt") or (
        row.generated_at.isoformat() if row.generated_at else ""
    )
    return {"id": row.id, **payload, "generatedAt": generated_at}


def build_node_centric_graph_from_snapshot(
    snapshot: dict[str, Any],
    *,
    center_node: str | None = None,
    lens: str = "insight-first",
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    include_inferred: bool = False,
    severity: str = "all",
) -> dict[str, Any]:
    """Build a node-centric payload from a cached snapshot's full graph.

    Does not re-collect the structural graph and does not call the AI server.
    Cached AI cards are overlaid only when the effective centre matches the
    centre the cards were generated for (the default project hub).
    """
    full = snapshot.get("fullGraph") or {"nodes": [], "edges": []}
    payload = build_graph_payload(
        full.get("nodes", []),
        full.get("edges", []),
        center_node=center_node,
        lens=lens,
        min_confidence=min_confidence,
        include_inferred=include_inferred,
        severity=severity,
    )
    center = payload.get("centerNode")
    ai_cards = snapshot.get("aiCards")
    ai_center_key = snapshot.get("aiCenterKey")
    if center and ai_cards and ai_center_key and center.get("graphKey") == ai_center_key:
        payload["insightCards"] = ai_cards.get("insightCards", payload["insightCards"])
        payload["gaps"] = ai_cards.get("gaps", payload["gaps"])
        payload["recommendedActions"] = ai_cards.get(
            "recommendedActions", payload["recommendedActions"]
        )
        payload["tracePaths"] = ai_cards.get("tracePaths", payload["tracePaths"])
        if ai_cards.get("aiGenerated"):
            payload["aiGenerated"] = True
    return payload


# ── Async DB wrapper ─────────────────────────────────────────────────

async def build_node_centric_graph(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
    user_id: int | None = None,
    center_node: str | None = None,
    lens: str = "insight-first",
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    include_inferred: bool = False,
    severity: str = "all",
    refresh: bool = False,
) -> dict[str, Any]:
    """Return the node-centric Knowledge Graph payload from the cached snapshot.

    Default load and node clicks read the persisted full-graph snapshot and only
    recenter/filter from its cached nodes/edges (no structural collection, no AI
    call). ``refresh=True`` rebuilds and re-persists the snapshot. A missing
    snapshot triggers a single rebuild.
    """
    snapshot: dict[str, Any] | None = None
    if not refresh:
        snapshot = await get_project_graph_snapshot(
            session, tenant_id=tenant_id, project_id=project_id,
        )
    if snapshot is None:
        snapshot = await rebuild_project_graph_snapshot(
            session, tenant_id=tenant_id, project_id=project_id, user_id=user_id,
        )

    payload = build_node_centric_graph_from_snapshot(
        snapshot,
        center_node=center_node,
        lens=lens,
        min_confidence=min_confidence,
        include_inferred=include_inferred,
        severity=severity,
    )
    payload["lastUpdated"] = snapshot.get("generatedAt", "")
    payload["snapshotId"] = snapshot.get("id")
    payload["isCached"] = not refresh
    return payload
