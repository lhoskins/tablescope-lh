"""Business interpretation of executed analysis results."""

import json
import logging
import uuid

from fastapi import APIRouter

from app.core.config import settings
from app.core.security import verify_signature
from app.models.schemas import (
    IntelligenceInterpretRequest,
    IntelligenceInterpretResponse,
    InterpretedInsight,
)
from app.services import llm_client

from .ai_shared import (
    _INTEL_SYSTEM_PROMPT,
    _parse_json_response,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/intelligence/interpret", response_model=IntelligenceInterpretResponse)
async def intelligence_interpret(
    req: IntelligenceInterpretRequest,
) -> IntelligenceInterpretResponse:
    """Turn executed query results (or document context) into business prose.

    Receives, per analysis, the columns + a sample of result rows (already run
    against real data) and returns an executive-style finding: summary, severity,
    an optional callout, and a recommended action.
    """
    request_id = str(uuid.uuid4())
    verify_signature(req.model_dump(exclude={"signature"}), req.signature)

    blocks: list[str] = []
    for a in req.analyses:
        lines = [
            f"Analysis id: {a.id}",
            f"Category: {a.category}",
            f"Title: {a.title}",
            f"Why it matters: {a.rationale}",
        ]
        if a.document_context:
            lines.append(f"Document context:\n{a.document_context[:1500]}")
        else:
            lines.append(f"Result columns: {', '.join(a.columns)}")
            lines.append(f"Row count: {a.row_count}")
            sample = a.rows[:20]
            lines.append(f"Result sample (JSON): {json.dumps(sample, default=str)[:2000]}")
        blocks.append("\n".join(lines))

    prompt = (
        "For each analysis below, you are given the REAL result of a query that was "
        "already executed against the project's data (or the relevant document "
        "text). Write a sharp, executive-level finding grounded ONLY in those "
        "numbers/text — never invent values. Quantify the insight using the actual "
        "figures, name the trend/risk/opportunity, and give one concrete "
        "recommendation a decision-maker can act on. Use **bold** for the key "
        "figure or entity.\n\n"
        + "\n\n---\n\n".join(blocks)
        + "\n\nReturn ONLY a JSON object: {\"insights\": [ {\n"
        "  \"id\": \"<matching analysis id>\",\n"
        "  \"title\": \"refined headline\",\n"
        "  \"summary\": \"2-3 sentence executive finding with the real figures\",\n"
        "  \"severity\": \"critical|urgent|watch|opportunity|info\",\n"
        "  \"callout_type\": \"risk|opportunity|info\",\n"
        "  \"callout_text\": \"one-line callout (or empty)\",\n"
        "  \"recommendation\": \"one concrete action\"\n"
        "} ] }"
    )

    raw = await llm_client.generate(
        prompt=prompt,
        system_prompt=_INTEL_SYSTEM_PROMPT,
        model=settings.reasoning_model,
        temperature=0.2,
        num_ctx=8192,
    )

    parsed = _parse_json_response(raw)
    insights: list[InterpretedInsight] = []
    if parsed and isinstance(parsed.get("insights"), list):
        for ins in parsed["insights"]:
            if not isinstance(ins, dict) or not ins.get("id"):
                continue
            severity = str(ins.get("severity", "info")).lower()
            if severity not in ("critical", "urgent", "watch", "opportunity", "info"):
                severity = "info"
            insights.append(
                InterpretedInsight(
                    id=str(ins["id"]),
                    title=str(ins.get("title", "")),
                    summary=str(ins.get("summary", "")),
                    severity=severity,
                    callout_type=str(ins.get("callout_type", "")),
                    callout_text=str(ins.get("callout_text", "")),
                    recommendation=str(ins.get("recommendation", "")),
                )
            )
    else:
        logger.warning("Failed to parse intelligence interpretation: %s", raw[:200])

    return IntelligenceInterpretResponse(
        insights=insights,
        request_id=request_id,
        model_used=settings.reasoning_model,
    )
