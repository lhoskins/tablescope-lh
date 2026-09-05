"""Knowledge graph payload rendering from raw nodes/edges."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from .cards import (
    _build_card_for_node,
    _build_gap_finding,
    _center_overview_card,
    _kpi_measurement_gap_card,
    _overlay_card_bundle,
    _rank_and_dedupe_cards,
)
from .classifier import (
    _classify_relationship,
    _edge_confidence,
    _evidence_summary,
)
from .constants import (
    _ACTION_TYPES,
    _GAP_TYPES,
    _INSIGHT_TYPES,
    DEFAULT_MIN_CONFIDENCE,
    INFERRED_FLOOR,
    PIPELINE_VERSION,
)
from .loader import _is_canvas_hidden, _neighborhood, _pick_center, enrich_node

logger = logging.getLogger(__name__)

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
    enriched_all = [enrich_node(n) for n in raw_nodes]
    # The project hub stays the data boundary but is never drawn: drop it from
    # the visible node set so it can't be a center or appear on the canvas.
    hidden_ids = {n["id"] for n in enriched_all if _is_canvas_hidden(n)}
    enriched = [n for n in enriched_all if n["id"] not in hidden_ids]
    nodes_by_id = {n["id"]: n for n in enriched}

    floor = INFERRED_FLOOR if include_inferred else min_confidence
    norm_edges: list[dict[str, Any]] = []
    hub_edges: list[dict[str, Any]] = []
    for e in raw_edges:
        f, t = e["from_node_id"], e["to_node_id"]
        f_hidden, t_hidden = f in hidden_ids, t in hidden_ids
        if f_hidden and t_hidden:
            continue  # hub-to-hub edge, never relevant
        if f_hidden or t_hidden:
            hub_edges.append(e)  # re-rooted onto the center below
            continue
        if f not in nodes_by_id or t not in nodes_by_id:
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

    # Re-root the hidden project hub's structural edges onto the center so the
    # project's documents, reference library, data sources, queries and
    # dashboards stay visible and radiate from the focal node (not the project).
    if hub_edges:
        existing_pairs: set[tuple[Any, Any]] = set()
        for e in norm_edges:
            existing_pairs.add((e["from_node_id"], e["to_node_id"]))
            existing_pairs.add((e["to_node_id"], e["from_node_id"]))
        for e in hub_edges:
            asset_id = e["to_node_id"] if e["from_node_id"] in hidden_ids else e["from_node_id"]
            if asset_id not in nodes_by_id or asset_id == center["id"]:
                continue
            if (center["id"], asset_id) in existing_pairs:
                continue
            existing_pairs.add((center["id"], asset_id))
            existing_pairs.add((asset_id, center["id"]))
            norm_edges.append({
                **e,
                "from_node_id": center["id"],
                "to_node_id": asset_id,
            })

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
                    "hops": card["traceToEvidence"].get("hops", []),
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

    # KPI measurement-gap card: when the centred KPI has no query or dashboard
    # measuring it, surface a gap (no fabricated evidence — it's a real
    # coverage gap derived from the KPI's own connections).
    if center["type"] in ("kpi", "metric"):
        kpi_gap = _kpi_measurement_gap_card(center, kept_edges, kept_by_id)
        if kpi_gap:
            cards.append(kpi_gap)
            gaps.append({
                "id": f"gap:kpi:{center['graphKey']}",
                "nodeKey": center["graphKey"],
                "title": kpi_gap["title"],
                "summary": kpi_gap["summary"],
                "severity": kpi_gap["severity"],
                "confidence": kpi_gap["confidence"],
            })

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


def _edge_payload(edge: dict[str, Any], nodes_by_id: dict[Any, dict[str, Any]]) -> dict[str, Any]:
    src = nodes_by_id.get(edge["from_node_id"])
    tgt = nodes_by_id.get(edge["to_node_id"])
    classification = _classify_relationship(edge, src, tgt)
    return {
        "id": edge["id"],
        "source": edge["from_node_id"],
        "target": edge["to_node_id"],
        "type": edge.get("relationship_type") or edge.get("edge_type") or "",
        "confidence": _edge_confidence(edge),
        "evidence": _evidence_summary(edge),
        **classification,
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

    Does not re-collect the structural graph and never calls the AI server. The
    insight cards come solely from the centre's cached AI bundle (keyed by graph
    key); a centre with no cached cards shows none (AI-only — no deterministic
    fallback). Both canvas and cards are served entirely from the snapshot.
    """
    full = snapshot.get("fullGraph") or {"nodes": [], "edges": []}
    nodes = full.get("nodes", [])
    edges = full.get("edges", [])
    by_center = snapshot.get("aiCardsByCenter") or {}

    # When no explicit centre is requested, prefer a centre that actually has
    # AI-generated insight cards so the initial canvas load is useful. If the
    # default centre has cards we keep it; otherwise fall back to the centre
    # with the richest cached bundle.
    chosen_center = center_node
    if not chosen_center and by_center:
        first_payload = build_graph_payload(
            nodes, edges,
            center_node=None,
            lens=lens,
            min_confidence=min_confidence,
            include_inferred=include_inferred,
            severity=severity,
        )
        default_center = first_payload.get("centerNode")
        default_key = default_center.get("graphKey") if default_center else None
        default_bundle = by_center.get(default_key) if default_key else None
        if not (default_bundle and default_bundle.get("insightCards")):
            best_key = max(
                by_center,
                key=lambda k: len((by_center[k] or {}).get("insightCards", [])),
                default=None,
            )
            if best_key:
                chosen_center = best_key

    payload = build_graph_payload(
        nodes,
        edges,
        center_node=chosen_center,
        lens=lens,
        min_confidence=min_confidence,
        include_inferred=include_inferred,
        severity=severity,
    )
    center = payload.get("centerNode")
    bundle = by_center.get(center.get("graphKey")) if center else None
    if bundle:
        _overlay_card_bundle(payload, bundle)
    else:
        # KG-40: no cached AI bundle for this centre (never enriched, or
        # enrichment hasn't run since the last rebuild) -- keep the
        # deterministic structural cards `build_graph_payload` already
        # computed above rather than wiping them to an empty list.
        payload["aiGenerated"] = False
        payload["aiEnrichmentStatus"] = "unavailable"
    return payload


# ── Async DB wrapper ─────────────────────────────────────────────────

