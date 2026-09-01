"""Reference-library summarization and domain suggestion."""

import logging
import uuid

from fastapi import APIRouter, HTTPException, status

from app.core.activity import update_activity
from app.core.config import settings
from app.core.security import verify_signature
from app.models.schemas import (
    ReferenceSuggestRequest,
    ReferenceSuggestResponse,
    ReferenceSummarizeRequest,
    ReferenceSummarizeResponse,
)
from app.services import llm_client

from .ai_shared import _parse_json_response

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/reference-library/summarize", response_model=ReferenceSummarizeResponse)
async def summarize_reference_document(req: ReferenceSummarizeRequest) -> ReferenceSummarizeResponse:
    """Summarize a reference-library document (standard/regulation/policy).

    Produces a short, AI-grounding summary focused on what the document governs,
    who it applies to, and any specific thresholds/requirements an AI assistant
    should know when citing it.
    """
    update_activity(req.user_id, req.tenant_id, req.project_id)
    verify_signature(req.model_dump(exclude={"signature"}, exclude_unset=True), req.signature)
    request_id = uuid.uuid4().hex[:12]
    logger.info(
        "[%s] reference-library/summarize doc=%s title=%s", request_id, req.document_id, req.title
    )

    text_preview = (req.extracted_text or "").strip()[:8000]
    if not text_preview:
        return ReferenceSummarizeResponse(
            summary="", request_id=request_id, model_used=req.model or settings.reasoning_model
        )

    prompt = f"""You are summarizing a reference document (standard, regulation, framework, or policy) for use as AI grounding context.

Title: {req.title}
Issuing body: {req.issuing_body or "unknown"}
Domain: {req.domain_tag or "unspecified"}

Document text:
{text_preview}

Write a 2-4 sentence summary for an AI assistant. Focus on:
- what this document governs (its scope/purpose),
- who it applies to,
- any specific thresholds, controls, or requirements an assistant should know when citing it.

Return ONLY the summary text — no preamble, no headings, no JSON."""

    try:
        raw = await llm_client.generate(
            prompt=prompt,
            model=req.model or settings.reasoning_model,
            temperature=0.2,
            max_tokens=400,
            llm_target_url=req.llm_target_url,
        )
    except Exception as exc:
        logger.exception("[%s] reference summarize failed: %s", request_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Reference summarize failed: {exc}",
        )

    return ReferenceSummarizeResponse(
        summary=(raw or "").strip(),
        request_id=request_id,
        model_used=req.model or settings.reasoning_model,
    )


@router.post("/reference-library/suggest", response_model=ReferenceSuggestResponse)
async def suggest_references(req: ReferenceSuggestRequest) -> ReferenceSuggestResponse:
    """Suggest which Industry reference domains add value for a project's signals.

    Only suggests domains clearly relevant to the project's data/documents — does
    not suggest broadly to maximize coverage.
    """
    update_activity(req.user_id, req.tenant_id, req.project_id)
    verify_signature(req.model_dump(exclude={"signature"}, exclude_unset=True), req.signature)
    request_id = uuid.uuid4().hex[:12]

    candidate_str = ", ".join(req.candidate_domains[:40]) or "(none)"
    ds_str = ", ".join(req.data_source_types[:40]) or "(none)"
    tables_str = ", ".join(req.table_names[:80]) or "(none)"
    docs_str = ", ".join(req.document_types[:40]) or "(none)"
    topics_str = ", ".join(req.recent_query_topics[:40]) or "(none)"

    prompt = f"""Given this project's data and document signals, identify which Industry-tier reference domains would add valuable context. Only suggest domains clearly relevant — do not suggest broadly to maximize coverage.

Available reference domains: {candidate_str}

Project signals:
- Data source types: {ds_str}
- Table names: {tables_str}
- Document types: {docs_str}
- Recent query topics: {topics_str}

Return ONLY valid JSON with this exact structure:
{{
  "suggestions": [
    {{"domainTag": "one of the available domains", "reasoning": "one sentence on why this project would benefit"}}
  ]
}}

Rules:
- Only use domains from the available list above.
- Suggest at most 4 domains, fewest that are clearly justified.
- If nothing is clearly relevant, return an empty suggestions list."""

    try:
        raw = await llm_client.generate(
            prompt=prompt,
            model=req.model or settings.reasoning_model,
            temperature=0.2,
            max_tokens=800,
            llm_target_url=req.llm_target_url,
        )
        parsed = _parse_json_response(raw) or {}
    except Exception as exc:
        logger.exception("[%s] reference suggest failed: %s", request_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Reference suggest failed: {exc}",
        )

    allowed = {d.lower() for d in req.candidate_domains}
    suggestions: list[dict] = []
    for s in parsed.get("suggestions", []):
        if not isinstance(s, dict):
            continue
        domain = str(s.get("domainTag", "")).strip()
        if domain and domain.lower() in allowed:
            suggestions.append(
                {"domainTag": domain, "reasoning": str(s.get("reasoning", "")).strip()}
            )

    return ReferenceSuggestResponse(
        suggestions=suggestions,
        request_id=request_id,
        model_used=req.model or settings.reasoning_model,
    )
