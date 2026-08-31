"""The ``/ai/intelligence/repair-sql-step`` SQL self-repair agent endpoint.

Unlike ``fix-sql`` (a single blind full-query rewrite), this endpoint returns
ONE step of a bounded decision loop that platform-api drives: rewrite the
query, ask to see a specific column's real sample value/type first, or give
up. This lets the model request only the schema detail it actually needs for
the failure in front of it, instead of every column of every allowed table
being crammed into the prompt on every attempt regardless of relevance --
which matters in particular for a model that has shown truncation issues
under longer prompts (see ``llm_client.py``'s ``_SQL_MIN_TOKENS`` workaround).
"""

import logging
import re
import uuid

from fastapi import APIRouter

from app.core.activity import update_activity
from app.core.config import settings
from app.core.security import verify_signature
from app.models.schemas import (
    IntelligenceRepairSQLStepRequest,
    IntelligenceRepairSQLStepResponse,
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
    _parse_json_response,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_VALID_ACTIONS = {"rewrite", "inspect_column", "give_up"}


def _known_columns_block(known: list) -> str:
    """Render previously-revealed column samples/types, if any."""
    lines = [
        f'  - "{k.table}"."{k.column}": type={k.type or "unknown"}, example value={k.sample!r}'
        for k in known
        if k.table and k.column
    ]
    if not lines:
        return ""
    return (
        "\nColumn details you already requested (use these facts, do NOT "
        "request the same table/column again):\n" + "\n".join(lines)
    )


def _repair_step_prompt(req: IntelligenceRepairSQLStepRequest) -> str:
    schema_lines = _build_schema_lines(req.table_schema)
    # A failing query that already JOINs two tables is a planner-mandated
    # cross-table analysis -- keep the join intact rather than "fixing" it
    # back to single-table, same as fix-sql.
    is_join_repair = bool(re.search(r"\bJOIN\b", req.sql or "", re.IGNORECASE))
    teiid_rules = (
        _TEIID_RULES_HEADER + _TEIID_FIX_JOIN_RULE + _TEIID_RULES_COMMON
        if is_join_repair
        else _TEIID_SQL_RULES
    )
    known_block = _known_columns_block(req.known_columns)

    return (
        "A read-only SQL query failed against a Teiid database. Decide the "
        "SINGLE next action toward fixing it. Respond with ONLY a JSON "
        "object, one of:\n"
        '  {"action": "rewrite", "sql": "<corrected query>"} -- use this '
        "when you already know enough to fix it.\n"
        '  {"action": "inspect_column", "table": "<table>", "column": '
        '"<column>"} -- use this when you need to see a specific column\'s '
        "real sample value/type before you can decide how to fix a date, "
        "cast, or type-related error. Never request a table/column not "
        "listed in the schema below, and never re-request one already "
        "listed under 'Column details you already requested'.\n"
        '  {"action": "give_up"} -- use this only if the query genuinely '
        "cannot be fixed against the allowed tables/columns.\n"
        "Fix ONLY what the error requires (e.g. CAST the right column, stop "
        "casting categorical text, drop an unsupported function, use a "
        "column that actually exists in the queried table). If the error "
        "says an element/column is 'not defined by any relevant group', "
        "that column does NOT exist on the table in your FROM clause -- do "
        "NOT switch tables and do NOT add a JOIN; replace it with a real "
        "column listed under that SAME table, or drop that term.\n"
        "If your fix touches a date/period expression that also appears in "
        "GROUP BY or ORDER BY (adding, removing, or switching a CAST, "
        "PARSETIMESTAMP, FORMATDATE, or FORMATTIMESTAMP wrapper) -- copy the "
        "exact new expression, character-for-character, into GROUP BY and "
        "ORDER BY too in this same rewrite. A GROUP BY still referencing the "
        "expression's old form IS the 'not present in a GROUP BY clause' "
        "error, even after the SELECT expression itself is fixed.\n\n"
        f"Allowed tables (use ONLY these): {', '.join(req.allowed_tables)}\n"
        f"{schema_lines}\n"
        f"{known_block}\n\n"
        f"{teiid_rules}\n"
        f"Failing SQL:\n{req.sql}\n\n"
        f"Engine error:\n{req.error[:800]}\n\n"
        "Respond with ONLY the JSON object -- no markdown, no commentary."
    )


@router.post(
    "/intelligence/repair-sql-step",
    response_model=IntelligenceRepairSQLStepResponse,
)
async def intelligence_repair_sql_step(
    req: IntelligenceRepairSQLStepRequest,
) -> IntelligenceRepairSQLStepResponse:
    """One step of the SQL self-repair agent: rewrite, inspect a column, or give up.

    Called in a bounded loop by platform-api's ``_execute_with_repair``. Each
    call is independent (no server-side state) -- the caller re-sends the
    accumulating ``known_columns`` list on every call.
    """
    request_id = str(uuid.uuid4())
    verify_signature(req.model_dump(exclude={"signature"}, exclude_unset=True), req.signature)
    update_activity()

    raw = await llm_client.generate(
        prompt=_repair_step_prompt(req),
        system_prompt=_INTEL_SYSTEM_PROMPT,
        model=req.model or settings.reasoning_model,
        temperature=0.1,
        num_ctx=8192,
        response_format="json",
        # Confirmed live: a reasoning model (e.g. muse-glimmer) can stop
        # right after a short reasoning burst and never finish the JSON
        # decision -- most visibly, the "sql" string value for a rewrite
        # gets cut off mid-statement (an aggregate expression present but
        # the FROM clause never emitted), producing SQL that then fails
        # for a different, more confusing reason than the original error.
        # Same guard llm_client.generate_sql/repair_sql already apply to
        # the initial generation call.
        min_tokens=llm_client._SQL_MIN_TOKENS,
        llm_target_url=req.llm_target_url,
    )

    decision = _parse_json_response(raw or "") or {}
    action = str(decision.get("action") or "").strip()
    if action not in _VALID_ACTIONS:
        action = "give_up"

    sql = ""
    table = ""
    column = ""
    if action == "rewrite":
        sql = _clean_sql(str(decision.get("sql") or ""))
        if sql:
            try:
                validate_sql(sql, req.allowed_tables)
            except SQLValidationError as e:
                logger.warning("repair-sql-step produced invalid SQL: %s", e.reason)
                sql = ""
        if not sql:
            action = "give_up"
    elif action == "inspect_column":
        table = str(decision.get("table") or "").strip()
        column = str(decision.get("column") or "").strip()
        if not table or not column:
            action = "give_up"

    return IntelligenceRepairSQLStepResponse(
        action=action,
        sql=sql,
        table=table,
        column=column,
        request_id=request_id,
        model_used=req.model or settings.reasoning_model,
    )
