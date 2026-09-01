"""The project-scoped executive Project Insight report."""

import uuid
from typing import Any

from fastapi import APIRouter

from app.core.activity import update_activity
from app.core.config import settings
from app.core.security import verify_signature
from app.models.schemas import (
    ProjectInsightExecutiveSummary,
    ProjectInsightRequest,
    ProjectInsightResponse,
)
from app.services import llm_client
from app.services.kg_context import format_knowledge_graph_context
from app.services.prompt_loader import load_prompt_reference

from .ai_shared import _parse_json_response

router = APIRouter()


_PROJECT_INSIGHT_SYSTEM_PROMPT = (
    "You are the Tablescope Project Insight analyst. You analyze ONE selected "
    "project and produce concise, evidence-based, business-oriented insight "
    "scoped only to that project. Never summarize the tenant or other projects. "
    "Ground every finding in the supplied project context (metadata, tables, "
    "documents, saved queries, dashboards, KPIs, Knowledge Graph). Do not invent "
    "data, metrics, thresholds, or relationships. Recommended dashboards, "
    "queries, and KPIs are suggestions and do not need to already exist. Never "
    "fabricate KPI values — mark unmeasurable KPIs as missing_data or "
    "recommended. Return ONLY the requested JSON object."
)


def _lines(items: list[str], limit: int) -> str:
    picked = [str(i).strip() for i in items if str(i).strip()][:limit]
    return "\n".join(f"  - {i}" for i in picked) if picked else "  (none)"


