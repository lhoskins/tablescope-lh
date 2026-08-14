"""AI-drafted project actions."""

import json
import logging
import re
import uuid
from typing import Any

from fastapi import APIRouter

from app.core.activity import update_activity
from app.core.config import settings
from app.core.security import verify_signature
from app.models.schemas import (
    DraftActionRequest,
    DraftActionResponse,
    DraftActionSubtask,
    DraftActionSuccessCriterion,
)
from app.services import llm_client

from .ai_shared import _repair_truncated_json

logger = logging.getLogger(__name__)
router = APIRouter()


_ACTION_DRAFT_SYSTEM_PROMPT = (
    "You are a senior project-management analyst. Given a business insight, "
    "draft a concrete, actionable project action. The output must be valid "
    "JSON only — no markdown, no prose wrappers. The model's response is "
    "constrained to JSON."
)


_ACTION_DRAFT_USER_PROMPT = """\
Convert the following insight into a project action draft.

Insight type: {insight_type}
Title: {title}
Summary: {summary}
Severity: {severity}
Recommended action (from AI): {recommended_action}
Sources: {sources}
Supporting sources: {supporting_sources}
Explanation: {explanation}

Return ONLY a JSON object matching this schema:
{{
  "title": "A short, specific action title (max 150 chars). Do not simply repeat the insight title; state the action to take.",
  "description": "2-4 sentences describing what the action is, why it matters, and any context needed. No markdown.",
  "subtasks": [
    {{"title": "First concrete subtask", "description": "", "is_required": true, "status": "not_started"}},
    ... up to 5 subtasks
  ],
  "success_criteria": [
    {{"name": "Criterion name", "description": "", "target_value": "numeric or descriptive target", "directionality": "increase|decrease|maintain", "cadence": "monthly|quarterly|annual|once", "unit": "", "format": ""}},
    ... up to 3 criteria
  ]
}}

Rules:
- subtask.status must be one of: not_started, in_progress, blocked, completed.
- directionality must be one of: increase, decrease, maintain.
- cadence must be one of: monthly, quarterly, annual, once.
- Limit to at most 5 subtasks and 3 success criteria.
- Do not auto-create the action; this is a draft for human review.
"""


def _sanitize_markdown(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"_(.+?)_", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*+>]\s+", "", text, flags=re.M)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text.strip()


def _build_action_draft_prompt(req: DraftActionRequest) -> str:
    sources = json.dumps(req.sources or {}, ensure_ascii=False)
    explanation = json.dumps(req.explanation or {}, ensure_ascii=False)
    return _ACTION_DRAFT_USER_PROMPT.format(
        insight_type=req.insight_type,
        title=req.title,
        summary=req.summary,
        severity=req.severity,
        recommended_action=req.recommended_action or "(none provided)",
        sources=sources,
        supporting_sources=json.dumps(req.supporting_sources or [], ensure_ascii=False),
        explanation=explanation,
    )


def _normalize_enum(value: str, allowed: tuple[str, ...], default: str) -> str:
    v = (value or "").strip().lower()
    return v if v in allowed else default


@router.post("/actions/draft", response_model=DraftActionResponse)
async def draft_action(req: DraftActionRequest) -> DraftActionResponse:
    """Generate a structured project action draft from an insight card."""
    request_id = str(uuid.uuid4())
    verify_signature(req.model_dump(exclude={"signature"}, exclude_unset=True), req.signature)
    update_activity(req.tenant_id)

    prompt = _build_action_draft_prompt(req)
    raw = await llm_client.generate(
        prompt,
        system_prompt=_ACTION_DRAFT_SYSTEM_PROMPT,
        model=req.model or settings.reasoning_model,
        temperature=0.2,
        response_format="json",
        max_tokens=2048,
        ollama_url=req.ollama_url,
    )

    parsed: dict[str, Any] = {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        repaired = _repair_truncated_json(raw)
        if repaired is not None:
            parsed = repaired
        else:
            logger.warning("Could not parse action draft JSON: %s", raw[:200])

    title = _sanitize_markdown(str(parsed.get("title", "")))
    description = _sanitize_markdown(str(parsed.get("description", "")))

    subtasks: list[DraftActionSubtask] = []
    for s in parsed.get("subtasks", [])[:5]:
        if not isinstance(s, dict):
            continue
        st = s.get("title", "").strip()
        if not st:
            continue
        status = _normalize_enum(
            s.get("status", "not_started"),
            ("not_started", "in_progress", "blocked", "completed"),
            "not_started",
        )
        subtasks.append(
            DraftActionSubtask(
                title=st[:500],
                description=_sanitize_markdown(s.get("description", "")),
                is_required=bool(s.get("is_required", True)),
                status=status,
            )
        )

    criteria: list[DraftActionSuccessCriterion] = []
    for c in parsed.get("success_criteria", [])[:3]:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name", "")).strip()
        if not name:
            continue
        directionality = _normalize_enum(
            c.get("directionality", "increase"),
            ("increase", "decrease", "maintain"),
            "increase",
        )
        cadence = _normalize_enum(
            c.get("cadence", "monthly"),
            ("monthly", "quarterly", "annual", "once"),
            "monthly",
        )
        criteria.append(
            DraftActionSuccessCriterion(
                name=name[:500],
                description=_sanitize_markdown(c.get("description", "")),
                target_value=c.get("target_value"),
                directionality=directionality,
                cadence=cadence,
                unit=str(c.get("unit", ""))[:50],
                format=str(c.get("format", ""))[:50],
            )
        )

    return DraftActionResponse(
        title=title or req.title,
        description=description,
        subtasks=subtasks,
        success_criteria=criteria,
        model_used=req.model or settings.reasoning_model,
        request_id=request_id,
    )
