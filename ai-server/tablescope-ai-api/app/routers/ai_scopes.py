"""Drill-down scope analysis for saved queries."""

import json
import logging
import uuid

from fastapi import APIRouter

from app.core.activity import update_activity
from app.core.config import settings
from app.core.security import verify_signature
from app.models.schemas import (
    AnalyzeScopesRequest,
    AnalyzeScopesResponse,
    ScopeSuggestion,
)
from app.services import llm_client

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/project/scopes/analyze", response_model=AnalyzeScopesResponse)
async def analyze_scopes(req: AnalyzeScopesRequest) -> AnalyzeScopesResponse:
    """Use AI to analyze saved queries and suggest drill-down scopes.

    The LLM determines:
    1. Which columns are meaningful for drill-down (identifiers, names — not aggregates)
    2. Direction: summarized/aggregated query → detailed/raw query
    """
    request_id = str(uuid.uuid4())
    verify_signature(req.model_dump(exclude={"signature"}, exclude_unset=True), req.signature)

    # Build query descriptions for the LLM
    query_descriptions = []
    for q in req.queries:
        query_descriptions.append(f"Query ID={q.id}, Name=\"{q.name}\", SQL:\n{q.sql}")

    queries_text = "\n\n".join(query_descriptions)

    prompt = (
        f"You are analyzing {len(req.queries)} saved SQL queries to find drill-down "
        f"scope relationships.\n\n"
        f"QUERIES:\n{queries_text}\n\n"
        "TASK: Find pairs of queries that share a meaningful drill-down relationship. "
        "A drill-down scope means: clicking a cell value in the SOURCE query filters "
        "the TARGET query by that value.\n\n"
        "RULES:\n"
        "1. Only use identifier/name columns (ProductName, CategoryName, CustomerID, "
        "OrderID, etc.) — NEVER use numeric/aggregate columns (Revenue, Amount, Total, "
        "Count, Price, Quantity, etc.)\n"
        "2. Direction must be: summarized/aggregated query → detailed/raw query. "
        "The source is the query with GROUP BY or aggregate functions (SUM, COUNT, AVG). "
        "The target is the query with raw/detailed rows (no aggregation, or less aggregation).\n"
        "3. The source_field and target_field must be the exact column alias from the "
        "SELECT clause of the respective query.\n"
        "4. Only ONE scope per pair of queries per shared column — no duplicates, no reverse.\n"
        "5. Both queries must actually SELECT the column (it must appear in the SELECT clause).\n\n"
        "Return a JSON array of objects with: source_query_id, source_query_name, "
        "source_field, target_query_id, target_query_name, target_field, confidence (0-1), reason.\n"
        "Return ONLY the JSON array, no other text."
    )

    raw = await llm_client.generate(
        prompt=prompt,
        system_prompt="You are a data analyst that identifies drill-down relationships between SQL queries. Return only valid JSON.",
        model=req.model or settings.reasoning_model,
        temperature=0.0,
        ollama_url=req.ollama_url,
    )

    # Parse scopes from LLM response
    scopes: list[ScopeSuggestion] = []
    try:
        json_match = raw.strip()
        if json_match.startswith("```"):
            json_match = json_match.split("```")[1]
            if json_match.startswith("json"):
                json_match = json_match[4:]
        parsed = json.loads(json_match)
        if isinstance(parsed, list):
            for item in parsed:
                scopes.append(ScopeSuggestion(**item))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        logger.warning("Failed to parse scope suggestions: %s — %s", str(e), raw[:200])

    update_activity(req.user_id, req.tenant_id, req.project_id)

    return AnalyzeScopesResponse(
        scopes=scopes,
        request_id=request_id,
        model_used=req.model or settings.reasoning_model,
    )
