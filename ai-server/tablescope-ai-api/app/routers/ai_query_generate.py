"""SQL generation and saved-query matching."""

import difflib
import logging
import re
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.core.activity import update_activity
from app.core.config import settings
from app.core.security import verify_signature
from app.models.schemas import (
    GenerateSQLRequest,
    GenerateSQLResponse,
    MatchQueryRequest,
    MatchQueryResponse,
    SelectedSource,
    SourceCatalogEntry,
)
from app.services import context_builder, llm_client
from app.services.context_builder import ContextBuildError
from app.services.kg_context import format_knowledge_graph_context
from app.services.sql_validator import SQLValidationError, validate_sql

from .ai_shared import _extract_sql

logger = logging.getLogger(__name__)
router = APIRouter()


def _needs_clarification(sql: str) -> bool:
    return "NEED_CLARIFICATION" in (sql or "").upper()


def _referenced_tables(sql: str) -> list[str]:
    """Table identifiers referenced in FROM/JOIN clauses of the SQL."""
    return re.findall(r"(?:FROM|JOIN)\s+\"?(\w+)\"?(?![\w(])", sql or "", re.IGNORECASE)


_SOURCE_SUFFIX_RE = re.compile(
    r"(_csv|_xlsx|_xls|_json|_parquet|_tsv|_table|_tbl|_view)$", re.IGNORECASE
)


def normalize_source_name(name: str) -> str:
    """Lowercase, drop a file-format suffix, and collapse separators to spaces.

    Lets ``fin_gl_chart_of_accounts`` / ``chart of accounts`` match the physical
    source ``fin_gl_chart_of_accounts_CSV`` even without the exact suffix.
    """
    text = _SOURCE_SUFFIX_RE.sub("", (name or "").strip().lower())
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _score_source_match(request: str, source: str) -> int:
    """Score how well ``request`` refers to authorized ``source`` (0–100)."""
    req = (request or "").strip().lower()
    src = (source or "").strip().lower()
    if not req or not src:
        return 0
    if req == src:
        return 100
    req_n = normalize_source_name(request)
    src_n = normalize_source_name(source)
    if req_n and req_n == src_n:
        return 95
    if req == _SOURCE_SUFFIX_RE.sub("", src):
        return 92
    req_tokens = [t for t in req_n.split() if t]
    src_tokens = {t for t in src_n.split() if t}
    if req_tokens and set(req_tokens).issubset(src_tokens):
        return 80
    if req_n and src_n and difflib.SequenceMatcher(None, req_n, src_n).ratio() >= 0.85:
        return 70
    if req_n and req_n in src_n:
        return 60
    return 0


def _catalog_table_columns(
    catalog: list[SourceCatalogEntry] | None,
) -> dict[str, list[str]]:
    """Extract ``{source name: real columns}`` for table-kind catalog entries.

    Feeds column-level validation so hallucinated column names (e.g.
    ``DefectRate`` when the real column is ``DefectQty``) are caught and sent
    back through the repair pass. Saved queries and sources without a known
    column list are skipped.
    """
    result: dict[str, list[str]] = {}
    for entry in catalog or []:
        if entry.kind == "query":
            continue
        if entry.name and entry.columns:
            result[entry.name] = list(entry.columns)
    return result


def _remap_tables_to_authorized(
    sql: str,
    allowed_tables: list[str],
    preferred_sources: list[str] | None = None,
) -> str:
    """Rewrite FROM/JOIN table references to their best-matching authorized source.

    The model frequently drops a source's file-format suffix — writing
    ``SUP_Quality_Inspections`` for the authorized ``SUP_Quality_Inspections_CSV`` —
    which then fails validation as an "unauthorized table reference". Deterministically
    remap each unauthorized identifier to the closest authorized table (using the same
    normalized/fuzzy scoring as source suggestions) so valid SQL is not rejected on a
    cosmetic name mismatch.

    When the semantic resolver has already auto-selected the source for this
    request (``preferred_sources``) and the model instead invents a table name
    with no confident fuzzy match (e.g. ``transactions``), the unknown reference
    is remapped to that single resolved source rather than left to fail. This is
    data-driven — it reuses the resolver's decision, not a hard-coded table — and
    only applies when exactly one source was resolved, so legitimate multi-table
    joins are never collapsed.
    """
    if not sql or not allowed_tables:
        return sql
    allowed_upper = {t.upper() for t in allowed_tables}
    # A single resolved source is a safe force-remap target for invented names.
    forced: str | None = None
    if preferred_sources:
        resolved = [s for s in preferred_sources if s.upper() in allowed_upper]
        if len(set(s.upper() for s in resolved)) == 1:
            forced = resolved[0]
    remapped = sql
    for ref in set(_referenced_tables(sql)):
        if ref.upper() in allowed_upper:
            continue
        best_score = 0
        best: str | None = None
        for table in allowed_tables:
            score = _score_source_match(ref, table)
            if score > best_score:
                best_score, best = score, table
        target: str | None = None
        if best and best_score >= 80:
            target = best
        elif forced is not None:
            target = forced
        if target and target.upper() != ref.upper():
            pattern = re.compile(rf'("?)\b{re.escape(ref)}\b("?)')
            remapped = pattern.sub(
                lambda m, t=target: f"{m.group(1)}{t}{m.group(2)}", remapped
            )
    return remapped


