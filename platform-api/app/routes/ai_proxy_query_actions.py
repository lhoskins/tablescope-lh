"""AI action endpoints that save queries — LLM proposes, Tablescope validates."""

from __future__ import annotations

import difflib
import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.file_source_meta import FileSourceMeta
from app.models.saved_query import SavedQuery
from app.services.teiid_sql import rebuild_group_by_from_select

from .ai_proxy_schemas import (
    AIGenerateAndSaveQueryRequest,
    AISaveQueryRequest,
)
from .ai_proxy_shared import (
    _build_source_catalog,
    _check_project_access,
    _detect_datasource,
    _forward_to_ai,
    _kg_context,
    _relationship_hints,
    _shorten_ai_name,
)

logger = logging.getLogger(__name__)
router = APIRouter()

def _clarification_response(
    prompt: str,
    detail: Any,
    allowed_tables: list[str],
) -> dict[str, Any]:
    """Turn a 422 from the AI server into a friendly, structured response.

    The frontend renders ``message`` + ``suggested_sources`` instead of a raw
    validation stack trace. The detailed reason stays in server logs.
    """
    suggested: list[str] = []
    reason = ""
    if isinstance(detail, dict):
        suggested = list(detail.get("suggested_sources") or [])
        reason = str(detail.get("reason") or detail.get("message") or "")
    else:
        reason = str(detail or "")
    if not suggested:
        suggested = _heuristic_rank_sources(prompt, allowed_tables)

    logger.info(
        "AI query generation needs clarification | reason=%s | suggested=%s",
        reason, suggested,
    )
    message = (
        "I could not find an authorized table that matches part of your "
        "request."
    )
    if suggested:
        message += " Try choosing one of these related sources."
    return {
        "action": "generate_and_save_query",
        "status": "needs_clarification",
        "message": message,
        "suggested_sources": suggested,
    }


def _heuristic_rank_sources(prompt: str, allowed_tables: list[str]) -> list[str]:
    """Rank authorized sources by normalized/fuzzy match with the prompt."""
    scored = sorted(
        ((_score_source_match(prompt, t), t) for t in allowed_tables),
        key=lambda x: (-x[0], x[1]),
    )
    ranked = [t for score, t in scored if score > 0]
    return (ranked or allowed_tables)[:5]


_SOURCE_SUFFIX_RE = re.compile(
    r"(_csv|_xlsx|_xls|_json|_parquet|_tsv|_table|_tbl|_view)$", re.IGNORECASE
)


def _strip_source_suffix(name: str) -> str:
    return _SOURCE_SUFFIX_RE.sub("", (name or "").strip())


def _normalize_source_name(name: str) -> str:
    """Lowercase, drop a file-format suffix, and collapse separators to spaces."""
    text = _strip_source_suffix((name or "").lower())
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _score_source_match(request: str, source: str) -> int:
    """Score how well ``request`` refers to authorized ``source`` (0-100)."""
    req = (request or "").strip().lower()
    src = (source or "").strip().lower()
    if not req or not src:
        return 0
    if req == src:
        return 100
    req_n = _normalize_source_name(request)
    src_n = _normalize_source_name(source)
    if req_n and req_n == src_n:
        return 95
    if req == _strip_source_suffix(src).lower():
        return 92
    req_tokens = [t for t in req_n.split() if t]
    src_tokens = set(t for t in src_n.split() if t)
    if req_tokens and set(req_tokens).issubset(src_tokens):
        return 80
    if req_n and src_n and difflib.SequenceMatcher(None, req_n, src_n).ratio() >= 0.85:
        return 70
    if req_n and req_n in src_n:
        return 60
    return 0


def _resolve_prompt_source(
    prompt: str, allowed_tables: list[str]
) -> tuple[list[str], list[str]]:
    """Return ``(strong, close)`` source matches for a table-name-like prompt.

    ``strong`` are confident matches (score ≥ 90); ``close`` are plausible but
    ambiguous ones (60 ≤ score < 90). Both are ordered best-first.
    """
    scored = sorted(
        ((_score_source_match(prompt, t), t) for t in allowed_tables),
        key=lambda x: (-x[0], x[1]),
    )
    strong = [t for s, t in scored if s >= 90]
    close = [t for s, t in scored if 60 <= s < 90]
    return strong, close


