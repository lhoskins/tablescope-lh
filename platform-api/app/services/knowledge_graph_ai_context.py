"""Knowledge Graph context collector for AI dashboard / query generation.

Produces a compact, AI-safe summary of the project's Knowledge Graph — risks,
opportunities, gaps, warnings, recommended vs. measured KPIs, governing
documents, reference guidance, processes, entities, and query/dashboard/
datasource lineage — so the AI server can generate dashboards and queries that
answer the business questions the graph surfaces (instead of merely summarizing
tables).

Everything here is derived from the project's *own* authorized graph (the stored
AI graph rows merged with the structural Evidence graph). Nothing is fabricated:
each item maps to a real node the user owns, summarized, ranked, and deduped.
Reference Library documents are reported as guidance only — never as queryable
datasources.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.kg_evidence_audit import evidence_ids_from_nodes, record_kg_evidence_access
from app.services.knowledge_graph_builder import (
    _as_dict,
    _classify_relationship,
    _edge_confidence,
    _load_stored_graph,
    enrich_node,
)

logger = logging.getLogger(__name__)

# Node-type buckets (see prompts/knowledge_graph_insight_best_practices.md).
_RISK_TYPES = {"risk", "audit_finding"}
_WARNING_TYPES = {"warning", "anomaly"}
_OPPORTUNITY_TYPES = {"opportunity"}
_GAP_TYPES = {"gap", "process_gap", "data_gap", "compliance_gap"}
_KPI_TYPES = {"kpi", "metric"}
_GOVERNING_DOC_TYPES = {"document", "policy", "procedure", "standard", "control"}
_REFERENCE_TYPES = {"reference_document"}
_PROCESS_TYPES = {"process"}
_ENTITY_TYPES = {
    "business_entity", "supplier", "customer", "product", "facility", "contract",
}
_QUERY_TYPES = {"query", "saved_query"}
_DASHBOARD_TYPES = {"dashboard"}
_DATASOURCE_TYPES = {"data_source", "datasource", "table"}


def _node_conf(node: dict[str, Any]) -> float:
    c = node.get("confidence")
    try:
        return float(c) if c is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _summary(node: dict[str, Any]) -> str:
    return str(node.get("summary") or node.get("businessValue") or "")[:400]


def _ranked(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Highest-confidence first, capped, deduped by title."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for it in sorted(items, key=lambda x: x.get("confidence") or 0.0, reverse=True):
        title = str(it.get("title") or "").strip().lower()
        if title and title in seen:
            continue
        if title:
            seen.add(title)
        out.append(it)
        if len(out) >= limit:
            break
    return out


async def collect_knowledge_graph_ai_context(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
    user_id: int | None = None,
    max_items: int = 20,
    surface: str = "unspecified",
) -> dict[str, Any]:
    """Return a compact Knowledge Graph context block for AI generation.

    The block is safe to embed in an AI request: it is summarized, ranked by
    confidence, deduped, and scoped to the authorized tenant/project graph.

    KG-07: ``surface`` names the feature this context is generated for
    (business_insights | project_insights | dashboard_generation |
    query_generation) -- every call records which node, document, and query
    ids actually ended up in the returned context to
    ``knowledge_graph_evidence_access``, so an administrator can later
    reconstruct exactly what evidence informed that feature's answer for
    this tenant/project/user.
    """
    empty: dict[str, Any] = {
        "risks": [], "opportunities": [], "gaps": [], "warnings": [],
        "recommended_kpis": [], "measured_kpis": [],
        "governing_documents": [], "reference_guidance": [],
        "processes": [], "entities": [],
        "query_lineage": [], "dashboard_lineage": [],
        "datasource_relationships": [],
    }

    try:
        raw_nodes, raw_edges = await _load_stored_graph(
            session, tenant_id=tenant_id, project_id=project_id,
        )
    except Exception:  # context is best-effort; never block AI gen
        logger.exception(
            "knowledge_graph_ai_context: failed to load graph (tenant=%s project=%s)",
            tenant_id, project_id,
        )
        return empty

    if not raw_nodes:
        return empty

    nodes = [enrich_node(n) for n in raw_nodes]
    by_id = {n["id"]: n for n in nodes}

    # Adjacency: node id -> list of (neighbor_node, edge) using only edges that
    # would actually display (explicit/inferred connectors), so related items
    # reflect real, non-recommended evidence.
    adj: dict[Any, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    lineage_edges: list[dict[str, Any]] = []
    for e in raw_edges:
        s = by_id.get(e.get("from_node_id"))
        t = by_id.get(e.get("to_node_id"))
        if s is None or t is None:
            continue
        cls = _classify_relationship(e, s, t)
        e_aug = {**e, **cls}
        lineage_edges.append(e_aug)
        if cls["connectorStyle"] in ("solid", "dotted"):
            adj.setdefault(s["id"], []).append((t, e_aug))
            adj.setdefault(t["id"], []).append((s, e_aug))

    def _related(node: dict[str, Any], types: set[str], cap: int = 5) -> list[str]:
        labels: list[str] = []
        for neigh, _e in adj.get(node["id"], []):
            if str(neigh.get("type") or "") in types and neigh.get("label"):
                labels.append(str(neigh["label"]))
        # dedupe preserving order
        out: list[str] = []
        for lbl in labels:
            if lbl not in out:
                out.append(lbl)
            if len(out) >= cap:
                break
        return out

    def _finding(node: dict[str, Any]) -> dict[str, Any]:
        return {
            "_id": node["id"],
            "title": node.get("label") or "",
            "severity": node.get("severity") or "",
            "summary": _summary(node),
            "related_kpis": _related(node, _KPI_TYPES),
            "related_documents": _related(
                node, _GOVERNING_DOC_TYPES | _REFERENCE_TYPES,
            ),
            "related_datasources": _related(node, _DATASOURCE_TYPES),
            "confidence": round(_node_conf(node), 4),
        }

    risks: list[dict[str, Any]] = []
    opportunities: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    recommended_kpis: list[dict[str, Any]] = []
    measured_kpis: list[dict[str, Any]] = []
    governing_documents: list[dict[str, Any]] = []
    reference_guidance: list[dict[str, Any]] = []
    processes: list[dict[str, Any]] = []
    entities: list[dict[str, Any]] = []

    for node in nodes:
        ntype = str(node.get("type") or "")
        props = _as_dict(node.get("properties"))
        if ntype in _RISK_TYPES:
            risks.append(_finding(node))
        elif ntype in _WARNING_TYPES:
            warnings.append(_finding(node))
        elif ntype in _OPPORTUNITY_TYPES:
            opportunities.append(_finding(node))
        elif ntype in _GAP_TYPES:
            gaps.append(_finding(node))
        elif ntype in _KPI_TYPES:
            kpi = {
                "_id": node["id"],
                "title": node.get("label") or "",
                "summary": _summary(node),
                "related_documents": _related(
                    node, _GOVERNING_DOC_TYPES | _REFERENCE_TYPES,
                ),
                "related_datasources": _related(node, _DATASOURCE_TYPES),
                "confidence": round(_node_conf(node), 4),
            }
            status = str(props.get("kpiStatus") or props.get("kpi_status") or "")
            measured_by = _related(node, _QUERY_TYPES | _DASHBOARD_TYPES)
            if status == "measured" or measured_by:
                kpi["measured_by"] = measured_by
                measured_kpis.append(kpi)
            else:
                recommended_kpis.append(kpi)
        elif ntype in _REFERENCE_TYPES:
            reference_guidance.append({
                "_id": node["id"],
                "title": node.get("label") or "",
                "summary": _summary(node),
                "confidence": round(_node_conf(node), 4),
            })
        elif ntype in _GOVERNING_DOC_TYPES:
            governing_documents.append({
                "_id": node["id"],
                "title": node.get("label") or "",
                "summary": _summary(node),
                "confidence": round(_node_conf(node), 4),
            })
        elif ntype in _PROCESS_TYPES:
            processes.append({
                "_id": node["id"],
                "title": node.get("label") or "",
                "summary": _summary(node),
                "related_kpis": _related(node, _KPI_TYPES),
                "confidence": round(_node_conf(node), 4),
            })
        elif ntype in _ENTITY_TYPES:
            entities.append({
                "_id": node["id"],
                "title": node.get("label") or "",
                "type": ntype,
                "confidence": round(_node_conf(node), 4),
            })

    # Lineage: query reads_from datasource / measures kpi; dashboard visualizes.
    query_lineage: list[dict[str, Any]] = []
    dashboard_lineage: list[dict[str, Any]] = []
    datasource_relationships: list[dict[str, Any]] = []
    for e in lineage_edges:
        s = by_id.get(e.get("from_node_id"))
        t = by_id.get(e.get("to_node_id"))
        if s is None or t is None:
            continue
        s_type = str(s.get("type") or "")
        t_type = str(t.get("type") or "")
        rel = str(e.get("relationship_type") or "")
        conf = round(_edge_confidence(e), 4)
        if s_type in _QUERY_TYPES and t_type in (_KPI_TYPES | _DATASOURCE_TYPES):
            query_lineage.append({
                "_ids": (s["id"], t["id"]),
                "query": s.get("label") or "",
                "relationship": rel,
                "target": t.get("label") or "",
                "target_type": t_type,
                "confidence": conf,
            })
        elif s_type in _DASHBOARD_TYPES:
            dashboard_lineage.append({
                "_ids": (s["id"], t["id"]),
                "dashboard": s.get("label") or "",
                "relationship": rel,
                "target": t.get("label") or "",
                "target_type": t_type,
                "confidence": conf,
            })
        elif s_type in _DATASOURCE_TYPES and t_type in _QUERY_TYPES:
            datasource_relationships.append({
                "_ids": (s["id"], t["id"]),
                "datasource": s.get("label") or "",
                "used_by": t.get("label") or "",
                "confidence": conf,
            })

    kpi_cap = max(3, max_items // 2)
    bucketed = {
        "risks": _ranked(risks, max_items),
        "opportunities": _ranked(opportunities, max_items),
        "gaps": _ranked(gaps, max_items),
        "warnings": _ranked(warnings, max_items),
        "recommended_kpis": _ranked(recommended_kpis, kpi_cap),
        "measured_kpis": _ranked(measured_kpis, kpi_cap),
        "governing_documents": _ranked(governing_documents, max_items),
        "reference_guidance": _ranked(reference_guidance, max_items),
        "processes": _ranked(processes, max_items),
        "entities": _ranked(entities, max_items),
    }
    lineage = {
        "query_lineage": query_lineage[:max_items],
        "dashboard_lineage": dashboard_lineage[:max_items],
        "datasource_relationships": datasource_relationships[:max_items],
    }

    # KG-07: audit exactly the node ids that made it into this context (after
    # ranking/capping), not the full candidate set that was merely considered.
    used_node_ids: set[Any] = set()
    for items in bucketed.values():
        used_node_ids.update(item["_id"] for item in items)
    for items in lineage.values():
        for item in items:
            used_node_ids.update(item["_ids"])
    used_nodes = [by_id[nid] for nid in used_node_ids if nid in by_id]
    audit_node_ids, document_ids, query_ids = evidence_ids_from_nodes(used_nodes)
    await record_kg_evidence_access(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        surface=surface,
        node_ids=audit_node_ids,
        document_ids=document_ids,
        query_ids=query_ids,
    )

    for items in bucketed.values():
        for item in items:
            item.pop("_id", None)
    for items in lineage.values():
        for item in items:
            item.pop("_ids", None)

    return {**bucketed, **lineage}
