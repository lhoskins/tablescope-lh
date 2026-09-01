"""The ``/ai/intelligence/investigate-step`` "why" investigation agent endpoint.

Plans a multi-query root-cause investigation one step at a time: given the
original question and every sub-query run so far (a bounded preview of
each, not full row sets), decide whether to run one more targeted
sub-question or stop because enough evidence has been gathered. This
endpoint never generates or sees SQL beyond the summaries in ``steps`` --
each sub-question it proposes is handed back to the existing ask-and-run
pipeline, which does its own schema resolution, SQL generation, execution,
and self-repair exactly as it would for a single-query turn.
"""

import logging
import uuid

from fastapi import APIRouter

from app.core.activity import update_activity
from app.core.config import settings
from app.core.security import verify_signature
from app.models.schemas import (
    IntelligenceInvestigateStepRequest,
    IntelligenceInvestigateStepResponse,
    InvestigationStepResult,
)
from app.services import llm_client
from app.services.llm_client import _catalog_text

from .ai_shared import _parse_json_response

logger = logging.getLogger(__name__)
router = APIRouter()

_INVESTIGATE_SYSTEM_PROMPT = (
    "You are Tablescope AI acting as a senior business analyst investigating "
    "a root-cause ('why') question. Plan a small number of targeted "
    "follow-up questions -- segment by a category, compare two periods, "
    "check a related metric -- the way an analyst would iterate toward an "
    "explanation instead of answering from a single number. You never write "
    "SQL yourself; each sub-question you propose is a plain-language "
    "analytical question that a downstream system turns into a query and "
    "runs for you.\n"
    "You are given a catalog of the project's real sources below, each with "
    "its actual columns and (when available) a profile: row count, the date "
    "column's real range, and a few categorical columns' actual values. "
    "Every sub-question you propose MUST be answerable from a column that "
    "genuinely appears in that catalog -- never propose a breakdown by a "
    "category, code, or attribute that is not listed, no matter how "
    "plausible it sounds. If a source's profile shows the date range covers "
    "a single period (e.g. one month), a trend/rising/falling question "
    "cannot be answered from it -- do not propose a sub-question chasing a "
    "trend that isn't there; finish and let the answer state the data is a "
    "single-period snapshot instead. Respond with a single JSON object and "
    "nothing else."
)


def _step_block(steps: list[InvestigationStepResult]) -> str:
    if not steps:
        return "No sub-queries have been run yet."
    lines: list[str] = []
    for i, s in enumerate(steps, start=1):
        lines.append(f'Step {i}: "{s.sub_question}"')
        if s.error:
            lines.append(f"  -> failed: {s.error}")
            continue
        if s.columns:
            lines.append(f"  columns: {', '.join(s.columns)}")
        lines.append(f"  row count: {s.row_count}")
        for row in s.sample_rows[:5]:
            if isinstance(row, dict):
                lines.append("  - " + ", ".join(f"{k}={v}" for k, v in row.items()))
    return "\n".join(lines)


def _investigate_step_prompt(req: IntelligenceInvestigateStepRequest) -> str:
    catalog = _catalog_text([], req.source_catalog)
    return (
        f"{catalog}\n\n"
        f"Original question: {req.question}\n\n"
        f"Evidence gathered so far:\n{_step_block(req.steps)}\n\n"
        f"You may run at most {req.steps_remaining} more sub-question(s) "
        "toward answering the original question, or decide you already "
        "have enough evidence. Respond with ONLY a JSON object, one of:\n"
        '  {"action": "query", "sub_question": "<one specific, plain-'
        'language follow-up question>"} -- gather one more piece of '
        "evidence. Investigate a DIFFERENT angle than any step above; never "
        "repeat a sub-question already run.\n"
        '  {"action": "finish"} -- use this once you have enough evidence '
        "to explain the original question, or whenever no more sub-"
        "questions are allowed.\n"
        "Respond with ONLY the JSON object -- no markdown, no commentary."
    )


@router.post(
    "/intelligence/investigate-step",
    response_model=IntelligenceInvestigateStepResponse,
)
async def intelligence_investigate_step(
    req: IntelligenceInvestigateStepRequest,
) -> IntelligenceInvestigateStepResponse:
    """One planning step of the multi-query "why" investigation agent.

    Called in a bounded loop by platform-api's conversational-analytics
    turn execution. Each call is independent (no server-side state) -- the
    caller re-sends the accumulating ``steps`` list on every call.
    """
    request_id = str(uuid.uuid4())
    verify_signature(req.model_dump(exclude={"signature"}, exclude_unset=True), req.signature)
    update_activity()

    if req.steps_remaining <= 0:
        # No budget left -- stop without spending a call asking the model to
        # decide something that isn't actually a choice.
        return IntelligenceInvestigateStepResponse(
            action="finish",
            request_id=request_id,
            model_used=req.model or settings.reasoning_model,
        )

    raw = await llm_client.generate(
        prompt=_investigate_step_prompt(req),
        system_prompt=_INVESTIGATE_SYSTEM_PROMPT,
        model=req.model or settings.reasoning_model,
        temperature=0.2,
        num_ctx=8192,
        response_format="json",
        llm_target_url=req.llm_target_url,
    )

    decision = _parse_json_response(raw or "") or {}
    action = str(decision.get("action") or "").strip()
    sub_question = str(decision.get("sub_question") or "").strip()

    already_asked = {req.question.strip().lower()} | {
        s.sub_question.strip().lower() for s in req.steps
    }
    if action != "query" or not sub_question or sub_question.lower() in already_asked:
        action = "finish"
        sub_question = ""

    return IntelligenceInvestigateStepResponse(
        action=action,
        sub_question=sub_question,
        request_id=request_id,
        model_used=req.model or settings.reasoning_model,
    )
