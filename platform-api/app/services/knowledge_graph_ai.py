"""AI enrichment for the Insight-First Knowledge Graph.

Mirrors the AI Home architecture: the deterministic builder produces the
node-centric neighborhood, then this module hands that neighborhood to the AI
server (``/ai/intelligence/knowledge-graph``) to generate AI-Home-style business
insight cards specific to the selected node and its related data sources.

The AI call is best-effort: on any failure (AI disabled, unreachable, no usable
cards) the deterministic cards already on the payload are kept, so the graph
never breaks just because the AI server is slow or down.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services import ai_intelligence_client as ai

logger = logging.getLogger(__name__)

PIPELINE_VERSION_AI = "knowledge_graph_insight_first_v1"

_DOC_TYPES = {
    "document", "reference_document", "policy", "procedure",
    "standard", "control", "document_family",
}
_TABLE_TYPES = {"data_source", "datasource", "table"}
_QUERY_TYPES = {"query", "saved_query"}
_DASH_TYPES = {"dashboard"}
_KPI_TYPES = {"kpi", "metric", "threshold", "benchmark"}


def _build_ai_request(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Translate the deterministic payload into the AI request inputs."""
    center = payload["centerNode"]
    center_id = center["id"]
    nodes: list[dict[str, Any]] = payload["nodes"]
    edges: list[dict[str, Any]] = payload["edges"]

    # Best (highest-confidence) direct edge between the center and each node.
    direct: dict[Any, dict[str, Any]] = {}
    for e in edges:
        other: Any | None = None
        direction = ""
        if e["source"] == center_id:
            other, direction = e["target"], "out"
        elif e["target"] == center_id:
            other, direction = e["source"], "in"
        if other is None:
            continue
        prev = direct.get(other)
        if prev is None or (e.get("confidence") or 0) > (prev.get("confidence") or 0):
            direct[other] = {**e, "_direction": direction}

    neighbors: list[dict[str, Any]] = []
    for n in nodes:
        if n["id"] == center_id:
            continue
        edge = direct.get(n["id"])
        neighbors.append(
            {
                "graph_key": n["graphKey"],
                "type": n["type"],
                "label": n["label"],
                "display_group": n.get("displayGroup") or "",
                "summary": n.get("summary") or "",
                "relationship": (edge.get("type") if edge else "") or "related_to",
                "confidence": (edge.get("confidence") if edge else n.get("confidence")) or 0.0,
                "direction": edge.get("_direction") if edge else "",
            }
        )

    documents = [
        {"title": n["label"], "summary": n.get("summary") or "", "source": n["type"]}
        for n in nodes
        if n["type"] in _DOC_TYPES and n["id"] != center_id
    ]
    kpis = [
        n["label"]
        for n in nodes
        if n["type"] in _KPI_TYPES and n["id"] != center_id and n["label"]
    ]

    center_payload = {
        "graph_key": center["graphKey"],
        "type": center["type"],
        "label": center["label"],
        "summary": center.get("summary") or "",
        "display_group": center.get("displayGroup") or "",
    }
    return center_payload, neighbors, documents, kpis


def _map_card(
    raw: dict[str, Any],
    *,
    index: int,
    center: dict[str, Any],
    nodes_by_key: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Map an AI card onto the platform card shape, grounding it in real nodes."""
    evidence_keys = [k for k in raw.get("evidenceKeys", []) if k in nodes_by_key]
    if not evidence_keys:
        return None

    evidence_nodes = [nodes_by_key[k] for k in evidence_keys]
    evidence_ids = {center["id"], *[n["id"] for n in evidence_nodes]}
    edge_ids = [
        e["id"]
        for e in edges
        if e["source"] in evidence_ids and e["target"] in evidence_ids
    ]

    def _labels(types: set[str]) -> list[str]:
        out: list[str] = []
        for n in evidence_nodes:
            if n["type"] in types and n["label"] and n["label"] not in out:
                out.append(n["label"])
        return out

    source_documents = _labels(_DOC_TYPES) or [
        str(d) for d in raw.get("sourceDocuments", []) if d
    ]
    supported_kpis = _labels(_KPI_TYPES) or [
        str(k) for k in raw.get("supportedKpis", []) if k
    ]

    category = str(raw.get("category", "business_insight"))
    severity = str(raw.get("severity", "info"))
    try:
        confidence = max(0.0, min(1.0, float(raw.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0

    return {
        "id": f"aicard:{center['graphKey']}:{raw.get('id') or index}",
        "nodeKey": center["graphKey"],
        "category": category,
        "severity": severity,
        "title": str(raw.get("title", "")),
        "summary": str(raw.get("summary", "")),
        "businessQuestion": str(raw.get("businessQuestion", "")),
        "businessImpact": str(raw.get("businessImpact", "")),
        "confidence": confidence,
        "evidencePath": evidence_keys,
        "sourceDocuments": source_documents,
        "sourceTables": _labels(_TABLE_TYPES),
        "sourceQueries": _labels(_QUERY_TYPES),
        "sourceDashboards": _labels(_DASH_TYPES),
        "supportedKpis": supported_kpis,
        "recommendedAction": str(raw.get("recommendedAction", "")),
        "traceToEvidence": {
            "nodeIds": list(evidence_ids),
            "edgeIds": edge_ids,
            "nodeKeys": evidence_keys,
        },
        "aiGenerated": True,
    }


async def enrich_payload_with_ai(
    payload: dict[str, Any],
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
) -> dict[str, Any]:
    """Replace deterministic insight cards with AI-generated cards when possible.

    Mutates and returns ``payload``. Falls back silently to the deterministic
    cards already present whenever the AI server is unavailable or returns no
    usable cards.
    """
    if not ai.is_enabled():
        return payload
    center = payload.get("centerNode")
    if not center or not payload.get("nodes"):
        return payload

    center_payload, neighbors, documents, kpis = _build_ai_request(payload)
    if not neighbors:
        return payload

    try:
        raw_cards = await ai.knowledge_graph_cards(
            tenant_id=tenant_id,
            user_id=user_id,
            project_id=project_id,
            lens=str(payload.get("lens") or "insight-first"),
            center=center_payload,
            neighbors=neighbors,
            documents=documents,
            kpis=kpis,
            max_cards=8,
        )
    except Exception as exc:  # never let AI break the graph
        logger.warning("KG AI enrichment failed: %s", exc)
        return payload

    if not raw_cards:
        return payload

    nodes_by_key = {n["graphKey"]: n for n in payload["nodes"]}
    edges = payload["edges"]
    cards: list[dict[str, Any]] = []
    for i, raw in enumerate(raw_cards):
        if not isinstance(raw, dict):
            continue
        card = _map_card(
            raw, index=i, center=center, nodes_by_key=nodes_by_key, edges=edges,
        )
        if card:
            cards.append(card)

    if not cards:
        return payload

    payload["insightCards"] = cards
    payload["tracePaths"] = [
        {
            "id": f"trace:{c['id']}",
            "fromNodeKey": c["nodeKey"],
            "nodeIds": c["traceToEvidence"]["nodeIds"],
            "edgeIds": c["traceToEvidence"]["edgeIds"],
        }
        for c in cards
    ]
    payload["aiGenerated"] = True
    payload["pipeline_version"] = PIPELINE_VERSION_AI
    return payload
