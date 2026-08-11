"""The ``/ai/intelligence/fix-sql`` repair endpoint."""

import logging
import re
import uuid

from fastapi import APIRouter

from app.core.config import settings
from app.core.security import verify_signature
from app.models.schemas import (
    IntelligenceFixSQLRequest,
    IntelligenceFixSQLResponse,
)
from app.services import llm_client
from app.services.sql_validator import SQLValidationError, validate_sql

from .ai_shared import (
    _INTEL_SYSTEM_PROMPT,
    _TEIID_FIX_JOIN_RULE,
    _TEIID_RULES_COMMON,
    _TEIID_RULES_HEADER,
    _TEIID_SQL_RULES,
    _build_schema_lines,
    _clean_sql,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/intelligence/fix-sql", response_model=IntelligenceFixSQLResponse)
async def intelligence_fix_sql(
    req: IntelligenceFixSQLRequest,
) -> IntelligenceFixSQLResponse:
    """Repair a single query the engine rejected, using the exact error + schema.

    This closes the analyst loop: when generated SQL fails (CAST on the wrong
    type, alias-in-GROUP BY, an unsupported function, a wrong-table column, …),
    the model is shown the precise engine error and asked to return a corrected
    query — keeping a cross-table query's verified join joined. Returns empty
    SQL if it can't be fixed.
    """
    request_id = str(uuid.uuid4())
    verify_signature(req.model_dump(exclude={"signature"}, exclude_unset=True), req.signature)

    schema_lines = _build_schema_lines(req.table_schema)
    # A failing query that already JOINs two tables is a planner-mandated
    # cross-table analysis. The default rules' "Do NOT write JOINs" would make
    # the repair strip the join (silently demoting the card to single-table or
    # to nothing) — use the keep-the-join variant instead.
    is_join_repair = bool(re.search(r"\bJOIN\b", req.sql or "", re.IGNORECASE))
    teiid_rules = (
        _TEIID_RULES_HEADER + _TEIID_FIX_JOIN_RULE + _TEIID_RULES_COMMON
        if is_join_repair
        else _TEIID_SQL_RULES
    )
    prompt = (
        "A read-only SQL query failed against a Teiid database. Rewrite it so it "
        "runs, keeping the SAME analytical intent. Fix ONLY what the error "
        "requires (e.g. CAST the right column, stop casting categorical text, "
        "repeat the SELECT expression in GROUP BY, drop an unsupported function, "
        "use a column that actually exists in the queried table). If the query "
        "cannot be made to work against the allowed tables, return an empty "
        "string.\n"
        "If the error says an element/column is 'not defined by any relevant "
        "group', that column does NOT exist on the table in your FROM clause. Do "
        "NOT switch tables and do NOT add a JOIN — instead replace it with a "
        "real column listed under that SAME table in the schema below (pick "
        "another numeric column with a similar meaning), or drop that term. For "
        "a text date stored like '1/19/2026', use "
        "PARSETIMESTAMP(\"col\", 'M/d/yyyy'), never CAST(\"col\" AS date).\n\n"
        f"Allowed tables (use ONLY these): {', '.join(req.allowed_tables)}\n"
        f"{schema_lines}\n\n"
        f"{teiid_rules}\n"
        f"Failing SQL:\n{req.sql}\n\n"
        f"Engine error:\n{req.error[:800]}\n\n"
        "Return ONLY the corrected SQL query (no markdown, no commentary), or an "
        "empty response if it cannot be fixed."
    )

    raw = await llm_client.generate(
        prompt=prompt,
        system_prompt=_INTEL_SYSTEM_PROMPT,
        model=req.model or settings.reasoning_model,
        temperature=0.1,
        num_ctx=8192,
    )

    fixed = _clean_sql(raw or "")
    if fixed:
        try:
            validate_sql(fixed, req.allowed_tables)
        except SQLValidationError as e:
            logger.warning("fix-sql produced invalid SQL: %s", e.reason)
            fixed = ""

    return IntelligenceFixSQLResponse(
        sql=fixed,
        request_id=request_id,
        model_used=req.model or settings.reasoning_model,
    )
