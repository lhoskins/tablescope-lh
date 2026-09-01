"""Select which precomputed Insight Card, if any, answers a question."""

import uuid

from fastapi import APIRouter

from app.core.activity import update_activity
from app.core.config import settings
from app.core.security import verify_signature
from app.models.schemas import (
    SelectInsightCardRequest,
    SelectInsightCardResponse,
)
from app.services import llm_client
from app.services.prompt_loader import load_prompt_reference

from .ai_shared import _parse_json_response

router = APIRouter()


_SELECT_INSIGHT_CARD_SYSTEM_PROMPT = (
    "You are judging relevance between a user's question and a short list of "
    "already-computed analysis cards. Your ONLY job is to say which single "
    "card, if any, directly answers the question. You never write SQL, never "
    "invent findings, and never combine cards. Respond with a single JSON "
    "object and nothing else."
)


def _select_insight_card_prompt(req: SelectInsightCardRequest) -> str:
    best_practices = load_prompt_reference("insight_card_match_best_practices.md")
    candidate_lines = "\n".join(
        (
            f'- id="{c.insight_id}" title="{c.title}" '
            f'chart_signature="{c.chart_signature}" series="{c.series}" '
            f'trend="{c.trend}" summary="{c.summary}"'
        )
        for c in req.candidates
    )
    return (
        f"{best_practices}\n\n"
        "## Candidates\n"
        f"{candidate_lines}\n\n"
        "## Output schema (JSON only, all keys required)\n"
        "{\n"
        '  "insightId": "one of the candidate ids above, or null",\n'
        '  "confidence": 0.0-1.0,\n'
        '  "reason": "one short sentence"\n'
        "}\n\n"
        "## Question\n"
        f"{req.question}\n"
    )


@router.post(
    "/intelligence/select-insight-card",
    response_model=SelectInsightCardResponse,
)
async def select_insight_card(
    req: SelectInsightCardRequest,
) -> SelectInsightCardResponse:
    """Pick the one candidate Insight Card (if any) that answers ``question``.

    Called only after a fresh query could not be generated/executed for the
    question, as an alternative to unattributed prose. Deterministic
    validation afterwards guarantees the platform only ever receives an id
    that was actually offered as a candidate.
    """
    request_id = str(uuid.uuid4())
    verify_signature(req.model_dump(exclude={"signature"}, exclude_unset=True), req.signature)
    update_activity()

    if not req.candidates:
        return SelectInsightCardResponse(
            insight_id=None,
            confidence=0.0,
            reason="No candidates were offered.",
            request_id=request_id,
            model_used=req.model or settings.reasoning_model,
        )

    raw = await llm_client.generate(
        prompt=_select_insight_card_prompt(req),
        system_prompt=_SELECT_INSIGHT_CARD_SYSTEM_PROMPT,
        model=req.model or settings.reasoning_model,
        temperature=0.0,
        max_tokens=200,
        num_ctx=4096,
        response_format="json",
        llm_target_url=req.llm_target_url,
    )
    parsed = _parse_json_response(raw or "") or {}

    valid_ids = {c.insight_id for c in req.candidates}
    insight_id = parsed.get("insightId")
    if not isinstance(insight_id, str) or insight_id not in valid_ids:
        # The model may only pick an id it was actually offered. Anything
        # else -- a hallucinated id, wrong type, or an explicit null -- is a
        # decline, never a best-effort guess at what it might have meant.
        insight_id = None

    try:
        confidence = min(max(float(parsed.get("confidence", 0.0)), 0.0), 1.0)
    except (TypeError, ValueError):
        confidence = 0.0
    if insight_id is None:
        confidence = 0.0

    return SelectInsightCardResponse(
        insight_id=insight_id,
        confidence=confidence,
        reason=str(parsed.get("reason") or "")[:300],
        request_id=request_id,
        model_used=req.model or settings.reasoning_model,
    )
