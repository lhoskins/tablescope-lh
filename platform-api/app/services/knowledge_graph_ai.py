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

from app.models.reference_library import TIER_COMPANY, TIER_PROJECT
from app.services import ai_intelligence_client as ai
from app.services.evidence_severity import REFERENCE_NODE_TYPES, gate_severity

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


_EVIDENCE_FIELDS = (
    "evidenceKeys", "sourceDocuments", "sourceTables", "sourceQueries",
    "sourceDashboards", "supportedKpis", "linkedNodes", "evidencePath",
)


def _resolve_evidence_keys(
    raw: dict[str, Any],
    nodes_by_key: dict[str, dict[str, Any]],
    nodes: list[dict[str, Any]],
) -> list[str]:
    """Resolve an AI card's evidence references to real graph keys.

    The AI may return graph keys, but also plain labels or source document /
    query / dashboard / KPI names. Match (in priority order) on: exact graph
    key, case-insensitive graph key, exact node label, case-insensitive node
    label. Only references that map to a real graph node are accepted — evidence
    that can't be grounded is dropped (never fabricated).
    """
    key_ci = {k.lower(): k for k in nodes_by_key}
    label_exact: dict[str, str] = {}
    label_ci: dict[str, str] = {}
    for n in nodes:
        label = str(n.get("label") or "").strip()
        if label:
            label_exact.setdefault(label, n["graphKey"])
            label_ci.setdefault(label.lower(), n["graphKey"])

    resolved: list[str] = []
    seen: set[str] = set()
    for field in _EVIDENCE_FIELDS:
        for raw_val in raw.get(field, []) or []:
            val = str(raw_val).strip()
            if not val:
                continue
            gk = (
                val if val in nodes_by_key
                else key_ci.get(val.lower())
                or label_exact.get(val)
                or label_ci.get(val.lower())
            )
            if gk and gk not in seen:
                seen.add(gk)
                resolved.append(gk)
    return resolved


def _evidence_strength(
    evidence_nodes: list[dict[str, Any]],
    grounding_edges: list[dict[str, Any]],
    *,
    has_project_evidence: bool,
) -> float:
    """KG-31: an independent 0-1 evidence-quality score, derived only from the
    card's own grounded evidence (never from the model's self-reported
    confidence) -- how much real support this claim actually has, separate
    from how confident the model says it is.

    Deliberately simple and explainable rather than learned/calibrated:
    - a single evidence node is weaker support than several converging ones;
    - evidence resting only on Reference Library guidance (no project data)
      is weaker than evidence that includes the project's own data;
    - the structural confidence already recorded on the grounding edges
      (from deterministic collection, not the LLM) factors in directly.
    """
    if not evidence_nodes:
        return 0.0
    node_count_score = min(1.0, len(evidence_nodes) / 3.0)
    project_evidence_score = 1.0 if has_project_evidence else 0.5
    if grounding_edges:
        edge_confidences = [float(e.get("confidence") or 0.0) for e in grounding_edges]
        edge_score = sum(edge_confidences) / len(edge_confidences)
    else:
        # No structural edge ties the evidence directly together/to the
        # center -- evidence was matched by label/reference only.
        edge_score = 0.5
    return round(
        max(0.0, min(1.0, (node_count_score + project_evidence_score + edge_score) / 3)),
        4,
    )