def _suggest_sources(prompt: str, allowed_tables: list[str], limit: int = 5) -> list[str]:
    """Rank authorized sources by normalized/fuzzy match with the user's prompt."""
    scored = sorted(
        ((_score_source_match(prompt, t), t) for t in allowed_tables),
        key=lambda x: (-x[0], x[1]),
    )
    ranked = [t for score, t in scored if score > 0]
    return (ranked or allowed_tables)[:limit]


def _selected_sources(
    prompt: str, sql: str, allowed_tables: list[str]
) -> list[SelectedSource]:
    """Sources the generated SQL actually uses, with a short match reason."""
    allowed_by_upper = {t.upper(): t for t in allowed_tables}
    seen: set[str] = set()
    out: list[SelectedSource] = []
    prompt_tokens = {t for t in re.split(r"[^a-z0-9]+", prompt.lower()) if len(t) > 2}
    for ref in _referenced_tables(sql):
        canonical = allowed_by_upper.get(ref.upper())
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        parts = {p for p in re.split(r"[^a-z0-9]+", canonical.lower()) if len(p) > 2}
        matched = sorted(
            p for p in parts if any(p in tok or tok in p for tok in prompt_tokens)
        )
        reason = (
            f"Matched '{', '.join(matched)}' in your request"
            if matched
            else "Authorized project source"
        )
        out.append(SelectedSource(name=canonical, reason=reason))
    return out


@router.post("/query/generate", response_model=GenerateSQLResponse)
async def generate_sql_endpoint(req: GenerateSQLRequest) -> GenerateSQLResponse:
    """Generate SQL from a natural language prompt.

    Pipeline: semantic source discovery → generate → validate → repair (up to
    2 attempts) → return SQL + the sources the AI selected. If the model cannot
    map the request to an authorized source it raises 422 with suggested
    sources so the app can show a friendly clarification.
    """
    request_id = str(uuid.uuid4())
    verify_signature(req.model_dump(exclude={"signature"}), req.signature)

    try:
        ctx = await context_builder.build_context(
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            project_id=req.project_id,
            scope="project",
            question=req.prompt,
            feature="generate_sql",
            grounding_evidence=req.grounding_evidence,
        )
    except ContextBuildError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: {e.reason}",
        )

    context_text = context_builder.context_to_prompt_text(ctx)

    # Fold in the Knowledge Graph context so generated SQL targets the validated
    # risks/gaps/measured KPIs the graph surfaces (never Reference Library docs).
    kg_block = format_knowledge_graph_context(req.knowledge_graph_context)
    if kg_block:
        context_text = f"{context_text}\n\n{kg_block}"

    # Determine allowed tables
    allowed_tables = req.allowed_tables
    if not allowed_tables:
        allowed_tables = [
            ds.get("view_name", ds.get("name", ""))
            for ds in ctx.allowed_context.get("metadata", [])
            if ds.get("view_name") or ds.get("name")
        ]

    catalog = req.source_catalog or None
    table_columns = _catalog_table_columns(catalog)

    def _clarify(reason: str) -> HTTPException:
        suggestions = _suggest_sources(req.prompt, allowed_tables)
        logger.warning(
            "SQL generation needs clarification | tenant=%d project=%d | %s | "
            "suggested=%s",
            req.tenant_id, req.project_id, reason, suggestions,
        )
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "needs_clarification",
                "message": (
                    "Could not match part of your request to an authorized "
                    "project source."
                ),
                "reason": reason,
                "suggested_sources": suggestions,
            },
        )

    # Initial generation. Extract a single clean SQL statement so any prose the
    # model wraps around the query never reaches Teiid.
    raw = await llm_client.generate_sql(
        prompt=req.prompt,
        context=context_text,
        allowed_tables=allowed_tables,
        source_catalog=catalog,
        preferred_sources=req.preferred_sources,
        relevant_columns=req.relevant_columns,
    )
    if _needs_clarification(raw):
        raise _clarify("Model could not find a matching authorized source.")
    sql = _extract_sql(raw)
    if not sql:
        raise _clarify("Model did not return a runnable SQL query.")

    repaired = False
    last_error = ""
    # Validate, then repair up to 2 times. Remap cosmetic table-name mismatches
    # (e.g. a dropped ``_CSV`` suffix) to the authorized source before validating
    # so a valid query is not rejected on a name technicality.
    for attempt in range(3):
        sql = _remap_tables_to_authorized(
            sql, allowed_tables, preferred_sources=req.preferred_sources
        )
        try:
            validate_sql(sql, allowed_tables, table_columns=table_columns)
            break
        except SQLValidationError as e:
            last_error = e.reason
            if attempt >= 2:
                raise _clarify(e.reason)
            logger.info(
                "Repairing generated SQL (attempt %d) | error=%s",
                attempt + 1, e.reason,
            )
            raw = await llm_client.repair_sql(
                prompt=req.prompt,
                context=context_text,
                allowed_tables=allowed_tables,
                failed_sql=sql,
                validation_error=e.reason,
                source_catalog=catalog,
                preferred_sources=req.preferred_sources,
                relevant_columns=req.relevant_columns,
            )
            repaired = True
            if _needs_clarification(raw):
                raise _clarify(last_error)
            sql = _extract_sql(raw)
            if not sql:
                raise _clarify(last_error or "Model did not return a runnable SQL query.")

    selected = _selected_sources(req.prompt, sql, allowed_tables)

    update_activity(req.user_id, req.tenant_id, req.project_id)

    logger.info(
        "SQL generated | tenant=%d project=%d repaired=%s sources=%s",
        req.tenant_id, req.project_id, repaired, [s.name for s in selected],
    )

    grounding_manifest: dict[str, Any] | None = None
    if req.grounding_evidence:
        grounding_manifest = {
            "question": req.grounding_evidence.question,
            "passage_count": len(req.grounding_evidence.passages),
            "kg_node_count": len(req.grounding_evidence.kg_nodes),
            "kpi_count": len(req.grounding_evidence.kpis),
            "retrieved_at": req.grounding_evidence.retrieved_at.isoformat(),
        }

    return GenerateSQLResponse(
        sql=sql,
        explanation="",
        allowed_tables_used=allowed_tables,
        request_id=request_id,
        model_used=settings.sql_model,
        selected_sources=selected,
        repaired=repaired,
        knowledge_graph_context_used=bool(kg_block),
        grounding_manifest=grounding_manifest,
    )