def _str_list(value: Any, limit: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _dict_list(value: Any, limit: int) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [d for d in value if isinstance(d, dict)][:limit]


@router.post("/intelligence/project-insight", response_model=ProjectInsightResponse)
async def project_insight(req: ProjectInsightRequest) -> ProjectInsightResponse:
    """Generate the project-scoped executive Project Insight report.

    Distinct from Business Insight (tenant-wide): this uses the Project Insight
    Best Practices prompt and reasons over ONLY the selected project's
    authorized context. Recommended dashboards/queries/KPIs are AI suggestions.
    """
    request_id = str(uuid.uuid4())
    verify_signature(req.model_dump(exclude={"signature"}, exclude_unset=True), req.signature)

    best_practices = load_prompt_reference("project_insight_best_practices.md")
    best_practices_block = (
        f"Project Insight Best Practices (authoritative policy):\n{best_practices}\n\n"
        if best_practices
        else ""
    )

    project = req.project or {}
    table_lines = _lines(
        [
            f"{t.get('name', '')} ({t.get('kind', 'table')}): "
            f"{', '.join(str(c) for c in (t.get('columns') or [])[:12])}"
            for t in req.tables
            if isinstance(t, dict) and t.get("name")
        ],
        40,
    )
    doc_lines = _lines(
        [
            f"{d.get('title', 'document')}: {(d.get('summary') or '')[:200]}"
            for d in req.documents
            if isinstance(d, dict)
        ],
        30,
    )
    query_lines = _lines(
        [
            f"{q.get('name', 'query')}: {(q.get('description') or '')[:160]}"
            for q in req.queries
            if isinstance(q, dict)
        ],
        30,
    )
    dashboard_lines = _lines(
        [str(d.get("name") or d.get("title") or "") for d in req.dashboards
         if isinstance(d, dict)],
        20,
    )
    kpi_line = ", ".join(str(k) for k in req.kpis[:30]) if req.kpis else "(none)"
    kg_block = format_knowledge_graph_context(req.knowledge_graph_context)
    kg_block = f"\n{kg_block}\n" if kg_block else ""

    prompt = (
        f"{best_practices_block}"
        f"SELECTED PROJECT: {project.get('name', 'this project')} "
        f"(status: {project.get('status', 'unknown')})\n\n"
        f"Project tables:\n{table_lines}\n\n"
        f"Project documents:\n{doc_lines}\n\n"
        f"Project saved queries:\n{query_lines}\n\n"
        f"Project dashboards:\n{dashboard_lines}\n\n"
        f"Project KPIs: {kpi_line}\n"
        f"{kg_block}\n"
        "Produce a Project Insight report for the SELECTED project only. Use "
        "clear business language, be concise, and ground everything in the "
        "context above. Recommended dashboards/queries/KPIs are suggestions and "
        "do not need to already exist. Do not fabricate KPI values.\n\n"
        "Return ONLY a JSON object with EXACTLY these keys. Replace every "
        "descriptive placeholder below with real, project-specific content "
        "drawn from the context above — never echo the placeholder text and "
        "never leave a primary field (question, label, title, name) blank.\n"
        "{\n"
        '  "executiveSummary": {\n'
        '    "summary": "2-4 sentence project status summary",\n'
        '    "critical": ["short bullet", ...],\n'
        '    "warnings": ["short bullet", ...],\n'
        '    "opportunities": ["short bullet", ...],\n'
        '    "recommendations": ["short bullet", ...]\n'
        "  },\n"
        '  "questionsToAsk": [{"id":"q1","question":"<a real, specific question '
        'about THIS project\'s data>","reason":"<why it matters>",'
        '"suggestedAction":"ask_project"}],\n'
        '  "trendDetection": [{"id":"t1","label":"<short descriptive trend name '
        'derived from the actual trend, e.g. Rising Late Deliveries>",'
        '"title":"<one-line headline>","description":"<what the trend shows>",'
        '"possibleCause":"<likely cause>","sourceSummary":"<evidence>",'
        '"chartLink":"","confidence":0.0}],\n'
        '  "recommendedDashboards": [{"id":"d1","title":"<specific dashboard '
        'name>","description":"<what it shows>","reason":"<why>",'
        '"status":"suggested","confidence":0.0,"backingSignals":[],'
        '"suggestedWidgets":[],"action":"generate"}],\n'
        '  "recommendedQueries": [{"id":"rq1","title":"<specific query name>",'
        '"businessQuestion":"<the question it answers>","reason":"<why>",'
        '"status":"suggested","confidence":0.0,"backingSignals":[],'
        '"recommendedTables":[],"recommendedKpis":[],"action":"generate"}],\n'
        '  "recommendedKpis": [{"id":"k1","name":"<specific KPI name>",'
        '"description":"<what it measures>","status":"recommended",'
        '"currentValue":null,"targetValue":null,"unit":"","reason":"<why>",'
        '"confidence":0.0,"backingSignals":[],"relatedDashboards":[],'
        '"relatedQueries":[],"relatedDataSources":[]}],\n'
        '  "insightValidationWorkflow": [{"id":"i1","title":"<specific insight '
        'title>","type":"risk","priority":"medium","confidence":0.0,'
        '"status":"new","evidenceSummary":"<evidence>","recommendedAction":""}]\n'
        "}\n\n"
        "RULES:\n"
        "- Provide 3-6 questionsToAsk, each a real question tied to this "
        "project's tables, documents, queries, or KPIs.\n"
        "- trendDetection: include a trend only when the context supports it, "
        "and give it a descriptive label derived from the actual trend (never "
        "'Trend A' or any generic placeholder).\n"
        "- Every recommendedDashboards / recommendedQueries / recommendedKpis / "
        "insightValidationWorkflow item MUST have a concrete title/name; omit "
        "any item you cannot name specifically rather than emitting a blank.\n"
        "- Do NOT return items whose question/label/title/name is empty — "
        "return an empty array for that section instead.\n"
        "- Do NOT fabricate KPI values; use null when unknown.\n\n"
        "OUTPUT FORMAT: respond with this JSON object and nothing else — no "
        "prose, no markdown, no code fences. Begin with { and end with }."
    )

    raw = await llm_client.generate(
        prompt=prompt,
        system_prompt=_PROJECT_INSIGHT_SYSTEM_PROMPT,
        model=req.model or settings.reasoning_model,
        temperature=0.2,
        num_ctx=24576,
        response_format="json",
        llm_target_url=req.llm_target_url,
    )

    parsed = _parse_json_response(raw) or {}
    es = parsed.get("executiveSummary")
    es = es if isinstance(es, dict) else {}
    executive = ProjectInsightExecutiveSummary(
        summary=str(es.get("summary", "")).strip(),
        critical=_str_list(es.get("critical")),
        warnings=_str_list(es.get("warnings")),
        opportunities=_str_list(es.get("opportunities")),
        recommendations=_str_list(es.get("recommendations")),
    )

    update_activity(req.user_id, req.tenant_id, req.project_id)
    return ProjectInsightResponse(
        executiveSummary=executive,
        questionsToAsk=_dict_list(parsed.get("questionsToAsk"), 8),
        trendDetection=_dict_list(parsed.get("trendDetection"), 8),
        recommendedDashboards=_dict_list(parsed.get("recommendedDashboards"), 8),
        recommendedQueries=_dict_list(parsed.get("recommendedQueries"), 8),
        recommendedKpis=_dict_list(parsed.get("recommendedKpis"), 12),
        insightValidationWorkflow=_dict_list(
            parsed.get("insightValidationWorkflow"), 12
        ),
        request_id=request_id,
        model_used=req.model or settings.reasoning_model,
    )
