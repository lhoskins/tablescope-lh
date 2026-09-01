"""Uploaded-file profile analysis."""

import json
import logging
import uuid

from fastapi import APIRouter

from app.core.config import settings
from app.core.security import verify_signature
from app.models.schemas import (
    AnalyzeFileRequest,
    AnalyzeFileResponse,
)
from app.services import llm_client

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/analyze-file", response_model=AnalyzeFileResponse)
async def analyze_file(req: AnalyzeFileRequest):
    """Analyze a file profile and return structured metadata."""
    verify_signature(req.model_dump(exclude={"signature"}, exclude_unset=True), req.signature)

    request_id = str(uuid.uuid4())
    logger.info("[%s] File analysis request", request_id)

    raw = await llm_client.generate(
        prompt=req.prompt,
        system_prompt=(
            "You are a data analyst that analyzes uploaded data files. "
            "Return ONLY valid JSON with the exact structure requested. "
            "Do not include markdown formatting, code fences, or any text outside the JSON."
        ),
        model=req.model or settings.reasoning_model,
        temperature=0.1,
        llm_target_url=req.llm_target_url,
    )

    # Parse JSON from LLM response
    analysis: dict = {}
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        analysis = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("Failed to parse file analysis JSON: %s — %s", str(e), raw[:300])
        analysis = {
            "summary": "AI analysis could not be completed.",
            "usage_summary": "File is available for queries.",
            "quality_summary": "Unable to assess quality.",
            "tags": [],
            "fields": [],
            "recommendations": [],
        }

    return AnalyzeFileResponse(
        analysis=analysis,
        request_id=request_id,
        model_used=req.model or settings.reasoning_model,
    )
