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
import re
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


# KG-37: common English words excluded from the question keyword set so a
# question like "what is the status of on-time delivery?" ranks on
# "status"/"on-time"/"delivery", not "what"/"is"/"the"/"of".
_QUESTION_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "of", "in", "on", "at", "to", "for", "and", "or", "but", "with", "by",
    "what", "which", "who", "whom", "how", "why", "when", "where",
    "does", "do", "did", "can", "could", "should", "would", "will",
    "this", "that", "these", "those", "our", "us", "we", "me", "my",
    "show", "tell", "give", "get", "about",
})


def _question_keywords(question: str | None) -> frozenset[str]:
    """KG-37: a small, explainable keyword set extracted from a free-text
    question -- lowercased word tokens with stopwords and single/double
    letter words dropped. No embeddings/ML: a caller with no question
    (or one that yields no keywords) gets ``frozenset()``, which makes
    ``_ranked`` fall back to its original confidence-only ordering exactly.
    """
    if not question:
        return frozenset()
    words = re.findall(r"[a-z0-9]+", question.lower())
    return frozenset(w for w in words if len(w) > 2 and w not in _QUESTION_STOPWORDS)


def _question_relevance(item: dict[str, Any], keywords: frozenset[str]) -> float:
    """Fraction of question keywords appearing in this item's own text."""
    if not keywords:
        return 0.0
    hay = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    hits = sum(1 for kw in keywords if kw in hay)
    return hits / len(keywords)