@router.post("/query/match", response_model=MatchQueryResponse)
async def match_query(req: MatchQueryRequest) -> MatchQueryResponse:
    """Find an existing saved query functionally equivalent to a candidate.

    Used during dashboard creation to avoid creating duplicate queries. Returns
    match_id of the equivalent existing query, or None if none match.
    """
    request_id = str(uuid.uuid4())
    verify_signature(req.model_dump(exclude={"signature"}), req.signature)

    if not req.existing_queries:
        return MatchQueryResponse(
            match_id=None, request_id=request_id, model_used=settings.reasoning_model,
        )

    existing_text = "\n".join(
        f"  ID={q.id}, Name=\"{q.name}\", SQL: {q.sql}"
        for q in req.existing_queries
    )
    prompt = (
        f"A new dashboard widget needs this query:\n"
        f"  Title: \"{req.candidate_title}\"\n"
        f"  SQL: {req.candidate_sql}\n\n"
        f"Here are the existing saved queries in the project:\n"
        f"{existing_text}\n\n"
        f"Does any existing query produce the SAME result (same columns, same "
        f"data, same aggregations, same grouping)? Minor differences like column "
        f"order, aliases, CAST wrappers, LIMIT values, or whitespace don't "
        f"matter — only whether the data returned is functionally equivalent.\n\n"
        f"If YES: respond with ONLY: MATCH=<id>\n"
        f"If NO existing query matches: respond with ONLY: NO_MATCH"
    )

    raw = await llm_client.generate(
        prompt=prompt,
        system_prompt=(
            "You compare SQL queries for functional equivalence. "
            "Respond with ONLY 'MATCH=<id>' or 'NO_MATCH' — no other text."
        ),
        model=settings.reasoning_model,
        temperature=0.0,
    )

    match_id: int | None = None
    m = re.search(r"MATCH\s*=\s*(\d+)", raw)
    if m:
        candidate_id = int(m.group(1))
        if any(q.id == candidate_id for q in req.existing_queries):
            match_id = candidate_id

    update_activity(req.user_id, req.tenant_id, req.project_id)

    return MatchQueryResponse(
        match_id=match_id, request_id=request_id, model_used=settings.reasoning_model,
    )