def _heuristic_sql(prompt: str, allowed_tables: list[str]) -> str:
    """Build a baseline SELECT when the AI server is unavailable.

    Picks the table whose name best matches words in the prompt (falling back
    to the first available table) and returns a simple preview query. The user
    can refine it in the query builder.
    """
    if not allowed_tables:
        return ""
    prompt_lower = prompt.lower()
    best = allowed_tables[0]
    best_score = -1
    for table in allowed_tables:
        # Score by how many of the table's word-parts appear in the prompt.
        parts = [p for p in re.split(r"[_\s]+", table.lower()) if p]
        score = sum(1 for p in parts if p in prompt_lower)
        if score > best_score:
            best_score = score
            best = table
    return f'SELECT * FROM "{best}" LIMIT 100'


@router.post("/actions/save-query")
async def ai_save_query(
    req: AISaveQueryRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Save AI-generated SQL as a project query.

    Pattern: LLM already proposed the SQL → Tablescope validates → saves.
    """
    project = await _check_project_access(session, context, req.project_id)

    # Detect which datasource the SQL references
    ds_stmt = select(FileSourceMeta).where(
        FileSourceMeta.project_id == req.project_id,
        FileSourceMeta.tenant_id == context.tenant_id,
        FileSourceMeta.archived.is_(False),
    )
    ds_result = await session.execute(ds_stmt)
    view_names = [ds.view_name for ds in ds_result.scalars()]
    left_datasource = _detect_datasource(req.sql_text, view_names)

    query = SavedQuery(
        project_id=project.id,
        owner_id=context.user_id,
        name=req.name,
        description=req.description or "",
        sql_text=req.sql_text,
        left_datasource=left_datasource,
        ai_generated=True,
    )
    session.add(query)
    await session.commit()
    await session.refresh(query)

    logger.info(
        "AI action: save_query | query_id=%d project=%d tenant=%d user=%d",
        query.id, project.id, context.tenant_id, context.user_id,
    )
    return {
        "action": "save_query",
        "status": "saved",
        "query_id": query.id,
        "name": query.name,
        "sql_text": query.sql_text,
    }


# Leading intent verb the user may type in the "Generate with AI" box, e.g.
# "generate table supplier performance" or "build query top vendors". Both the
# table and query phrasings must reach the SAME read-only query-generation flow;
# stripping the verb also stops the model from reading "table" as a DDL/CREATE
# request (which the SQL validator rejects — the source of the earlier
# "authorization error" on `generate table …`).
_GENERATION_INTENT_PATTERN = re.compile(
    r"^\s*(?:please\s+)?(?:generate|create|build|make)\s+(table|query)\b[:\s-]*",
    re.IGNORECASE,
)


def normalize_ai_generation_intent(prompt: str) -> tuple[str, str]:
    """Normalize an AI generation prompt into ``(intent, cleaned_prompt)``.

    ``intent`` is ``"table"`` or ``"query"`` (defaults to ``"query"``). Both
    intents use the same authorized, read-only query-generation path — the only
    difference is a hint appended to the prompt. The recognised leading verb is
    stripped so the remaining text describes the desired data, not a DDL action.
    """
    text = prompt or ""
    match = _GENERATION_INTENT_PATTERN.match(text)
    if not match:
        return "query", text.strip()
    intent = match.group(1).lower()
    remainder = text[match.end():].strip()
    return intent, remainder or text.strip()


@router.post("/actions/generate-and-save-query")
async def ai_generate_and_save_query(
    req: AIGenerateAndSaveQueryRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Generate SQL from a natural language prompt, validate, and save.

    Supports both new query creation and modification of existing queries.
    When the prompt indicates modification intent (modify, update, edit,
    change, add to, etc.) and references an existing query name, the
    existing query is updated in place instead of creating a new one.
    """
    project = await _check_project_access(session, context, req.project_id)

    # Normalize "generate/create/build table|query …" so both phrasings hit this
    # same authorized flow and the model treats the request as a read-only query
    # rather than a table (DDL) creation.
    gen_intent, base_prompt = normalize_ai_generation_intent(req.prompt)

    # Datasources are fetched unconditionally (not just when allowed_tables is
    # unset) since relationship-hint discovery needs the FileSourceMeta
    # objects, not just view names.
    ds_stmt = select(FileSourceMeta).where(
        FileSourceMeta.project_id == req.project_id,
        FileSourceMeta.tenant_id == context.tenant_id,
        FileSourceMeta.archived.is_(False),
    )
    ds_result = await session.execute(ds_stmt)
    sources = list(ds_result.scalars())
    allowed_tables = req.allowed_tables or [ds.view_name for ds in sources]
    # Evidence-backed join candidates (same discovery engine the dashboard
    # pipeline uses).
    relationship_hints = _relationship_hints(sources)

    # ── Detect modification intent ────────────────────────────────────
    import re as _re
    _MODIFY_PATTERN = _re.compile(
        r"^(?:modify|update|edit|change|alter|revise|adjust|fix|add\s+to|"
        r"add\s+.+?\s+to|remove\s+from|include\s+.+?\s+in)\s+",
        _re.IGNORECASE,
    )
    is_modification = bool(_MODIFY_PATTERN.search(req.prompt.strip()))

    # If modification, find the referenced existing query
    existing_query: SavedQuery | None = None
    if is_modification:
        existing_result = await session.scalars(
            select(SavedQuery).where(SavedQuery.project_id == project.id)
        )
        all_queries = list(existing_result)
        prompt_lower = req.prompt.lower()
        # Score each query by how well its name matches the prompt
        best_match: SavedQuery | None = None
        best_score = 0
        for eq in all_queries:
            if not eq.name:
                continue
            eq_name_lower = eq.name.lower().strip()
            # Check if the query name appears in the prompt
            if eq_name_lower in prompt_lower:
                score = len(eq_name_lower)
                if score > best_score:
                    best_score = score
                    best_match = eq
        existing_query = best_match
        if existing_query:
            logger.info(
                "Modification intent detected — updating query %d (%s)",
                existing_query.id, existing_query.name,
            )

    # Step 1: Call AI server to generate SQL
    prompt_text = base_prompt
    if existing_query and existing_query.sql_text:
        # Include the existing SQL so the AI can modify it
        prompt_text = (
            f"{base_prompt}\n\n"
            f"Here is the current SQL for the query \"{existing_query.name}\":\n"
            f"{existing_query.sql_text}\n\n"
            f"Please modify this SQL according to the request above. "
            f"Return ONLY the modified SQL."
        )
    elif gen_intent == "table":
        # A "generate table" request still resolves to a single read-only
        # SELECT that materializes the table — never CREATE/DDL.
        prompt_text = (
            f"{base_prompt}\n\n"
            "Return a single read-only SELECT query that produces this table. "
            "Do not emit CREATE TABLE, DDL, or any write statement."
        )

    # Fuzzy source match: when the prompt is essentially a source name given
    # without its physical suffix ("fin_gl_chart_of_accounts" for
    # "fin_gl_chart_of_accounts_CSV"), resolve it directly. A single confident
    # match is auto-selected; several plausible matches ask the user to choose.
    ai_result: dict[str, Any] = {}
    generated_sql = ""
    if not existing_query and allowed_tables:
        strong, close = _resolve_prompt_source(base_prompt, allowed_tables)
        if len(strong) == 1 and not close:
            matched = strong[0]
            generated_sql = f'SELECT * FROM "{matched}" LIMIT 100'
            ai_result = {
                "explanation": (
                    f'Matched your request to authorized source "{matched}".'
                ),
                "model_used": "source-match",
            }
        elif len(strong) > 1 or (not strong and len(close) > 1):
            return {
                "action": "generate_and_save_query",
                "status": "needs_clarification",
                "message": (
                    "I found multiple matching sources. Which one should I use?"
                ),
                "suggested_sources": (strong or close)[:5],
            }

    try:
        if not generated_sql:  # not resolved by fuzzy source match
            source_catalog = await _build_source_catalog(
                session, tenant_id=context.tenant_id, project_id=req.project_id
            )
            payload = {
                "tenant_id": context.tenant_id,
                "user_id": context.user_id,
                "project_id": req.project_id,
                "prompt": prompt_text,
                "allowed_tables": allowed_tables,
                "source_catalog": source_catalog,
                "preferred_sources": [],
                "relevant_columns": [],
                # Knowledge Graph context steers generated SQL toward validated
                # risks/gaps/measured KPIs surfaced by the graph.
                "knowledge_graph_context": await _kg_context(
                    session, context, req.project_id,
                ),
                "relationship_hints": relationship_hints,
            }
            ai_result = await _forward_to_ai("/ai/query/generate", payload)
            generated_sql = ai_result.get("sql", "").rstrip().rstrip(";")
            if generated_sql:
                generated_sql = rebuild_group_by_from_select(generated_sql)
    except HTTPException as exc:
        # A 422 means the AI generated SQL that could not be validated/repaired
        # (e.g. it could not map the request to an authorized source). Surface a
        # friendly, structured clarification instead of a raw validation error.
        if exc.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY:
            return _clarification_response(req.prompt, exc.detail, allowed_tables)
        # The local AI server is optional/may be offline. Rather than failing
        # the action outright, fall back to a deterministic query built from
        # the prompt + the project's available tables.
        if exc.status_code != status.HTTP_503_SERVICE_UNAVAILABLE:
            raise
        generated_sql = _heuristic_sql(req.prompt, allowed_tables)
        ai_result = {
            "explanation": (
                "Generated without the AI server (offline) — a baseline query "
                "from your prompt and available tables. Edit it as needed."
            ),
            "model_used": "heuristic-fallback",
        }

    if not generated_sql:
        generated_sql = _heuristic_sql(req.prompt, allowed_tables)
    if not generated_sql:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Could not generate SQL — connect a data source to this "
                "project first."
            ),
        )

    # Detect which datasource the SQL references
    left_datasource = _detect_datasource(generated_sql, allowed_tables)

    if existing_query:
        # Update the existing query in place
        existing_query.sql_text = generated_sql
        existing_query.left_datasource = left_datasource
        existing_query.description = req.description or req.prompt
        await session.commit()
        await session.refresh(existing_query)

        logger.info(
            "AI action: update_query | query_id=%d project=%d tenant=%d user=%d",
            existing_query.id, project.id, context.tenant_id, context.user_id,
        )
        return {
            "action": "update_query",
            "status": "updated",
            "query_id": existing_query.id,
            "name": existing_query.name,
            "sql_text": existing_query.sql_text,
        }

    # Step 2: Derive a name if not provided (from the cleaned prompt, so the
    # "generate table"/"generate query" verb isn't baked into the table name).
    name = req.name or _shorten_ai_name(base_prompt)

    # Step 3: Save as new query
    query = SavedQuery(
        project_id=project.id,
        owner_id=context.user_id,
        name=name,
        description=req.description or req.prompt,
        sql_text=generated_sql,
        left_datasource=left_datasource,
        ai_generated=True,
    )
    session.add(query)
    await session.commit()
    await session.refresh(query)

    logger.info(
        "AI action: generate_and_save_query | query_id=%d project=%d tenant=%d user=%d",
        query.id, project.id, context.tenant_id, context.user_id,
    )
    return {
        "action": "generate_and_save_query",
        "status": "saved",
        "query_id": query.id,
        "name": query.name,
        "sql_text": generated_sql,
        "explanation": ai_result.get("explanation", ""),
        "model_used": ai_result.get("model_used", ""),
        "selected_sources": ai_result.get("selected_sources", []),
        "repaired": ai_result.get("repaired", False),
    }