def _map_card(
    raw: dict[str, Any],
    *,
    index: int,
    center: dict[str, Any],
    nodes_by_key: dict[str, dict[str, Any]],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Map an AI card onto the platform card shape, grounding it in real nodes."""
    evidence_keys = _resolve_evidence_keys(raw, nodes_by_key, nodes)
    if not evidence_keys:
        logger.info("KG AI card rejected: no matching evidenceKeys (%s)", raw.get("title"))
        return None

    evidence_nodes = [nodes_by_key[k] for k in evidence_keys]
    # KG-34: an order-preserving sequence (center first, then each evidence
    # node in the order it was resolved) -- a plain set here had no
    # guaranteed order at all, so a "trace path" built from it couldn't be
    # a real, reproducible sequence.
    evidence_ids = list(dict.fromkeys([center["id"], *[n["id"] for n in evidence_nodes]]))
    evidence_id_set = set(evidence_ids)
    grounding_edges = [
        e for e in edges
        if e["source"] in evidence_id_set and e["target"] in evidence_id_set
    ]
    edge_ids = [e["id"] for e in grounding_edges]
    hops = [
        {
            "fromNodeId": e["source"],
            "toNodeId": e["target"],
            "relationshipType": e.get("type") or "",
        }
        for e in grounding_edges
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
    # Reference Library docs are authoritative guidance, not project evidence:
    # a card grounded only in reference documents may not exceed watch severity.
    has_project_evidence = any(
        n["type"] not in REFERENCE_NODE_TYPES for n in evidence_nodes
    )
    # KG-36: approved company policy and project-tier reference documents rank
    # above generic industry references in the stated source-authority order,
    # so a card grounded only in one of those shouldn't be capped the same way
    # as one grounded only in a generic industry standard. A reference
    # document with no tier recorded at all is not proof of authority -- only
    # an explicit company/project tier counts.
    has_authoritative_non_industry_evidence = any(
        n["type"] in REFERENCE_NODE_TYPES
        and n["properties"].get("tier") in (TIER_COMPANY, TIER_PROJECT)
        for n in evidence_nodes
    )
    severity = gate_severity(
        str(raw.get("severity", "info")),
        has_project_evidence=has_project_evidence,
        has_authoritative_non_industry_evidence=has_authoritative_non_industry_evidence,
    )
    try:
        model_confidence = max(0.0, min(1.0, float(raw.get("confidence", 0.0))))
    except (TypeError, ValueError):
        model_confidence = 0.0

    evidence_strength = _evidence_strength(
        evidence_nodes, grounding_edges, has_project_evidence=has_project_evidence,
    )
    # KG-31: a card's overall confidence can never exceed what its own
    # evidence supports -- a high self-reported model score can't make a
    # weakly-evidenced claim look authoritative. reviewer_confidence is
    # schema-ready for a future human-review workflow; nothing populates it
    # yet, so it stays None rather than a fabricated placeholder value.
    confidence = min(model_confidence, evidence_strength)

    return {
        "id": f"aicard:{center['graphKey']}:{raw.get('id') or index}",
        "nodeKey": center["graphKey"],
        "category": category,
        "severity": severity,
        "title": str(raw.get("title", "")),
        "summary": str(raw.get("summary", "")),
        "businessQuestion": str(raw.get("businessQuestion", "")),
        "businessImpact": str(raw.get("businessImpact", "")),
        "valid": True,
        "confidence": confidence,
        "modelConfidence": model_confidence,
        "evidenceStrength": evidence_strength,
        "reviewerConfidence": None,
        "evidencePath": evidence_keys,
        "sourceDocuments": source_documents,
        "sourceTables": _labels(_TABLE_TYPES),
        "sourceQueries": _labels(_QUERY_TYPES),
        "sourceDashboards": _labels(_DASH_TYPES),
        "supportedKpis": supported_kpis,
        "recommendedAction": str(raw.get("recommendedAction", "")),
        "traceToEvidence": {
            "nodeIds": evidence_ids,
            "edgeIds": edge_ids,
            "nodeKeys": evidence_keys,
            "hops": hops,
        },
        "aiGenerated": True,
    }


def _clear_cards(payload: dict[str, Any]) -> dict[str, Any]:
    """KG-40: AI enrichment is unavailable or rejected every result -- fall
    back to the deterministic, evidence-grounded structural cards
    ``build_graph_payload`` already computed into this same ``payload``
    (``insightCards``/``tracePaths`` are left untouched) instead of wiping
    them to an empty list. ``aiGenerated`` still reports whether the
    cards currently shown are AI-enriched (``False`` here); the new
    ``aiEnrichmentStatus`` (mirroring KG-39's ``grounding_status``
    convention) reports *why* separately, so a caller/UI can show "AI
    enrichment unavailable, showing structural relationships" rather than
    an unexplained empty panel or, worse, confusing structural fallback
    content for a fully AI-enriched result.
    """
    payload["aiGenerated"] = False
    payload["aiEnrichmentStatus"] = "unavailable"
    return payload


async def enrich_payload_with_ai(
    payload: dict[str, Any],
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
) -> dict[str, Any]:
    """Generate the insight cards for a payload from the AI server only.

    Mutates and returns ``payload``. Insight cards are produced solely by the
    AI server — there is no deterministic fallback. If the AI server is
    disabled, unreachable, or returns no card that grounds to a real graph
    node, the payload's insight cards are cleared (the panel shows no cards
    rather than deterministic placeholders).
    """
    if not ai.is_enabled():
        return _clear_cards(payload)
    center = payload.get("centerNode")
    if not center or not payload.get("nodes"):
        return _clear_cards(payload)

    center_payload, neighbors, documents, kpis = _build_ai_request(payload)
    if not neighbors:
        return _clear_cards(payload)

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
    except Exception as exc:  # AI failure → no cards (no deterministic fallback)
        logger.warning("KG AI enrichment failed: %s", exc)
        return _clear_cards(payload)

    if not raw_cards:
        return _clear_cards(payload)

    nodes_by_key = {n["graphKey"]: n for n in payload["nodes"]}
    nodes = payload["nodes"]
    edges = payload["edges"]
    cards: list[dict[str, Any]] = []
    for i, raw in enumerate(raw_cards):
        if not isinstance(raw, dict):
            continue
        card = _map_card(
            raw, index=i, center=center, nodes_by_key=nodes_by_key,
            nodes=nodes, edges=edges,
        )
        if card:
            cards.append(card)

    if not cards:
        # AI returned cards but none grounded to real graph nodes — show no
        # cards (no deterministic fallback).
        logger.info(
            "KG AI enrichment returned cards but none were grounded in current graph nodes"
        )
        return _clear_cards(payload)

    payload["insightCards"] = cards
    payload["tracePaths"] = [
        {
            "id": f"trace:{c['id']}",
            "fromNodeKey": c["nodeKey"],
            "nodeIds": c["traceToEvidence"]["nodeIds"],
            "edgeIds": c["traceToEvidence"]["edgeIds"],
            "hops": c["traceToEvidence"].get("hops", []),
        }
        for c in cards
    ]
    payload["aiGenerated"] = True
    payload["aiEnrichmentStatus"] = "ok"
    payload["pipeline_version"] = PIPELINE_VERSION_AI
    return payload
