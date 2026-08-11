"""Knowledge-Graph insight cards for a selected node."""

import logging
import uuid

from fastapi import APIRouter, HTTPException, status

from app.core.activity import update_activity
from app.core.config import settings
from app.core.security import verify_signature
from app.models.schemas import (
    KnowledgeGraphCard,
    KnowledgeGraphInsightRequest,
    KnowledgeGraphInsightResponse,
)
from app.services import context_builder, llm_client
from app.services.context_builder import ContextBuildError
from app.services.prompt_loader import load_prompt_reference

from .ai_shared import _parse_json_response

logger = logging.getLogger(__name__)
router = APIRouter()


_KG_SYSTEM_PROMPT = (
    "You are Tablescope AI acting as a senior business analyst reasoning over a "
    "knowledge graph for ONE project. You are handed a SELECTED node and the "
    "nodes/edges connected to it (documents, policies, processes, KPIs, data "
    "sources, queries, dashboards, entities). Your job is to produce business "
    "insight cards — the same caliber as the AI Home page — but specific to this "
    "node and the data sources related to it in the graph. Ground every card "
    "ONLY in the supplied nodes and relationships; never invent a node, "
    "document, KPI, metric, threshold, or relationship that is not listed. "
    "Every card must cite the graph_keys of the nodes that support it."
)

_KG_CATEGORIES = {
    "business_insight", "opportunity", "risk", "warning", "gap", "recommendation",
}
_KG_SEVERITIES = {"critical", "urgent", "warning", "watch", "opportunity", "info"}


def _build_kg_neighbor_lines(neighbors: list[dict]) -> str:
    if not neighbors:
        return "Connected nodes: (none)\n"
    by_group: dict[str, list[dict]] = {}
    for n in neighbors:
        by_group.setdefault(str(n.get("display_group") or "Related"), []).append(n)
    lines = ["Connected nodes (grouped), each with its relationship to the selected node:"]
    for group, items in by_group.items():
        lines.append(f"\n  {group}:")
        for n in items[:14]:
            rel = str(n.get("relationship") or "related_to")
            direction = str(n.get("direction") or "")
            arrow = (
                "selected→node" if direction == "out"
                else "node→selected" if direction == "in"
                else "linked"
            )
            conf = n.get("confidence")
            conf_str = f", confidence {conf:.2f}" if isinstance(conf, int | float) and conf else ""
            label = str(n.get("label") or "")
            key = str(n.get("graph_key") or "")
            summary = str(n.get("summary") or "")[:140]
            lines.append(
                f"    - [{key}] {label} ({n.get('type', 'node')}) — "
                f"{rel} [{arrow}]{conf_str}"
                + (f" — {summary}" if summary else "")
            )
    return "\n".join(lines) + "\n"