def _ranked(
    items: list[dict[str, Any]],
    limit: int,
    *,
    keywords: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Question-relevance first (when a question was asked), then
    highest-confidence, capped, deduped by title.

    KG-37: previously this only ever ranked by the node's own static
    confidence, so a question like "what's blocking on-time delivery?"
    could see its most relevant risk pushed out of a capped bucket by an
    unrelated but higher-confidence one. ``keywords`` (from
    ``_question_keywords``) is empty for any caller that has no question
    text, which reduces the sort key back to confidence-only -- identical
    to the previous behavior.
    """
    def sort_key(it: dict[str, Any]) -> tuple[float, float]:
        return (_question_relevance(it, keywords), it.get("confidence") or 0.0)

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for it in sorted(items, key=sort_key, reverse=True):
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
    question: str | None = None,
) -> dict[str, Any]:
    """Return a compact Knowledge Graph context block for AI generation.

    The block is safe to embed in an AI request: it is summarized, ranked by
    confidence, deduped, and scoped to the authorized tenant/project graph.

    KG-37: ``question`` is the user's free-text prompt/ask, when the calling
    surface has one. When given, each bucket is ranked by relevance to the
    question's own keywords first, confidence second, instead of confidence
    alone -- so a capped bucket keeps the items that actually answer what was
    asked. Omitting it (the default) keeps the original confidence-only
    ranking exactly.

    KG-07: ``surface`` names the feature this context is generated for
    (business_insights | project_insights | dashboard_generation |
    query_generation) -- every call records which node, document, and query
    ids actually ended up in the returned context to
    ``knowledge_graph_evidence_access``, so an administrator can later
    reconstruct exactly what evidence informed that feature's answer for
    this tenant/project/user.

    KG-50: the same record is also returned inline as ``kg_grounding``
    (``{"kgVersionId", "nodeIds", "documentIds", "queryIds"}``, or ``None``
    when there's nothing to ground on) so the caller can attach it to its
    own response envelope directly -- proving which KG version and evidence
    grounded *this* answer doesn't require a separate audit-table query.

    KG-39: the returned block always carries ``grounding_status`` --
    ``"ok"`` for both a real result and a project that legitimately has no
    Knowledge Graph content yet, ``"unavailable"`` only when loading the
    graph itself failed. Previously both cases returned the identical empty
    shape, so a caller (and, transitively, whatever it generates) could never
    tell "this project has no KG-worthy content" apart from "the KG failed to
    load and this answer has no grounding at all" -- callers should degrade
    visibly (surface a note, log distinctly) rather than silently proceed as
    if fully grounded.
    """
    empty: dict[str, Any] = {
        "risks": [], "opportunities": [], "gaps": [], "warnings": [],
        "recommended_kpis": [], "measured_kpis": [],
        "governing_documents": [], "reference_guidance": [],
        "processes": [], "entities": [],
        "query_lineage": [], "dashboard_lineage": [],
        "datasource_relationships": [],
        "grounding_status": "ok",
        # KG-50: the active KG version + evidence ids that grounded this
        # context, so a caller can attach them to its own response envelope.
        # None when there is no graph content to ground on.
        "kg_grounding": None,
        # KG-38: per-bucket {"available", "selected"} counts, empty here
        # because there was nothing to count for either an unavailable or a
        # legitimately empty graph.
        "context_coverage": {},
    }

    try:
        raw_nodes, raw_edges = await _load_stored_graph(
            session, tenant_id=tenant_id, project_id=project_id,
        )
    except Exception:  # context is best-effort; never block AI gen
        logger.warning(
            "KG grounding degraded: failed to load graph for %s "
            "(tenant=%s project=%s) -- proceeding without KG context",
            surface, tenant_id, project_id, exc_info=True,
        )
        return {**empty, "grounding_status": "unavailable"}

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

    keywords = _question_keywords(question)
    kpi_cap = max(3, max_items // 2)
    bucketed = {
        "risks": _ranked(risks, max_items, keywords=keywords),
        "opportunities": _ranked(opportunities, max_items, keywords=keywords),
        "gaps": _ranked(gaps, max_items, keywords=keywords),
        "warnings": _ranked(warnings, max_items, keywords=keywords),
        "recommended_kpis": _ranked(recommended_kpis, kpi_cap, keywords=keywords),
        "measured_kpis": _ranked(measured_kpis, kpi_cap, keywords=keywords),
        "governing_documents": _ranked(governing_documents, max_items, keywords=keywords),
        "reference_guidance": _ranked(reference_guidance, max_items, keywords=keywords),
        "processes": _ranked(processes, max_items, keywords=keywords),
        "entities": _ranked(entities, max_items, keywords=keywords),
    }
    lineage = {
        "query_lineage": query_lineage[:max_items],
        "dashboard_lineage": dashboard_lineage[:max_items],
        "datasource_relationships": datasource_relationships[:max_items],
    }

    # KG-38: a caller could never previously tell "the graph had nothing to
    # say here" apart from "there was more evidence than fit in this
    # request's cap" -- both looked like the same short bucket. Counting the
    # raw candidate list before ranking/capping against what actually made it
    # through makes truncation visible instead of silent.
    raw_by_bucket: dict[str, list[dict[str, Any]]] = {
        "risks": risks, "opportunities": opportunities, "gaps": gaps,
        "warnings": warnings, "recommended_kpis": recommended_kpis,
        "measured_kpis": measured_kpis, "governing_documents": governing_documents,
        "reference_guidance": reference_guidance, "processes": processes,
        "entities": entities, "query_lineage": query_lineage,
        "dashboard_lineage": dashboard_lineage,
        "datasource_relationships": datasource_relationships,
    }
    selected_by_bucket: dict[str, list[dict[str, Any]]] = {**bucketed, **lineage}
    context_coverage = {
        key: {"available": len(raw_by_bucket[key]), "selected": len(selected_by_bucket[key])}
        for key in raw_by_bucket
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
    recorded = await record_kg_evidence_access(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        surface=surface,
        node_ids=audit_node_ids,
        document_ids=document_ids,
        query_ids=query_ids,
    )
    kg_grounding = (
        {
            "kgVersionId": recorded["kg_version_id"],
            "nodeIds": recorded["node_ids"],
            "documentIds": recorded["document_ids"],
            "queryIds": recorded["query_ids"],
        }
        if recorded is not None
        else None
    )

    for items in bucketed.values():
        for item in items:
            item.pop("_id", None)
    for items in lineage.values():
        for item in items:
            item.pop("_ids", None)

    return {
        **bucketed, **lineage,
        "grounding_status": "ok",
        "kg_grounding": kg_grounding,
        "context_coverage": context_coverage,
    }
