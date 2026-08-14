"""Table-relationship generation for a project."""

import json
import logging
import uuid

from fastapi import APIRouter, HTTPException, status

from app.core.activity import update_activity
from app.core.config import settings
from app.core.security import verify_signature
from app.models.schemas import (
    GenerateRelationshipsRequest,
    GenerateRelationshipsResponse,
    RelationshipSuggestion,
)
from app.services import context_builder, llm_client
from app.services.context_builder import ContextBuildError

from .ai_shared import SYSTEM_PROMPT

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/project/relationships/generate", response_model=GenerateRelationshipsResponse)
async def generate_relationships(req: GenerateRelationshipsRequest) -> GenerateRelationshipsResponse:
    """Generate suggested relationships between project tables."""
    request_id = str(uuid.uuid4())
    verify_signature(req.model_dump(exclude={"signature"}, exclude_unset=True), req.signature)

    try:
        ctx = await context_builder.build_context(
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            project_id=req.project_id,
            scope="project",
            question="",
            feature="relationships",
        )
    except ContextBuildError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: {e.reason}",
        )

    context_text = context_builder.context_to_prompt_text(ctx)

    prompt = (
        f"{context_text}\n\n"
        "Analyze the tables and columns above. Suggest relationships between tables "
        "based on: matching column names, similar column names, overlapping value types, "
        "primary-key-like uniqueness, and foreign-key-like repetition.\n"
        "Return a JSON array of objects with: left_table, left_column, right_table, "
        "right_column, confidence (0-1), reason.\n"
        "Return ONLY the JSON array."
    )

    raw = await llm_client.generate(
        prompt=prompt,
        system_prompt=SYSTEM_PROMPT,
        model=req.model or settings.sql_model,
        temperature=0.0,
        ollama_url=req.ollama_url,
    )

    # Parse relationships from LLM response
    relationships: list[RelationshipSuggestion] = []
    try:
        # Extract JSON from response
        json_match = raw.strip()
        if json_match.startswith("```"):
            json_match = json_match.split("```")[1]
            if json_match.startswith("json"):
                json_match = json_match[4:]
        parsed = json.loads(json_match)
        if isinstance(parsed, list):
            for item in parsed:
                relationships.append(RelationshipSuggestion(**item))
    except (json.JSONDecodeError, KeyError, TypeError):
        logger.warning("Failed to parse relationship suggestions: %s", raw[:200])

    update_activity(req.user_id, req.tenant_id, req.project_id)

    return GenerateRelationshipsResponse(
        relationships=relationships,
        request_id=request_id,
        model_used=req.model or settings.sql_model,
    )