@router.post("/intelligence/knowledge-graph", response_model=KnowledgeGraphInsightResponse)
async def knowledge_graph_insights(
    req: KnowledgeGraphInsightRequest,
) -> KnowledgeGraphInsightResponse:
    """Generate AI-Home-style business-insight cards for a selected graph node.

    Mirrors the AI Home architecture (deterministic evidence in, AI insight out)
    but scoped to a single node's graph neighborhood: the platform passes the
    deterministic node-centric graph and the model reasons over it, grounded in
    the Knowledge Graph Insight Best Practices, to surface insights specific to
    the data sources related to that node.
    """
    request_id = str(uuid.uuid4())
    verify_signature(req.model_dump(exclude={"signature"}, exclude_unset=True), req.signature)

    try:
        ctx = await context_builder.build_context(
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            project_id=req.project_id,
            scope="project",
            question="",
            feature="knowledge_graph",
        )
        context_text = context_builder.context_to_prompt_text(ctx)
    except ContextBuildError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: {e.reason}",
        )

    best_practices = load_prompt_reference("knowledge_graph_insight_best_practices.md")
    best_practices_block = (
        f"Knowledge Graph Insight Best Practices (authoritative policy):\n"
        f"{best_practices}\n\n"
        if best_practices
        else ""
    )

    center = req.center or {}
    allowed_keys = {
        str(n.get("graph_key"))
        for n in req.neighbors
        if n.get("graph_key")
    }
    center_key = str(center.get("graph_key") or "")
    if center_key:
        allowed_keys.add(center_key)

    neighbor_lines = _build_kg_neighbor_lines(req.neighbors)
    doc_lines = ""
    if req.documents:
        doc_lines = "\nGoverning / supporting documents:\n" + "\n".join(
            f"  - {d.get('title', 'document')}: {(d.get('summary') or '')[:240]}"
            for d in req.documents[:20]
        )
    kpi_lines = (
        "\nKPIs in this neighborhood: " + ", ".join(req.kpis[:30])
        if req.kpis
        else ""
    )

    max_cards = max(1, min(req.max_cards, 8))
    prompt = (
        f"{best_practices_block}"
        f"{context_text}\n\n"
        f"SELECTED NODE: [{center_key}] {center.get('label', '')} "
        f"({center.get('type', 'node')}) — {(center.get('summary') or '')[:240]}\n"
        f"Graph lens: {req.lens}\n\n"
        f"{neighbor_lines}"
        f"{doc_lines}"
        f"{kpi_lines}\n\n"
        f"Produce up to {max_cards} knowledge-graph business-insight cards for the "
        "SELECTED node, specific to the data sources, KPIs, queries, dashboards, "
        "documents, and processes related to it above. Cover a mix of card "
        "categories where the evidence supports it: business_insight, "
        "opportunity, risk, warning, gap, recommendation. Rules:\n"
        "- Ground every card ONLY in the connected nodes listed above. Do NOT "
        "invent nodes, documents, KPIs, metrics, thresholds, or relationships.\n"
        "- A 'gap' card is only valid when an authoritative source in the "
        "neighborhood (a policy, procedure, standard, or governing document) "
        "implies something should exist that is missing — name that source.\n"
        "- evidenceKeys MUST be graph_keys copied exactly from the connected "
        "nodes (or the selected node). Drop any card you cannot ground in at "
        "least one real graph_key.\n"
        "- Keep the recommendation and the insight in the flow: when a card "
        "implies an action, fill recommendedAction.\n"
        "- confidence is 0..1, reflecting how strongly the evidence supports the "
        "card.\n\n"
        "Return ONLY a JSON object: {\"cards\": [ {\n"
        "  \"id\": \"c1\",\n"
        "  \"category\": \"business_insight|opportunity|risk|warning|gap|recommendation\",\n"
        "  \"severity\": \"critical|urgent|warning|watch|opportunity|info\",\n"
        "  \"title\": \"short headline\",\n"
        "  \"summary\": \"2-3 sentences, business language, cite the related sources\",\n"
        "  \"businessQuestion\": \"the question this answers\",\n"
        "  \"businessImpact\": \"why it matters to the business\",\n"
        "  \"confidence\": 0.0,\n"
        "  \"recommendedAction\": \"the next action (empty if none)\",\n"
        "  \"evidenceKeys\": [\"graph_key\", ...],\n"
        "  \"sourceDocuments\": [\"document title\", ...],\n"
        "  \"supportedKpis\": [\"kpi name\", ...]\n"
        "} ] }\n\n"
        "OUTPUT FORMAT: respond with this JSON object and nothing else — no "
        "prose, no markdown, no code fences. Begin with { and end with }."
    )

    raw = await llm_client.generate(
        prompt=prompt,
        system_prompt=_KG_SYSTEM_PROMPT,
        model=req.model or settings.reasoning_model,
        temperature=0.2,
        num_ctx=24576,
        response_format="json",
    )

    parsed = _parse_json_response(raw)
    cards: list[KnowledgeGraphCard] = []
    if parsed and isinstance(parsed.get("cards"), list):
        for i, c in enumerate(parsed["cards"][:max_cards]):
            if not isinstance(c, dict):
                continue
            category = str(c.get("category", "business_insight")).lower()
            if category not in _KG_CATEGORIES:
                category = "business_insight"
            severity = str(c.get("severity", "info")).lower()
            if severity not in _KG_SEVERITIES:
                severity = "info"
            # Keep only evidence keys that actually exist in the neighborhood —
            # this is the evidence gate that rejects fabricated grounding.
            # The model may return either graph_keys or node labels; normalize
            # to the canonical graph_key before accepting.
            neighbor_labels = {}
            neighbor_labels_ci = {}
            for n in req.neighbors:
                label = str(n.get("label") or "").strip()
                gk = str(n.get("graph_key") or "").strip()
                if label and gk:
                    neighbor_labels.setdefault(label, gk)
                    neighbor_labels_ci.setdefault(label.lower(), gk)
            center_label = str(center.get("label") or "").strip()
            if center_label and center_key:
                neighbor_labels.setdefault(center_label, center_key)
                neighbor_labels_ci.setdefault(center_label.lower(), center_key)

            def _resolve_evidence_key(k: str) -> str | None:
                k = str(k).strip()
                if not k:
                    return None
                if k in allowed_keys:
                    return k
                if k in neighbor_labels:
                    return neighbor_labels[k]
                return neighbor_labels_ci.get(k.lower())

            evidence_keys = [
                gk for gk in {
                    _resolve_evidence_key(k)
                    for k in c.get("evidenceKeys", [])
                }
                if gk
            ]
            if not evidence_keys:
                logger.info("Dropping KG card with no real evidence: %s", c.get("title"))
                continue
            try:
                confidence = float(c.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0
            title = str(c.get("title", "")).strip()
            if not title:
                continue
            cards.append(
                KnowledgeGraphCard(
                    id=str(c.get("id") or f"c{i + 1}"),
                    category=category,
                    severity=severity,
                    title=title,
                    summary=str(c.get("summary", "")),
                    businessQuestion=str(c.get("businessQuestion", "")),
                    businessImpact=str(c.get("businessImpact", "")),
                    confidence=max(0.0, min(1.0, confidence)),
                    recommendedAction=str(c.get("recommendedAction", "")),
                    evidenceKeys=evidence_keys,
                    sourceDocuments=[
                        str(d) for d in c.get("sourceDocuments", []) if d
                    ],
                    supportedKpis=[str(k) for k in c.get("supportedKpis", []) if k],
                )
            )
    else:
        logger.warning("Failed to parse KG insight cards: %s", raw[:200])

    update_activity(req.user_id, req.tenant_id, req.project_id)
    return KnowledgeGraphInsightResponse(
        cards=cards,
        request_id=request_id,
        model_used=req.model or settings.reasoning_model,
    )
