"""AI feature endpoints — all requests flow through the context builder.

Every endpoint:
1. Verifies HMAC signature (request came from trusted app server)
2. Builds permission-aware context via context_builder
3. Sends ONLY allowed context to the LLM
4. Validates LLM output (SQL allowlist, no cross-tenant refs)
5. Logs everything (vectors accessed, context used, denied access)
6. Updates last_activity for idle shutdown
"""

import difflib
import json
import logging
import re
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.core.activity import update_activity
from app.core.config import settings
from app.core.security import verify_signature
from app.models.schemas import (
    AnalyzeFileRequest,
    AnalyzeFileResponse,
    AnalyzeScopesRequest,
    AnalyzeScopesResponse,
    AskRequest,
    AskResponse,
    DocumentProfileRequest,
    DocumentProfileResponse,
    FamilySummarizeRequest,
    FamilySummarizeResponse,
    GenerateRelationshipsRequest,
    GenerateRelationshipsResponse,
    GenerateSQLRequest,
    GenerateSQLResponse,
    IndexDocumentRequest,
    IndexReferenceRequest,
    IntelligenceFixSQLRequest,
    IntelligenceFixSQLResponse,
    IntelligenceInterpretRequest,
    IntelligenceInterpretResponse,
    IntelligencePlanRequest,
    IntelligencePlanResponse,
    InterpretedInsight,
    KnowledgeGraphCard,
    KnowledgeGraphInsightRequest,
    KnowledgeGraphInsightResponse,
    MatchQueryRequest,
    MatchQueryResponse,
    PlannedAnalysis,
    ProjectInsightExecutiveSummary,
    ProjectInsightRequest,
    ProjectInsightResponse,
    ReferenceSuggestRequest,
    ReferenceSuggestResponse,
    ReferenceSummarizeRequest,
    ReferenceSummarizeResponse,
    RelationshipSuggestion,
    ScopeSuggestion,
    SelectedSource,
    SourceCatalogEntry,
    DashboardPlanSuggestion,
    DashboardPlanWidget,
    SuggestDashboardRequest,
    SuggestDashboardResponse,
    SuggestDashboardsMultiRequest,
    SuggestDashboardsMultiResponse,
)
from app.services import context_builder, llm_client, vector_store
from app.services.context_builder import ContextBuildError
from app.services.kg_context import format_knowledge_graph_context
from app.services.prompt_loader import load_prompt_reference
from app.services.sql_validator import SQLValidationError, validate_sql

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["AI"])

def _fix_teiid_group_by(sql: str) -> str:
    """Replace alias references in GROUP BY / ORDER BY with the actual SELECT expression.

    Teiid does not allow column aliases in GROUP BY.
    E.g. ``SELECT FORMATDATE(...) AS SalesMonth ... GROUP BY SalesMonth``
    becomes ``GROUP BY FORMATDATE(...)``.
    """
    # Extract SELECT aliases: "expr AS alias"
    select_match = re.search(r'SELECT\s+(.*?)\s+FROM\s', sql, re.IGNORECASE | re.DOTALL)
    if not select_match:
        return sql

    aliases: dict[str, str] = {}
    select_body = select_match.group(1)
    # Split on commas that are not inside parentheses
    depth = 0
    parts: list[str] = []
    current: list[str] = []
    for ch in select_body:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == ',' and depth == 0:
            parts.append(''.join(current).strip())
            current = []
            continue
        current.append(ch)
    parts.append(''.join(current).strip())

    for part in parts:
        as_match = re.match(r'(.+?)\s+AS\s+(\w+)\s*$', part, re.IGNORECASE)
        if as_match:
            expr = as_match.group(1).strip()
            alias = as_match.group(2).strip()
            aliases[alias.upper()] = expr

    if not aliases:
        return sql

    def replace_alias_in_clause(clause_match: re.Match[str]) -> str:
        keyword = clause_match.group(1)
        body = clause_match.group(2)
        for alias_upper, expr in aliases.items():
            body = re.sub(
                rf'\b{re.escape(alias_upper)}\b',
                expr,
                body,
                flags=re.IGNORECASE,
            )
        return f"{keyword} {body}"

    sql = re.sub(
        r'(GROUP\s+BY)\s+(.*?)(?=ORDER|HAVING|LIMIT|;|\Z)',
        replace_alias_in_clause,
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return sql


def _clean_sql(raw: str) -> str:
    """Remove markdown fences and fix Teiid-incompatible SQL patterns."""
    sql = raw.strip()
    if sql.startswith("```"):
        sql = sql.split("```")[1]
        if sql.startswith("sql"):
            sql = sql[3:]
        sql = sql.strip()
    sql = _fix_teiid_group_by(sql)
    return sql


# A CTE starts with ``WITH <name> AS (`` — matching that (rather than a bare
# ``WITH``) avoids treating the word "with" inside prose as the start of SQL.
_WITH_CTE_RE = re.compile(r"\bWITH\s+\"?\w+\"?\s+AS\s*\(", re.IGNORECASE)
_SELECT_RE = re.compile(r"\bSELECT\b", re.IGNORECASE)


def _extract_sql(raw: str) -> str:
    """Extract a single clean, read-only SQL statement from a model response.

    Models sometimes wrap SQL in markdown, prefix it with prose ("To calculate
    the defect rate ..."), or append an explanation after the query. Any of that
    reaching Teiid raises a parser error (``TEIID31100 ... Encountered "To ..."``),
    so this strips everything before the first ``SELECT``/``WITH`` statement and
    everything after the first complete statement. Returns "" when the response
    contains no SQL statement, so the caller can ask for clarification instead of
    executing prose.
    """
    if not raw:
        return ""
    text = raw.strip()
    # Prefer a fenced ```sql block when present; keep the fenced body only.
    if "```" in text:
        for seg in text.split("```"):
            candidate = seg.strip()
            if candidate.lower().startswith("sql"):
                candidate = candidate[3:].strip()
            if _SELECT_RE.search(candidate) or _WITH_CTE_RE.search(candidate):
                text = candidate
                break
    starts = [
        m.start()
        for m in (_SELECT_RE.search(text), _WITH_CTE_RE.search(text))
        if m
    ]
    if not starts:
        return ""
    text = text[min(starts):]
    # Keep only the first statement — drop trailing statements/prose.
    semicolon = text.find(";")
    if semicolon != -1:
        text = text[:semicolon]
    return _fix_teiid_group_by(text.strip()).strip()


SYSTEM_PROMPT = (
    "You are Tablescope AI, an assistant for the user's active project.\n"
    "Answer using ONLY the provided context package (project metadata/tables, "
    "uploaded documents, saved queries, dashboards, and relationships).\n"
    "Do not request or infer access to data outside the provided context.\n"
    "\n"
    "Decide how to respond based on the question:\n"
    "- If the user asks about an uploaded document, a concept, a policy, a "
    "summary, or anything explanatory, answer in clear natural language grounded "
    "in the document context. Reference the relevant document by name and quote "
    "or paraphrase the supporting passage.\n"
    "- If the user asks for data, metrics, or records from the project's tables, "
    "generate a single read-only SQL query using only the allowed tables and "
    "columns. Do not use SELECT *. Never generate INSERT, UPDATE, DELETE, DROP, "
    "or any write operation.\n"
    "\n"
    "If the context is insufficient to answer, say specifically what additional "
    "project data or document would be needed. Do not invent facts.\n"
    "\n"
    "Use the prior messages in this conversation to interpret follow-up "
    "questions. If the user says \"that\", \"it\", \"the second option\", "
    "\"explain more\", or \"continue\", resolve the reference from the "
    "conversation history above rather than asking them to restate it.\n"
)


# Cap history sent to the model so long conversations stay within budget.
_MAX_HISTORY_TURNS = 20


def _format_conversation_history(history: list[dict[str, Any]]) -> str:
    """Render prior conversation turns into a prompt block (oldest→newest)."""
    if not history:
        return ""
    lines: list[str] = []
    for msg in history[-_MAX_HISTORY_TURNS:]:
        content = str(msg.get("content") or "").strip()
        if not content:
            continue
        role = str(msg.get("role") or "user").lower()
        speaker = "User" if role == "user" else "Assistant"
        lines.append(f"{speaker}: {content}")
    if not lines:
        return ""
    return "Conversation so far:\n" + "\n".join(lines) + "\n\n"


@router.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    """Ask Tablescope AI a question about the active project."""
    request_id = str(uuid.uuid4())

    # 1. Verify signature
    verify_signature(req.model_dump(exclude={"signature"}), req.signature)

    # 2. Build permission-aware context
    try:
        ctx = await context_builder.build_context(
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            project_id=req.project_id,
            scope=req.scope,
            question=req.question,
            feature="ask",
        )
    except ContextBuildError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: {e.reason}",
        )

    # 3. Send ONLY allowed context to LLM
    context_text = context_builder.context_to_prompt_text(ctx)
    history_text = _format_conversation_history(req.history)
    prompt = f"{context_text}\n\n{history_text}User question: {req.question}"

    answer = await llm_client.generate(
        prompt=prompt,
        system_prompt=SYSTEM_PROMPT,
        model=settings.reasoning_model,
    )

    # 4. Update activity
    update_activity(req.user_id, req.tenant_id, req.project_id)

    # 5. Log
    logger.info(
        "AI ask | request_id=%s tenant=%d project=%d user=%d",
        request_id, req.tenant_id, req.project_id, req.user_id,
    )

    return AskResponse(
        answer=answer,
        model_used=settings.reasoning_model,
        request_id=request_id,
        context_summary={
            "metadata_count": len(ctx.allowed_context.get("metadata", [])),
            "document_count": len(ctx.allowed_context.get("documents", [])),
            "project_document_count": len(
                ctx.allowed_context.get("project_documents", [])
            ),
            "query_count": len(ctx.allowed_context.get("queries", [])),
        },
    )


@router.post("/index/document")
async def index_document(req: IndexDocumentRequest) -> dict:
    """Index a project document into the tenant's vector collection."""
    request_id = str(uuid.uuid4())
    verify_signature(req.model_dump(exclude={"signature"}), req.signature)

    # Ensure tenant collection exists
    await vector_store.ensure_collection(req.tenant_id)

    # Chunk the content
    content = req.content
    if not content:
        return {"status": "no_content", "request_id": request_id}

    # Simple chunking (512 char chunks with 50 char overlap)
    chunk_size = 512
    overlap = 50
    chunks: list[str] = []
    for i in range(0, len(content), chunk_size - overlap):
        chunk = content[i:i + chunk_size]
        if chunk.strip():
            chunks.append(chunk)

    if not chunks:
        return {"status": "no_chunks", "request_id": request_id}

    # Generate embeddings
    embeddings = await llm_client.generate_embeddings(chunks)

    # Build payloads with security fields
    payloads = []
    for idx, chunk in enumerate(chunks):
        payloads.append({
            "tenant_id": req.tenant_id,
            "project_id": req.project_id,
            "document_id": req.document_id,
            "chunk_id": f"chunk_{idx:04d}",
            "chunk_index": idx,
            "chunk_text": chunk,
            "visibility": req.visibility,
            "owner_user_id": req.user_id,
            "source_type": req.source_type,
            "source_id": req.source_id,
            "embedding_model": settings.embedding_model,
        })

    # Upsert into tenant-specific collection
    point_ids = await vector_store.upsert_vectors(
        tenant_id=req.tenant_id,
        vectors=embeddings,
        payloads=payloads,
    )

    update_activity(req.user_id, req.tenant_id, req.project_id)

    logger.info(
        "Indexed document %d: %d chunks | tenant=%d project=%d",
        req.document_id, len(chunks), req.tenant_id, req.project_id,
    )

    return {
        "status": "indexed",
        "document_id": req.document_id,
        "chunks_indexed": len(chunks),
        "vector_ids": point_ids,
        "request_id": request_id,
    }


@router.post("/index/reference")
async def index_reference(req: IndexReferenceRequest) -> dict:
    """Index a reference-library document into the shared, tier-scoped store.

    Reference docs are governed knowledge (industry/company/project tier) made
    available to the AI assistant and Home planner across projects. Re-indexing
    is idempotent: existing chunks for the document are dropped first.
    """
    request_id = str(uuid.uuid4())
    verify_signature(req.model_dump(exclude={"signature"}), req.signature)

    await vector_store.delete_reference_document(req.document_id)

    content = req.content
    if not content.strip():
        return {"status": "no_content", "request_id": request_id}

    # Simple chunking (512 char chunks with 50 char overlap) — mirrors documents.
    chunk_size = 512
    overlap = 50
    chunks: list[str] = []
    for i in range(0, len(content), chunk_size - overlap):
        chunk = content[i:i + chunk_size]
        if chunk.strip():
            chunks.append(chunk)

    if not chunks:
        return {"status": "no_chunks", "request_id": request_id}

    embeddings = await llm_client.generate_embeddings(chunks)

    payloads = []
    for idx, chunk in enumerate(chunks):
        payloads.append({
            "tier": req.tier,
            "tenant_id": req.tenant_id,
            "project_id": req.project_id,
            "document_id": req.document_id,
            "title": req.title,
            "chunk_id": f"chunk_{idx:04d}",
            "chunk_index": idx,
            "chunk_text": chunk,
            "source_type": "reference_library",
            "embedding_model": settings.embedding_model,
        })

    point_ids = await vector_store.upsert_reference_vectors(
        vectors=embeddings,
        payloads=payloads,
    )

    logger.info(
        "Indexed reference document %d (%s): %d chunks",
        req.document_id, req.tier, len(chunks),
    )

    return {
        "status": "indexed",
        "document_id": req.document_id,
        "chunks_indexed": len(chunks),
        "vector_ids": point_ids,
        "request_id": request_id,
    }


@router.post("/project/relationships/generate", response_model=GenerateRelationshipsResponse)
async def generate_relationships(req: GenerateRelationshipsRequest) -> GenerateRelationshipsResponse:
    """Generate suggested relationships between project tables."""
    request_id = str(uuid.uuid4())
    verify_signature(req.model_dump(exclude={"signature"}), req.signature)

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
        model=settings.sql_model,
        temperature=0.0,
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
        model_used=settings.sql_model,
    )


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

    return GenerateSQLResponse(
        sql=sql,
        explanation="",
        allowed_tables_used=allowed_tables,
        request_id=request_id,
        model_used=settings.sql_model,
        selected_sources=selected,
        repaired=repaired,
        knowledge_graph_context_used=bool(kg_block),
    )


_DASHBOARD_INSIGHT_SYSTEM_PROMPT = (
    "You are Tablescope AI acting as a senior business analyst, KPI strategist, "
    "and dashboard designer working inside ONE authorized Tablescope project. "
    "Your job is NOT to create generic charts from whatever tables exist. First "
    "reason about what a well-run company in this domain should monitor, where "
    "risk or opportunity lives, and which insights deserve dashboard placement — "
    "THEN choose the single best visualization for each insight and write the "
    "SQL that proves it.\n"
    "Use ONLY the authorized project context provided in the request (tables, "
    "columns, saved queries, documents, KPI references, reference-library "
    "standards, and relationships). Never reference data outside it. Do not "
    "invent tables, columns, metrics, thresholds, benchmarks, dates, values, or "
    "documents. If the context cannot support a proposed insight, leave it out. "
    "Prefer fewer strong, non-empty, decision-grade widgets over many weak ones."
)


@router.post("/dashboard/suggest", response_model=SuggestDashboardResponse)
async def suggest_dashboard(req: SuggestDashboardRequest) -> SuggestDashboardResponse:
    """Suggest dashboard widgets based on project data (insight-first).

    Reasons like a senior analyst over the project's real schema, documents, KPI
    references, and reference library, then emits chart-ready widget specs with
    validation expectations and priority/confidence scores. The platform-api
    judge stage executes each widget's SQL and drops empty/weak ones before save.
    """
    request_id = str(uuid.uuid4())
    verify_signature(req.model_dump(exclude={"signature"}), req.signature)

    try:
        ctx = await context_builder.build_context(
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            project_id=req.project_id,
            scope="project",
            question="",
            feature="suggest_dashboard",
        )
    except ContextBuildError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: {e.reason}",
        )

    context_text = context_builder.context_to_prompt_text(ctx)

    # Determine allowed tables
    allowed_tables = req.allowed_tables
    if not allowed_tables:
        allowed_tables = [
            ds.get("view_name", ds.get("name", ""))
            for ds in ctx.allowed_context.get("metadata", [])
            if ds.get("view_name") or ds.get("name")
        ]

    user_instruction = ""
    if req.prompt:
        user_instruction = f"\nUser request: {req.prompt}\n"

    chart_catalog = (
        "Supported chart types — pick the SINGLE best one per insight; never "
        "default everything to bar:\n"
        "- kpi / kpi_grid: one or a few executive headline numbers (single-row aggregate).\n"
        "- bar (vertical): compact category comparisons or period buckets.\n"
        "- horizontal_bar: ranked categories with long labels — suppliers, customers, products, regions, top-N.\n"
        "- stacked_bar: category composition over another category or period.\n"
        "- grouped_bar: side-by-side comparison of 2+ metrics across categories.\n"
        "- line: trends over time.\n"
        "- dual_line: two related metrics over the same time axis.\n"
        "- area: cumulative or volume-over-time.\n"
        "- pie / donut: true part-to-whole share with 2-8 slices only.\n"
        "- table / pivot_table: operational detail users can act on.\n"
        "- heatmap: a metric across two categorical dimensions (intensity).\n"
        "- scatter / bubble: relationship/correlation between two (or three) metrics.\n"
        "- treemap: many categories' relative sizes.\n"
        "- waterfall: bridge analysis / variance decomposition / contribution to change.\n"
        "- funnel: stage conversion / drop-off.\n"
        "- gauge / bullet: a metric vs an explicit target, threshold, SLA, or benchmark.\n"
        "- radar: multi-metric comparison of a few items.\n"
        "- sparkline_table: many entities each with an inline trend + current value.\n"
        "- narrative_insight: a document-driven finding better told as prose (no SQL).\n"
    )

    best_practices = load_prompt_reference("dashboard_best_practices.md")
    best_practices_block = (
        f"Dashboard Best Practices (authoritative policy):\n{best_practices}\n\n"
        if best_practices
        else ""
    )

    kg_block = format_knowledge_graph_context(req.knowledge_graph_context)
    kg_prompt_block = f"{kg_block}\n\n" if kg_block else ""

    prompt = (
        f"{context_text}\n\n"
        f"{kg_prompt_block}"
        f"{best_practices_block}"
        f"Allowed tables (use ONLY these exact names): {', '.join(allowed_tables)}\n\n"
        "CRITICAL: every widget's SQL must reference ONLY the allowed tables "
        "above. Never invent or assume any other table (e.g. Sales, Product, "
        "Customers).\n\n"
        f"{_TEIID_SQL_RULES}\n"
        f"{user_instruction}\n"
        "Think like a senior business analyst and KPI strategist. Do NOT start "
        "by making charts. First decide what a well-run company in this domain "
        "should monitor, where the risk or opportunity is, and which insights "
        "deserve dashboard placement. THEN, for each insight, choose the single "
        "chart type that best communicates it and write the SQL that proves it.\n\n"
        "Grounding rules:\n"
        "- Use the project's real tables/columns, saved queries, documents, KPI "
        "references, and reference-library standards shown above as evidence.\n"
        "- Do NOT invent tables, columns, metrics, thresholds, dates, or values. "
        "If the context cannot support an insight, leave it out.\n"
        "- Prefer business impact over chart quantity; prefer fewer strong "
        "widgets over many weak ones.\n"
        "- Use reference-library thresholds/SLAs/benchmarks as target lines ONLY "
        "when the value is explicit in the provided content, and cite the "
        "document in reference_lines[].source_document.\n"
        "- For any time-series chart, GROUP BY a sortable STRING period label "
        "built with FORMATTIMESTAMP — default to month 'yyyy-MM' so a single "
        "year still shows a trend; use 'yyyy' only across 3+ years. NEVER group "
        "by a bare numeric year (it collapses to one point and renders as a "
        "meaningless '2.0K' tile). Put the period first in SELECT, ORDER BY it, "
        "and only build a trend when >= 3 periods exist — otherwise use a KPI or "
        "category comparison. When the data spans 2+ years, prefer a "
        "year-over-year view (month on the axis; year as the series or a "
        "prior-year value_column_2) so this year is shown against last year.\n"
        "- Do NOT create a pie/donut unless it is a true part-to-whole with 2-8 "
        "slices. Do NOT create a KPI unless it is an executive-level number.\n"
        "- Avoid WHERE filters on guessed values; only filter on values proven "
        "by the schema/sample context or explicitly requested by the user.\n"
        "- Do NOT include a widget you expect to return no rows.\n\n"
        f"{chart_catalog}\n"
        "SQL rules: read-only, never SELECT *, give every selected expression a "
        "stable alias, and make label_column / value_column / value_column_2 / "
        "series_column / target_column EXACTLY match aliases in the SELECT list. "
        "Query a single allowed table per widget (no JOINs).\n\n"
        "Layout: 12-column grid. Put the highest-priority executive KPIs in the "
        "top row, place related charts near each other, give trend/table/heatmap/"
        "waterfall charts more width (gridW 8-12), and create a clear top-left to "
        "bottom-right reading path. Aim for 4-8 strong widgets.\n\n"
        "Return ONLY a JSON object:\n"
        "{\n"
        '  "title": "dashboard name",\n'
        '  "description": "one-line description",\n'
        '  "business_domain": "",\n'
        '  "intended_audience": "executive|manager|analyst|operational",\n'
        '  "executive_summary": "2-3 sentences on what this dashboard answers",\n'
        '  "widgets": [ {\n'
        '    "type": "<one chart type from the catalog>",\n'
        '    "title": "short widget title",\n'
        '    "subtitle": "",\n'
        '    "business_question": "the executive question this answers",\n'
        '    "sql": "SELECT ... (empty for narrative_insight)",\n'
        '    "label_column": "alias for the category/x axis",\n'
        '    "value_column": "alias for the primary numeric value",\n'
        '    "value_column_2": "alias for a 2nd metric (dual_line/scatter/bubble/target) or empty",\n'
        '    "series_column": "alias that splits series (stacked/grouped) or empty",\n'
        '    "target_column": "alias holding a target/threshold (gauge/bullet) or empty",\n'
        '    "x_column": "alias for x (scatter/bubble) or empty",\n'
        '    "y_column": "alias for y (scatter/bubble) or empty",\n'
        '    "aggregation": "count|sum|avg|min|max",\n'
        '    "reference_lines": [ {"label": "", "value": null, "source_document": ""} ],\n'
        '    "drilldown_fields": [],\n'
        '    "validation_expectations": {\n'
        '      "minimum_rows": 1, "required_columns": [], "non_null_columns": [],\n'
        '      "chart_requires_multiple_rows": false, "empty_result_action": "drop_widget"\n'
        "    },\n"
        '    "priority_score": 0,\n'
        '    "confidence_score": 0.0,\n'
        '    "gridX": 0, "gridY": 0, "gridW": 6, "gridH": 4\n'
        "  } ]\n"
        "}\n\n"
        "OUTPUT FORMAT: respond with this JSON object and nothing else — no "
        "prose, no markdown, no code fences. Begin with { and end with }."
    )

    raw = await llm_client.generate(
        prompt=prompt,
        system_prompt=_DASHBOARD_INSIGHT_SYSTEM_PROMPT,
        model=settings.sql_model,
        temperature=0.3,
        # Larger window so the injected dashboard_best_practices reference fits
        # alongside the project context without truncation.
        num_ctx=24576,
        response_format="json",
    )

    suggestions: list[dict] = []
    parsed = _parse_json_response(raw)
    if isinstance(parsed, dict):
        suggestions = [parsed]
    elif isinstance(parsed, list):
        suggestions = [s for s in parsed if isinstance(s, dict)]
    else:
        logger.warning("Failed to parse dashboard suggestions: %s", raw[:200])

    # Post-process: fix Teiid GROUP BY aliases in each widget's SQL, then drop
    # any widget whose SQL references a table outside the project's allowed set.
    # The LLM occasionally hallucinates generic tables (e.g. "Sales", "Product")
    # that do not belong to this tenant/project; those must never reach the user.
    # Widgets with no SQL (narrative_insight) are kept — they are document-driven.
    for s in suggestions:
        kept_widgets = []
        for w in s.get("widgets", []):
            sql = w.get("sql")
            if sql:
                w["sql"] = _clean_sql(sql)
                try:
                    validate_sql(w["sql"], allowed_tables)
                except SQLValidationError as e:
                    logger.warning(
                        "Dropping suggested widget %r: %s",
                        w.get("title", "untitled"), e.reason,
                    )
                    continue
            kept_widgets.append(w)
        # Highest-priority widgets first so the executive reading path is sound.
        kept_widgets.sort(
            key=lambda w: float(w.get("priority_score") or 0), reverse=True
        )
        s["widgets"] = kept_widgets

    update_activity(req.user_id, req.tenant_id, req.project_id)

    return SuggestDashboardResponse(
        suggestions=suggestions,
        request_id=request_id,
        model_used=settings.sql_model,
    )


@router.post(
    "/dashboard/suggest-multi", response_model=SuggestDashboardsMultiResponse
)
async def suggest_dashboards_multi(
    req: SuggestDashboardsMultiRequest,
) -> SuggestDashboardsMultiResponse:
    """Suggest several distinct dashboard *plans* (insight-first, lightweight).

    Returns at least ``desired_count`` plans, each grounded in the project's real
    tables, KPI references, and reference-library standards. These are previews:
    the heavy SQL validation/build happens on save via the existing
    generate-and-save-dashboard pipeline.
    """
    request_id = str(uuid.uuid4())
    verify_signature(req.model_dump(exclude={"signature"}), req.signature)

    try:
        ctx = await context_builder.build_context(
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            project_id=req.project_id,
            scope="project",
            question="",
            feature="suggest_dashboard",
        )
    except ContextBuildError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: {e.reason}",
        )

    context_text = context_builder.context_to_prompt_text(ctx)

    allowed_tables = req.allowed_tables
    if not allowed_tables:
        allowed_tables = [
            ds.get("view_name", ds.get("name", ""))
            for ds in ctx.allowed_context.get("metadata", [])
            if ds.get("view_name") or ds.get("name")
        ]

    desired = max(3, int(req.desired_count or 3))
    audience_line = (
        f"Target audience: {req.audience}.\n" if req.audience else ""
    )
    user_instruction = f"\nUser request: {req.prompt}\n" if req.prompt else ""
    kpi_line = (
        f"Known project KPIs (cover the relevant ones): {', '.join(req.kpis)}\n"
        if req.kpis
        else ""
    )

    best_practices = load_prompt_reference("dashboard_best_practices.md")
    best_practices_block = (
        f"Dashboard Best Practices (authoritative policy):\n{best_practices}\n\n"
        if best_practices
        else ""
    )

    kg_block = format_knowledge_graph_context(req.knowledge_graph_context)
    kg_prompt_block = f"{kg_block}\n\n" if kg_block else ""

    prompt = (
        f"{context_text}\n\n"
        f"{kg_prompt_block}"
        f"{best_practices_block}"
        f"Allowed tables (use ONLY these exact names): {', '.join(allowed_tables)}\n\n"
        f"{audience_line}"
        f"{kpi_line}"
        f"{user_instruction}\n"
        f"Propose {desired} DISTINCT, non-overlapping dashboard PLANS a senior "
        "analyst would build for this project. Each plan must target a different "
        "business theme, audience, or decision (e.g. executive overview, supplier "
        "quality & risk, on-time delivery & operations). Think first about what "
        "matters; do not just regroup the same charts.\n\n"
        "Grounding rules:\n"
        "- Ground every plan in the project's REAL tables, columns, saved "
        "queries, documents, KPI references, and reference-library standards "
        "shown above.\n"
        "- Do NOT invent tables, columns, metrics, KPIs, or data sources. Only "
        "list data_sources from the allowed tables and kpis from the project's "
        "real KPI references.\n"
        "- Reference Library documents are authoritative guidance, NOT data "
        "sources: never list a reference document as a data source.\n"
        "- 3-6 widgets per plan. Each chart/table/KPI widget MUST include a "
        "complete, runnable SQL query grounded in the allowed tables/columns "
        "above so the dashboard can render real data. Use exact table and column "
        "names; aggregate where appropriate; add ORDER BY and a small LIMIT "
        "(<= 12 rows) for ranked/top-N widgets.\n"
        "- For each widget also name the label_column (category/x axis) and "
        "value_column (numeric/y axis) from the SELECT list.\n"
        "- A narrative/risk/gap widget (chart_type 'narrative_insight') has an "
        "empty sql; use these sparingly and prefer real data widgets.\n\n"
        f"Return ONLY a JSON object with at least {desired} suggestions:\n"
        "{\n"
        '  "suggestions": [ {\n'
        '    "title": "dashboard name",\n'
        '    "description": "one-line description",\n'
        '    "business_purpose": "the decision/question this dashboard drives",\n'
        '    "audience": "executive|manager|analyst|operational",\n'
        '    "widgets": [ {"title": "", "chart_type": "<chart type>", '
        '"business_question": "", "sql": "SELECT ... (empty for '
        'narrative_insight)", "label_column": "", "value_column": ""} ],\n'
        '    "kpis": ["kpi names this dashboard covers"],\n'
        '    "data_sources": ["allowed table names this dashboard uses"],\n'
        '    "confidence": 0.0,\n'
        '    "quality_score": 0\n'
        "  } ]\n"
        "}\n\n"
        "OUTPUT FORMAT: respond with this JSON object and nothing else — no "
        "prose, no markdown, no code fences. Begin with { and end with }."
    )

    raw = await llm_client.generate(
        prompt=prompt,
        system_prompt=_DASHBOARD_INSIGHT_SYSTEM_PROMPT,
        model=settings.sql_model,
        temperature=0.4,
        num_ctx=24576,
        response_format="json",
    )

    parsed = _parse_json_response(raw)
    raw_suggestions: list[dict] = []
    if isinstance(parsed, dict):
        if isinstance(parsed.get("suggestions"), list):
            raw_suggestions = [s for s in parsed["suggestions"] if isinstance(s, dict)]
        else:
            raw_suggestions = [parsed]
    elif isinstance(parsed, list):
        raw_suggestions = [s for s in parsed if isinstance(s, dict)]
    else:
        logger.warning("Failed to parse dashboard plans: %s", raw[:200])

    allowed_set = {t.lower() for t in allowed_tables}
    suggestions: list[DashboardPlanSuggestion] = []
    for s in raw_suggestions:
        widgets: list[DashboardPlanWidget] = []
        for w in s.get("widgets", []):
            if not isinstance(w, dict):
                continue
            sql = (w.get("sql") or "").strip()
            if sql:
                # Clean + validate against the allowed tables. Drop widgets whose
                # SQL references tables outside the project (hallucinated/reference
                # docs); narrative widgets (empty sql) are always kept.
                sql = _clean_sql(sql)
                try:
                    validate_sql(sql, allowed_tables)
                except SQLValidationError as e:
                    logger.warning(
                        "Dropping multi-suggest widget %r: %s",
                        w.get("title", "untitled"), e.reason,
                    )
                    continue
            widgets.append(
                DashboardPlanWidget(
                    title=str(w.get("title", "")),
                    chart_type=str(w.get("chart_type") or w.get("type") or ""),
                    business_question=str(w.get("business_question", "")),
                    sql=sql,
                    label_column=str(w.get("label_column", "")),
                    value_column=str(w.get("value_column", "")),
                )
            )
        # Keep only data sources that are real allowed tables (drop hallucinations
        # and any reference document the planner may have slipped in).
        data_sources = [
            str(d)
            for d in s.get("data_sources", [])
            if str(d).lower() in allowed_set
        ]
        suggestions.append(
            DashboardPlanSuggestion(
                title=str(s.get("title") or "AI Dashboard"),
                description=str(s.get("description", "")),
                business_purpose=str(s.get("business_purpose", "")),
                audience=str(s.get("audience") or req.audience or ""),
                widgets=widgets,
                kpis=[str(k) for k in s.get("kpis", []) if k],
                data_sources=data_sources,
                confidence=float(s.get("confidence") or 0.0),
                quality_score=int(s.get("quality_score") or 0),
            )
        )

    update_activity(req.user_id, req.tenant_id, req.project_id)

    return SuggestDashboardsMultiResponse(
        suggestions=suggestions,
        request_id=request_id,
        model_used=settings.sql_model,
    )


_INTEL_SYSTEM_PROMPT = (
    "You are Tablescope AI acting as a senior business analyst and management "
    "consultant. You are handed the real schema and documents for ONE project. "
    "Your job is to decide, on your own, what analyses a well-run company would "
    "run on this data to surface risks, trends, and opportunities that drive "
    "business decisions. Do not rely on any predefined metric list — reason from "
    "the actual tables, columns, and documents in front of you and apply best "
    "practices from how top-performing companies manage this kind of data.\n"
    "Use ONLY the provided context. Never invent tables, columns, or facts."
)


def _build_schema_lines(table_schema: list[dict]) -> str:
    """Exact per-table column list so the LLM never invents column names."""
    if not table_schema:
        return ""
    def _col_str(c: dict) -> str:
        name = c.get("name")
        desc = f'"{name}" ({c.get("type", "string")}'
        sample = c.get("sample")
        if sample not in (None, ""):
            # A real example value lets the LLM see the actual format (e.g.
            # "1/19/2026" vs "2026-01-19") and whether the text is numeric, so
            # it can CAST/parse correctly instead of guessing.
            desc += f', e.g. {sample!r}'
        return desc + ")"

    parts: list[str] = []
    for t in table_schema:
        tname = t.get("table") or t.get("view_name") or ""
        cols = t.get("columns") or []
        col_str = ", ".join(_col_str(c) for c in cols if c.get("name"))
        if tname and col_str:
            # Flag text-backed (CSV/file) tables so the LLM always casts.
            tag = (
                " [text-backed: CAST every column for math/date]"
                if t.get("storage") == "text"
                else ""
            )
            parts.append(f'  - "{tname}"{tag}: {col_str}')
    if not parts:
        return ""
    return (
        "\nExact schema — use ONLY these table and column names, spelled "
        "exactly as shown (they are case-sensitive). Do NOT invent or guess "
        "any column that is not listed here. Each column belongs to exactly "
        "ONE table; never reference a column under a table that does not "
        "list it. Where an example value is shown, use it to judge the column's "
        "real format: only CAST/aggregate columns whose example is numeric, and "
        "when grouping by a date stored as text, parse it with the matching mask "
        "via PARSETIMESTAMP (e.g. a value like '1/19/2026' -> "
        "EXTRACT(YEAR FROM PARSETIMESTAMP(\"col\", 'M/d/yyyy')); a value like "
        "'2026-01-19' -> EXTRACT(YEAR FROM CAST(\"col\" AS date))). Never CAST a "
        "text date straight to date unless its example is already ISO "
        "yyyy-MM-dd:\n" + "\n".join(parts)
    )


def _build_relationship_hint_lines(hints: list[dict]) -> str:
    """Render verified join candidates the platform discovered.

    Only relationships supplied here (from scope metadata or exact matching
    keys) may be joined; everything else stays single-table. Returns "" when
    there is no relationship evidence, which leaves single-table behaviour
    completely unchanged.
    """
    def _conf(h: dict) -> float:
        c = h.get("join_confidence")
        return float(c) if isinstance(c, int | float) else 0.0

    rows: list[str] = []
    # Strongest evidence first: the prompt tells the planner to prefer the
    # highest-confidence pairs, and if a response is ever truncated the
    # weakest pairs are the ones nearest the cut.
    for h in sorted(hints, key=_conf, reverse=True):
        left = h.get("left_table") or ""
        right = h.get("right_table") or ""
        lkey = h.get("left_join_key") or ""
        rkey = h.get("right_join_key") or ""
        if not (left and right and lkey and rkey):
            continue
        rel = h.get("relationship_type") or "unknown"
        reason = str(h.get("confidence_reason") or "")[:60]
        risk = h.get("row_multiplication_risk") or "unknown"
        conf_str = f"{_conf(h):.2f}" if h.get("join_confidence") is not None else "n/a"
        rows.append(
            f'  - "{left}"."{lkey}" = "{right}"."{rkey}" '
            f"(rel={rel}, conf={conf_str}, risk={risk}"
            f"{f'; {reason}' if reason else ''})"
        )
    if not rows:
        return ""
    return (
        "\nRELATIONSHIP EVIDENCE — verified joins you MAY use (exception to the "
        "single-table rule below):\n" + "\n".join(rows) + "\n"
        "Multi-table join rules:\n"
        "- You may JOIN a pair of tables ONLY when the exact pair and keys "
        "appear in the list above. Never invent a join or join on matching "
        "names that are not listed here.\n"
        "- Default to at most TWO tables per analysis. Aggregate the detail/fact "
        "table to one row per key in a derived step expressed as a single "
        "GROUP BY before relating it to the master/entity table, so a "
        "one-to-many join cannot multiply rows.\n"
        "- Prefer a join only when it produces a genuinely cross-table insight "
        "(e.g. high-spend suppliers with elevated defect rates, single-source "
        "dependency, concentration risk). Otherwise stay single-table.\n"
        "- Skip any join whose row_multiplication_risk is high unless you "
        "aggregate first.\n"
    )


_TEIID_SQL_RULES = (
    "This database uses Teiid (not MySQL/PostgreSQL). Text-backed (CSV/file) "
    "columns are stored as STRINGS no matter what logical type is shown.\n"
    "- Query a SINGLE table per analysis. Do NOT write JOINs. (Many tables "
    'share column names like "SupplierID" — joining causes ambiguity errors. '
    "One table per query avoids this entirely.)\n"
    "- Reference ONLY columns listed under the table you select FROM; never "
    "invent columns and never borrow a column from another table.\n"
    '- Quote every table and column name with double quotes: "ColName".\n'
    "- Only CAST columns that hold NUMERIC values (quantities, amounts, counts, "
    "prices). Do NOT CAST categorical/label text (status, type, rating, name, "
    "category, country, severity) — filter or GROUP BY those as-is.\n"
    "- For ANY arithmetic (+ - * /), comparison (>, <), SUM/AVG/MIN/MAX, or "
    "numeric sort on a numeric text-backed column, you MUST CAST it: "
    'CAST("col" AS double). Example: SUM(CAST("DefectQty" AS double)) / '
    'NULLIF(SUM(CAST("ReceivedQty" AS double)), 0).\n'
    "- For date operations on a text-backed column, parse/cast it first: a slash "
    "date like '1/19/2026' uses PARSETIMESTAMP(\"OrderDate\", 'M/d/yyyy'); an "
    'ISO date like \'2026-01-19\' uses CAST("OrderDate" AS timestamp).\n'
    "- To count days/months between two dates, NEVER subtract them "
    "(date1 - date2 raises TEIID30070) and NEVER wrap a subtraction in "
    "EXTRACT(DAY FROM ...). Use TIMESTAMPDIFF(SQL_TSI_DAY, <earlier>, <later>), "
    "parsing text dates first, and CAST the result to double when aggregating "
    "so it decodes: "
    "AVG(CAST(TIMESTAMPDIFF(SQL_TSI_DAY, "
    "PARSETIMESTAMP(\"ShipDate\", 'M/d/yyyy'), "
    "PARSETIMESTAMP(\"DeliveryDate\", 'M/d/yyyy')) AS double)). "
    "Also never use DATEDIFF.\n"
    "- Do NOT use DATE_FORMAT/MONTH()/YEAR(). For a time trend, GROUP BY a "
    "SORTABLE STRING period label built with FORMATTIMESTAMP, e.g. "
    "FORMATTIMESTAMP(PARSETIMESTAMP(\"OrderDate\", 'M/d/yyyy'), 'yyyy-MM'). "
    "Default to month ('yyyy-MM') so a single year still trends; use 'yyyy' only "
    "across 3+ years. NEVER group a trend by a bare numeric year alone — it "
    "collapses to one point and renders as a meaningless '2.0K' tile.\n"
    "- Alias columns with a plain identifier or double quotes (e.g. AS Month or "
    'AS "Month") — NEVER single quotes (AS \'Month\' is a syntax error).\n'
    "- Do NOT use CTEs (WITH), subqueries in FROM, or derived tables. Query the "
    "allowed tables directly with WHERE/GROUP BY/aggregations only.\n"
    "- GROUP BY must repeat the full SELECT expression (Teiid forbids alias "
    "references in GROUP BY). Never use SELECT *.\n"
)

# Chart families the planner may request. These map onto the dashboard's chart
# catalog downstream (platform-api ``_build_chart``); the result shape can still
# override the pick (e.g. a single-row aggregate always renders as KPI tiles).
_ALLOWED_PLAN_CHART_TYPES = frozenset(
    {
        "kpi_grid",
        "line",
        "area",
        "dual_line",
        "scatter",
        "bubble",
        "bar",
        "horizontal_bar",
        "stacked_bar",
        "waterfall",
        "donut",
        "pie",
        "treemap",
        "funnel",
        "radar",
        "heatmap",
        "gauge",
        "bullet",
        "sparkline_table",
        "none",
    }
)


@router.post("/intelligence/plan", response_model=IntelligencePlanResponse)
async def intelligence_plan(req: IntelligencePlanRequest) -> IntelligencePlanResponse:
    """Propose high-value diagnostic analyses for a project (SQL written in memory).

    The LLM reasons over the project's real schema + documents and returns a set
    of analyses, each with a category (risk/trend/opportunity), a business
    rationale, and either a read-only SQL query or a document-based finding.
    """
    request_id = str(uuid.uuid4())
    verify_signature(req.model_dump(exclude={"signature"}), req.signature)

    try:
        ctx = await context_builder.build_context(
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            project_id=req.project_id,
            scope="project",
            question="",
            feature="intelligence_plan",
        )
    except ContextBuildError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: {e.reason}",
        )

    context_text = context_builder.context_to_prompt_text(ctx)

    allowed_tables = req.allowed_tables
    if not allowed_tables:
        allowed_tables = [
            ds.get("view_name", ds.get("name", ""))
            for ds in ctx.allowed_context.get("metadata", [])
            if ds.get("view_name") or ds.get("name")
        ]

    doc_lines = ""
    if req.documents:
        project_docs = [
            d for d in req.documents if d.get("source") != "reference_library"
        ]
        reference_docs = [
            d for d in req.documents if d.get("source") == "reference_library"
        ]
        sections: list[str] = []
        if project_docs:
            sections.append(
                "\nProject documents (title — summary — tags):\n"
                + "\n".join(
                    f"  - {d.get('title', 'document')}: "
                    f"{(d.get('summary') or '')[:300]}"
                    + (
                        f"  [tags: {', '.join(d.get('tags', []))}]"
                        if d.get("tags")
                        else ""
                    )
                    for d in project_docs[:20]
                )
            )
        if reference_docs:
            sections.append(
                "\nReference Library — authoritative standards, regulations, "
                "and governance policies that apply to this project. Treat "
                "these as the source of truth for compliance requirements, "
                "thresholds, and best practices. When the project's data can "
                "be assessed against one of these, propose a finding that "
                "grounds the risk/opportunity in the standard and ALWAYS put "
                "the document's exact title in source_documents:\n"
                + "\n".join(
                    f"  - {d.get('title', 'document')}"
                    + (
                        " ["
                        + ", ".join(
                            p
                            for p in (
                                d.get("issuing_body") or "",
                                d.get("tier") or "",
                            )
                            if p
                        )
                        + "]"
                        if (d.get("issuing_body") or d.get("tier"))
                        else ""
                    )
                    + f": {(d.get('summary') or '')[:300]}"
                    for d in reference_docs[:25]
                )
            )
        doc_lines = "".join(sections)

    schema_lines = _build_schema_lines(req.table_schema)
    relationship_lines = _build_relationship_hint_lines(req.relationship_hints)
    teiid_rules = _TEIID_SQL_RULES

    # Granularity (1 executive .. 5 granular) steers count + depth + how
    # aggressively to surface smaller, lower-severity signals.
    granularity = max(1, min(5, req.granularity))
    target_count = max(1, min(req.max_analyses, {1: 3, 2: 5, 3: 8, 4: 11, 5: 15}[granularity]))
    if granularity <= 2:
        depth_guidance = (
            "Operate at an EXECUTIVE level. Surface ONLY the few most material, "
            "highest-leverage findings — the ones a CEO would act on. Aggregate "
            "broadly; ignore minor or niche signals. Prefer high-severity items."
        )
    elif granularity >= 4:
        depth_guidance = (
            "Operate at a GRANULAR, analyst level. Drill into specific segments, "
            "categories, suppliers, time periods, or line items. Surface detailed "
            "and smaller signals too, including lower-severity 'watch' items and "
            "early-stage opportunities — even when the dataset is small. Slice the "
            "data multiple ways to find detail-level risks and opportunities."
        )
    else:
        depth_guidance = (
            "Operate at a BALANCED level — a mix of strategic headline findings "
            "and a few more specific, detailed insights."
        )

    prompt = (
        f"{context_text}\n{doc_lines}\n{schema_lines}\n{relationship_lines}\n"
        f"Allowed tables (use ONLY these, exact names): {', '.join(allowed_tables)}\n\n"
        f"{teiid_rules}\n"
        f"{depth_guidance}\n\n"
        f"Propose up to {target_count} of the most valuable analyses for this "
        "project at this level of detail. Cover a mix of risks, trends, "
        "opportunities, and relationships where the data supports it. Each "
        "analysis must be answerable from the allowed tables OR grounded in a "
        "listed document.\n"
        "IN ADDITION to those, propose one CROSS-TABLE analysis for EACH table "
        "pair listed in RELATIONSHIP EVIDENCE whose data supports a genuine "
        "insight. Cross-table analyses are extra — they do NOT count toward "
        f"the {target_count} limit, and you must not drop a supportable "
        "evidence pair to stay under it.\n\n"
        "RELATIONSHIP ANALYSES (category \"relationship\"):\n"
        "In addition to single-metric risks/trends/opportunities, actively look "
        "for pairs of columns within ONE allowed table whose relationship to each "
        "other changes over time — not just two values that both move, but a "
        "connection that strengthens, weakens, decouples, inverts, or diverges. "
        "Examples of what counts: a cost metric and a quality metric that used to "
        "track together but no longer do; one category's share of a total "
        "shrinking while another grows; a rate (e.g. defects per unit) drifting "
        "away from its historical band. The two variables may be columns on "
        "the SAME table, or on TWO tables joined per the CROSS-TABLE rules "
        "below.\n"
        "CROSS-TABLE ANALYSES (category \"relationship\"):\n"
        "For each pair in the RELATIONSHIP EVIDENCE list above, propose one "
        "analysis that JOINs exactly that pair on exactly the listed keys. "
        "Aggregate the detail/fact table to one row per join key in a derived "
        "GROUP BY step BEFORE joining, so a one-to-many join cannot multiply "
        "rows. Prefer the highest-confidence pairs first and skip a pair only "
        "when its data genuinely supports no insight (e.g. the joined result "
        "would be a single row or empty). Never join a pair that is not "
        "listed, and never join on matching column names that are not listed "
        "there.\n"
        "For each relationship analysis, decide which shape best reveals the "
        "change and choose accordingly:\n"
        "- If both variables are naturally plotted on a shared timeline → use "
        "'dual_line' (two series, one time axis).\n"
        "- If the relationship is better expressed as a single derived value per "
        "period (a gap, ratio, or delta between the two variables) → use 'line' "
        "and compute that derived value in the SQL itself (e.g. SELECT period, "
        "(metric_a - metric_b) AS variance).\n"
        "- If the relationship is best seen as a small number of snapshots in time "
        "rather than a continuous trend → use 'scatter' or 'bubble', with one "
        "point per period and the two variables as x/y (and a third metric as "
        "bubble size, if relevant).\n"
        "Only propose a relationship analysis when at least 3 time periods of data "
        "are available for both variables — a 2-point comparison cannot show a "
        "changing relationship.\n"
        "MANDATORY SQL SHAPE for every dual_line / scatter / time-based "
        "relationship — get this exactly right or the chart cannot be drawn:\n"
        "0. Pick ONE table from the schema that itself lists BOTH metric columns "
        "you want (and a date column when plotting over time). Every column you "
        "reference — both metrics, the date, anything in WHERE/GROUP BY — MUST "
        "appear under that exact table in the schema above. NEVER borrow a "
        "column from another table (e.g. do not use a Suppliers column while "
        "selecting FROM the Inspections table); a column that is not listed "
        "under your FROM table does not exist for this query.\n"
        "0b. EXCEPTION — cross-table analyses: when the analysis joins a table "
        "pair from the RELATIONSHIP EVIDENCE list (and only then), columns may "
        "come from BOTH joined tables. Every referenced column must still "
        "appear under one of the two joined tables in the schema, the join "
        "must use exactly the listed keys, and the detail table must be "
        "aggregated to one row per key before the join. "
        "The Inspections-style table that holds two numeric quantities "
        "(e.g. a received quantity and a defect quantity) is usually the best "
        "single source for a real two-metric relationship.\n"
        "1. The period/time column MUST appear in the SELECT list as the FIRST "
        "column, not only in GROUP BY. A query like 'SELECT metric_a, metric_b "
        "... GROUP BY period' is WRONG because the result then has no time axis. "
        "Write 'SELECT period_expr AS Period, agg_a AS metric_a, agg_b AS "
        "metric_b ... GROUP BY period_expr ORDER BY period_expr'.\n"
        "2. Build the period as a SORTABLE STRING label, NOT a bare numeric year "
        "(a number like 2026 renders as a meaningless '2.0K' tile). Default to "
        "MONTH granularity 'yyyy-MM' so a single year still shows a real trend; "
        "use 'yyyy' only when the data clearly spans 3+ distinct years. Derive it "
        "from the date column using the parse that matches its EXAMPLE value (see "
        "schema): a slash date like '1/19/2026' MUST use "
        "FORMATTIMESTAMP(PARSETIMESTAMP(\"DateCol\", 'M/d/yyyy'), 'yyyy-MM') — "
        "never CAST a slash date straight to date, it fails. An ISO value like "
        "'2026-01-19' uses FORMATTIMESTAMP(CAST(\"DateCol\" AS timestamp), "
        "'yyyy-MM'). Repeat the full expression in GROUP BY (no alias references) "
        "and ORDER BY it so periods are chronological.\n"
        "2b. A trend needs >= 3 distinct periods. If monthly grouping still "
        "yields < 3 periods the data is too thin for a trend — use a KPI or a "
        "category comparison instead of a line.\n"
        "2c. YEAR-OVER-YEAR: when the data spans 2+ years, compare the latest "
        "year against the prior year — put the within-year period (month 'MM' or "
        "'yyyy-MM') on the axis and either split the series by year or add the "
        "prior-year metric as value_column_2, so 'this year vs last year' is "
        "visible. With only ONE year of data, do NOT fabricate a prior-year "
        "comparison; trend by month instead.\n"
        "3. Set label_column to the period alias (e.g. \"Period\"), value_column "
        "to the first metric alias, and value_column_2 to the second metric "
        "alias. All three MUST be aliases that actually appear in your SELECT.\n"
        "4. CAST any text-backed column used in a comparison or CASE, not just in "
        "arithmetic — e.g. CASE WHEN CAST(\"DefectQty\" AS double) > 0 THEN 1 "
        "ELSE 0 END. An uncast text column in '> 0' will be rejected.\n"
        "5. Never use DATEDIFF (it is not a Teiid function). For a day count "
        "between two dates use TIMESTAMPDIFF(SQL_TSI_DAY, CAST(\"d1\" AS "
        "timestamp), CAST(\"d2\" AS timestamp)).\n"
        "Example (two metrics over time, date column whose example is a slash "
        "date like '1/19/2026'):\n"
        "SELECT FORMATTIMESTAMP(PARSETIMESTAMP(\"date_col\", 'M/d/yyyy'), "
        "'yyyy-MM') AS Period, AVG(CAST(\"metric_a\" AS double)) AS MetricA, "
        "AVG(CAST(\"metric_b\" AS double)) AS MetricB "
        "FROM \"some_table\" "
        "GROUP BY FORMATTIMESTAMP(PARSETIMESTAMP(\"date_col\", 'M/d/yyyy'), "
        "'yyyy-MM') ORDER BY Period — with label_column=Period, "
        "value_column=MetricA, value_column_2=MetricB, chart_type=dual_line.\n\n"
        "DOCUMENT-GROUNDED RELATIONSHIPS:\n"
        "Relationships are NOT limited to two table columns — also look for how "
        "the project's DATA relates to its DOCUMENTS, and how documents relate to "
        "each other:\n"
        "- DATA vs DOCUMENT TARGET: when a listed document states a concrete "
        "threshold, target, limit, or SLA that applies to a table metric (e.g. a "
        "policy requiring on-time delivery >= 98%, a defect rate < 2%, or a "
        "single-supplier spend cap of 30%), propose an analysis that trends the "
        "ACTUAL metric over time AND carries the document's stated value as a "
        "constant second series, so the reader sees the data tracking against the "
        "policy line. Compute the constant directly in SQL as its own column, "
        "e.g. SELECT period_expr AS Period, AVG(CAST(\"OnTimeFlag=1\" ...)) AS "
        "ActualOnTime, 98.0 AS PolicyTarget ... GROUP BY period_expr. Set "
        "chart_type=dual_line (or line), value_column=ActualOnTime, "
        "value_column_2=PolicyTarget, and ALWAYS list the source document title "
        "in source_documents. Phrase the title/rationale around whether the data "
        "meets, is converging toward, or is diverging from the documented "
        "requirement.\n"
        "- DOCUMENT-ONLY relationships: when two documents (or two requirements "
        "within one document) interact, conflict, or reinforce each other and no "
        "single table proves it, propose a narrative finding: leave sql empty, "
        "set chart_type=none, category=relationship, and list every relevant "
        "document in source_documents.\n"
        "Only assert a data-vs-document relationship when the metric the document "
        "describes can actually be computed from an allowed table; otherwise make "
        "it a document-only narrative finding.\n\n"
        "For data analyses, write a single read-only SQL query that returns a small "
        "result suitable for a chart or KPI (aggregate/group — not raw dumps), "
        "querying a single allowed table (or a verified two-table join from the "
        "RELATIONSHIP EVIDENCE list) with no other joins or subqueries. Pick the "
        "chart type that BEST represents each result — do NOT default everything "
        "to bar. This is an executive report, so vary the visuals across the full "
        "range below:\n"
        "- 'kpi_grid': one or a few headline numbers (a single-row aggregate).\n"
        "- 'line' (or 'area'): a trend over time / ordered periods.\n"
        "- 'dual_line': two related metrics plotted over the same time axis to show "
        "how their relationship shifts.\n"
        "- 'scatter': two variables compared across periods or entities, to show a "
        "changing or underlying relationship.\n"
        "- 'bubble': scatter with a third dimension encoded as point size (e.g. "
        "magnitude or volume).\n"
        "- 'bar' (or 'horizontal_bar'): compare a metric across categories / top-N.\n"
        "- 'stacked_bar': a metric across categories, broken into sub-components.\n"
        "- 'waterfall': a running total with sequential positive/negative "
        "contributions (e.g. bridge from budget to actual).\n"
        "- 'donut' (or 'pie'): parts-of-a-whole / share/mix of a total.\n"
        "- 'treemap': many categories' relative sizes.\n"
        "- 'funnel': stage-by-stage drop-off.\n"
        "- 'radar': multi-metric comparison of a few items.\n"
        "- 'heatmap': a metric across two categorical dimensions (e.g. category x "
        "time period), where magnitude is shown by color intensity.\n"
        "- 'gauge': a single metric against a target or threshold range.\n"
        "- 'bullet': a single metric vs. target with qualitative ranges "
        "(good/watch/poor).\n"
        "- 'sparkline_table': a small table of entities/rows, each with an inline "
        "trend sparkline and a current value — good for comparing many items' "
        "trajectories at once.\n"
        "- 'none': a narrative finding best told as prose with bolded figures "
        "(no chart). Use this for at least one insight when it reads better as text.\n"
        "For document-based findings, leave sql empty, set chart_type to 'none', and "
        "list the relevant document titles in source_documents.\n\n"
        "Before finalizing each analysis, sanity-check that it will actually return "
        "data:\n"
        "- Don't filter, group, or join on a specific value (a status, category, "
        "ID, or date range) unless the schema or sample context gives you a "
        "concrete reason to believe that value exists in the data. Prefer "
        "aggregations that span the full table (no risky WHERE clause) over a "
        "narrow filter you're guessing at.\n"
        "- Don't propose a time-based trend, dual_line, scatter, or relationship "
        "analysis unless the table clearly has enough distinct time periods to "
        "support it (see the minimum-periods rule above). If you're not confident "
        "the date range has enough spread, propose a non-time-based analysis on "
        "that table instead.\n"
        "- If, after this check, you're not confident a proposed analysis will "
        "return at least one meaningful row, drop it and propose a different "
        "analysis in its place — do not include an analysis you expect to come "
        "back empty, and do not fill a gap with placeholder, sample, or invented "
        "figures.\n"
        f"- Aim to deliver the full {target_count} analyses PLUS the "
        "cross-table analyses this way; if the data "
        "genuinely can't support that many non-empty analyses, return fewer rather "
        "than padding with weak or empty ones.\n\n"
        "Return ONLY a JSON object: {\"analyses\": [ {\n"
        "  \"id\": \"a1\",\n"
        "  \"category\": \"risk|trend|opportunity|relationship\",\n"
        "  \"title\": \"short headline\",\n"
        "  \"rationale\": \"why this matters for the business (1 sentence)\",\n"
        "  \"sql\": \"SELECT ... (empty for document findings)\",\n"
        "  \"chart_type\": \"kpi_grid|line|area|dual_line|scatter|bubble|bar|horizontal_bar|stacked_bar|waterfall|donut|pie|treemap|funnel|radar|heatmap|gauge|bullet|sparkline_table|none\",\n"
        "  \"label_column\": \"alias used for the category/x axis\",\n"
        "  \"value_column\": \"alias used for the numeric value (primary metric, or size for bubble)\",\n"
        "  \"value_column_2\": \"alias for a second metric — used by dual_line, scatter, bubble, heatmap (color value), gauge/bullet (target). Omit/empty otherwise.\",\n"
        "  \"severity_hint\": \"critical|urgent|watch|opportunity|info\",\n"
        "  \"source_documents\": [\"doc title\"]\n"
        "} ] }\n\n"
        "OUTPUT FORMAT: respond with this JSON object and nothing else — no "
        "prose, no markdown, no headings, no numbered list, no code fences. "
        "Begin your response with { and end it with }."
    )

    raw = await llm_client.generate(
        prompt=prompt,
        system_prompt=_INTEL_SYSTEM_PROMPT,
        model=settings.reasoning_model,
        temperature=0.2,
        # The window is shared by the prompt AND the generated JSON. The plan
        # prompt (schema + documents + relationship evidence + rules) plus
        # target_count + one-per-evidence-pair analyses is the largest
        # prompt+output pair in the pipeline — run it at the same 24576 the
        # scope-analysis calls already use on this model, so a rich project's
        # response is not truncated into invalid JSON.
        num_ctx=24576,
        response_format="json",
    )

    parsed = _parse_json_response(raw)
    if parsed is None and raw:
        logger.warning(
            "intelligence plan JSON unparseable (len=%s, tail=%r) — "
            "attempting truncation salvage",
            len(raw), raw[-80:],
        )
    analyses: list[PlannedAnalysis] = []
    # Cross-table analyses are additive: allow one extra slot per evidence
    # pair so the slice never drops a join the prompt mandated.
    plan_budget = target_count + len(req.relationship_hints or [])
    if parsed and isinstance(parsed.get("analyses"), list):
        for i, a in enumerate(parsed["analyses"][:plan_budget]):
            if not isinstance(a, dict):
                continue
            sql = _clean_sql(a.get("sql", "") or "")
            if sql:
                try:
                    validate_sql(sql, allowed_tables)
                except SQLValidationError as e:
                    logger.warning("Dropping analysis %s: %s", a.get("title"), e.reason)
                    continue
            category = str(a.get("category", "trend")).lower()
            if category not in ("risk", "trend", "opportunity", "relationship"):
                category = "trend"
            chart_type = str(a.get("chart_type", "bar")).lower()
            if chart_type not in _ALLOWED_PLAN_CHART_TYPES:
                chart_type = "bar"
            # An analysis must have either runnable SQL or document grounding.
            if not sql and not a.get("source_documents"):
                continue
            analyses.append(
                PlannedAnalysis(
                    id=str(a.get("id") or f"a{i + 1}"),
                    category=category,
                    title=str(a.get("title", "")),
                    rationale=str(a.get("rationale", "")),
                    sql=sql,
                    chart_type=chart_type,
                    label_column=str(a.get("label_column", "")),
                    value_column=str(a.get("value_column", "")),
                    value_column_2=str(a.get("value_column_2", "")),
                    severity_hint=str(a.get("severity_hint", "watch")),
                    source_documents=[
                        str(d) for d in a.get("source_documents", []) if d
                    ],
                )
            )
    else:
        logger.warning("Failed to parse intelligence plan: %s", raw[:200])

    update_activity(req.user_id, req.tenant_id, req.project_id)
    return IntelligencePlanResponse(
        analyses=analyses,
        request_id=request_id,
        model_used=settings.reasoning_model,
    )


@router.post("/intelligence/fix-sql", response_model=IntelligenceFixSQLResponse)
async def intelligence_fix_sql(
    req: IntelligenceFixSQLRequest,
) -> IntelligenceFixSQLResponse:
    """Repair a single query the engine rejected, using the exact error + schema.

    This closes the analyst loop: when generated SQL fails (CAST on the wrong
    type, alias-in-GROUP BY, an unsupported function, a wrong-table column, …),
    the model is shown the precise engine error and asked to return a corrected
    single-table query. Returns empty SQL if it can't be fixed.
    """
    request_id = str(uuid.uuid4())
    verify_signature(req.model_dump(exclude={"signature"}), req.signature)

    schema_lines = _build_schema_lines(req.table_schema)
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
        f"{_TEIID_SQL_RULES}\n"
        f"Failing SQL:\n{req.sql}\n\n"
        f"Engine error:\n{req.error[:800]}\n\n"
        "Return ONLY the corrected SQL query (no markdown, no commentary), or an "
        "empty response if it cannot be fixed."
    )

    raw = await llm_client.generate(
        prompt=prompt,
        system_prompt=_INTEL_SYSTEM_PROMPT,
        model=settings.reasoning_model,
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
        model_used=settings.reasoning_model,
    )


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


_KG_SYSTEM_PROMPT = (
    "You are Tablescope AI acting as a senior business analyst reasoning over a "
    "knowledge graph for ONE project. You are handed a SELECTED node and the "
    "nodes/edges connected to it (documents, policies, processes, KPIs, data "
    "sources, queries, dashboards, entities). Your job is to produce business "
    "insight cards — the same caliber as the AI Home page — but specific to this "
    "node and the data sources related to it in the graph. Ground every card "
    "ONLY in the supplied nodes and relationships; never invent a node, "
    "document, KPI, metric, threshold, or relationship that is not listed. "
    "Every card must cite the graph_keys of the nodes that support it."
)

_KG_CATEGORIES = {
    "business_insight", "opportunity", "risk", "warning", "gap", "recommendation",
}
_KG_SEVERITIES = {"critical", "urgent", "warning", "watch", "opportunity", "info"}


def _build_kg_neighbor_lines(neighbors: list[dict]) -> str:
    if not neighbors:
        return "Connected nodes: (none)\n"
    by_group: dict[str, list[dict]] = {}
    for n in neighbors:
        by_group.setdefault(str(n.get("display_group") or "Related"), []).append(n)
    lines = ["Connected nodes (grouped), each with its relationship to the selected node:"]
    for group, items in by_group.items():
        lines.append(f"\n  {group}:")
        for n in items[:14]:
            rel = str(n.get("relationship") or "related_to")
            direction = str(n.get("direction") or "")
            arrow = (
                "selected→node" if direction == "out"
                else "node→selected" if direction == "in"
                else "linked"
            )
            conf = n.get("confidence")
            conf_str = f", confidence {conf:.2f}" if isinstance(conf, int | float) and conf else ""
            label = str(n.get("label") or "")
            key = str(n.get("graph_key") or "")
            summary = str(n.get("summary") or "")[:140]
            lines.append(
                f"    - [{key}] {label} ({n.get('type', 'node')}) — "
                f"{rel} [{arrow}]{conf_str}"
                + (f" — {summary}" if summary else "")
            )
    return "\n".join(lines) + "\n"


@router.post("/intelligence/knowledge-graph", response_model=KnowledgeGraphInsightResponse)
async def knowledge_graph_insights(
    req: KnowledgeGraphInsightRequest,
) -> KnowledgeGraphInsightResponse:
    """Generate AI-Home-style business-insight cards for a selected graph node.

    Mirrors the AI Home architecture (deterministic evidence in, AI insight out)
    but scoped to a single node's graph neighborhood: the platform passes the
    deterministic node-centric graph and the model reasons over it, grounded in
    the Knowledge Graph Insight Best Practices, to surface insights specific to
    the data sources related to that node.
    """
    request_id = str(uuid.uuid4())
    verify_signature(req.model_dump(exclude={"signature"}), req.signature)

    try:
        ctx = await context_builder.build_context(
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            project_id=req.project_id,
            scope="project",
            question="",
            feature="knowledge_graph",
        )
        context_text = context_builder.context_to_prompt_text(ctx)
    except ContextBuildError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: {e.reason}",
        )

    best_practices = load_prompt_reference("knowledge_graph_insight_best_practices.md")
    best_practices_block = (
        f"Knowledge Graph Insight Best Practices (authoritative policy):\n"
        f"{best_practices}\n\n"
        if best_practices
        else ""
    )

    center = req.center or {}
    allowed_keys = {
        str(n.get("graph_key"))
        for n in req.neighbors
        if n.get("graph_key")
    }
    center_key = str(center.get("graph_key") or "")
    if center_key:
        allowed_keys.add(center_key)

    neighbor_lines = _build_kg_neighbor_lines(req.neighbors)
    doc_lines = ""
    if req.documents:
        doc_lines = "\nGoverning / supporting documents:\n" + "\n".join(
            f"  - {d.get('title', 'document')}: {(d.get('summary') or '')[:240]}"
            for d in req.documents[:20]
        )
    kpi_lines = (
        "\nKPIs in this neighborhood: " + ", ".join(req.kpis[:30])
        if req.kpis
        else ""
    )

    max_cards = max(1, min(req.max_cards, 8))
    prompt = (
        f"{best_practices_block}"
        f"{context_text}\n\n"
        f"SELECTED NODE: [{center_key}] {center.get('label', '')} "
        f"({center.get('type', 'node')}) — {(center.get('summary') or '')[:240]}\n"
        f"Graph lens: {req.lens}\n\n"
        f"{neighbor_lines}"
        f"{doc_lines}"
        f"{kpi_lines}\n\n"
        f"Produce up to {max_cards} knowledge-graph business-insight cards for the "
        "SELECTED node, specific to the data sources, KPIs, queries, dashboards, "
        "documents, and processes related to it above. Cover a mix of card "
        "categories where the evidence supports it: business_insight, "
        "opportunity, risk, warning, gap, recommendation. Rules:\n"
        "- Ground every card ONLY in the connected nodes listed above. Do NOT "
        "invent nodes, documents, KPIs, metrics, thresholds, or relationships.\n"
        "- A 'gap' card is only valid when an authoritative source in the "
        "neighborhood (a policy, procedure, standard, or governing document) "
        "implies something should exist that is missing — name that source.\n"
        "- evidenceKeys MUST be graph_keys copied exactly from the connected "
        "nodes (or the selected node). Drop any card you cannot ground in at "
        "least one real graph_key.\n"
        "- Keep the recommendation and the insight in the flow: when a card "
        "implies an action, fill recommendedAction.\n"
        "- confidence is 0..1, reflecting how strongly the evidence supports the "
        "card.\n\n"
        "Return ONLY a JSON object: {\"cards\": [ {\n"
        "  \"id\": \"c1\",\n"
        "  \"category\": \"business_insight|opportunity|risk|warning|gap|recommendation\",\n"
        "  \"severity\": \"critical|urgent|warning|watch|opportunity|info\",\n"
        "  \"title\": \"short headline\",\n"
        "  \"summary\": \"2-3 sentences, business language, cite the related sources\",\n"
        "  \"businessQuestion\": \"the question this answers\",\n"
        "  \"businessImpact\": \"why it matters to the business\",\n"
        "  \"confidence\": 0.0,\n"
        "  \"recommendedAction\": \"the next action (empty if none)\",\n"
        "  \"evidenceKeys\": [\"graph_key\", ...],\n"
        "  \"sourceDocuments\": [\"document title\", ...],\n"
        "  \"supportedKpis\": [\"kpi name\", ...]\n"
        "} ] }\n\n"
        "OUTPUT FORMAT: respond with this JSON object and nothing else — no "
        "prose, no markdown, no code fences. Begin with { and end with }."
    )

    raw = await llm_client.generate(
        prompt=prompt,
        system_prompt=_KG_SYSTEM_PROMPT,
        model=settings.reasoning_model,
        temperature=0.2,
        num_ctx=16384,
        response_format="json",
    )

    parsed = _parse_json_response(raw)
    cards: list[KnowledgeGraphCard] = []
    if parsed and isinstance(parsed.get("cards"), list):
        for i, c in enumerate(parsed["cards"][:max_cards]):
            if not isinstance(c, dict):
                continue
            category = str(c.get("category", "business_insight")).lower()
            if category not in _KG_CATEGORIES:
                category = "business_insight"
            severity = str(c.get("severity", "info")).lower()
            if severity not in _KG_SEVERITIES:
                severity = "info"
            # Keep only evidence keys that actually exist in the neighborhood —
            # this is the evidence gate that rejects fabricated grounding.
            evidence_keys = [
                str(k) for k in c.get("evidenceKeys", [])
                if str(k) in allowed_keys
            ]
            if not evidence_keys:
                logger.info("Dropping KG card with no real evidence: %s", c.get("title"))
                continue
            try:
                confidence = float(c.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0
            title = str(c.get("title", "")).strip()
            if not title:
                continue
            cards.append(
                KnowledgeGraphCard(
                    id=str(c.get("id") or f"c{i + 1}"),
                    category=category,
                    severity=severity,
                    title=title,
                    summary=str(c.get("summary", "")),
                    businessQuestion=str(c.get("businessQuestion", "")),
                    businessImpact=str(c.get("businessImpact", "")),
                    confidence=max(0.0, min(1.0, confidence)),
                    recommendedAction=str(c.get("recommendedAction", "")),
                    evidenceKeys=evidence_keys,
                    sourceDocuments=[
                        str(d) for d in c.get("sourceDocuments", []) if d
                    ],
                    supportedKpis=[str(k) for k in c.get("supportedKpis", []) if k],
                )
            )
    else:
        logger.warning("Failed to parse KG insight cards: %s", raw[:200])

    update_activity(req.user_id, req.tenant_id, req.project_id)
    return KnowledgeGraphInsightResponse(
        cards=cards,
        request_id=request_id,
        model_used=settings.reasoning_model,
    )


_PROJECT_INSIGHT_SYSTEM_PROMPT = (
    "You are the Tablescope Project Insight analyst. You analyze ONE selected "
    "project and produce concise, evidence-based, business-oriented insight "
    "scoped only to that project. Never summarize the tenant or other projects. "
    "Ground every finding in the supplied project context (metadata, tables, "
    "documents, saved queries, dashboards, KPIs, Knowledge Graph). Do not invent "
    "data, metrics, thresholds, or relationships. Recommended dashboards, "
    "queries, and KPIs are suggestions and do not need to already exist. Never "
    "fabricate KPI values — mark unmeasurable KPIs as missing_data or "
    "recommended. Return ONLY the requested JSON object."
)


def _lines(items: list[str], limit: int) -> str:
    picked = [str(i).strip() for i in items if str(i).strip()][:limit]
    return "\n".join(f"  - {i}" for i in picked) if picked else "  (none)"


def _str_list(value: Any, limit: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _dict_list(value: Any, limit: int) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [d for d in value if isinstance(d, dict)][:limit]


@router.post("/intelligence/project-insight", response_model=ProjectInsightResponse)
async def project_insight(req: ProjectInsightRequest) -> ProjectInsightResponse:
    """Generate the project-scoped executive Project Insight report.

    Distinct from Business Insight (tenant-wide): this uses the Project Insight
    Best Practices prompt and reasons over ONLY the selected project's
    authorized context. Recommended dashboards/queries/KPIs are AI suggestions.
    """
    request_id = str(uuid.uuid4())
    verify_signature(req.model_dump(exclude={"signature"}), req.signature)

    best_practices = load_prompt_reference("project_insight_best_practices.md")
    best_practices_block = (
        f"Project Insight Best Practices (authoritative policy):\n{best_practices}\n\n"
        if best_practices
        else ""
    )

    project = req.project or {}
    table_lines = _lines(
        [
            f"{t.get('name', '')} ({t.get('kind', 'table')}): "
            f"{', '.join(str(c) for c in (t.get('columns') or [])[:12])}"
            for t in req.tables
            if isinstance(t, dict) and t.get("name")
        ],
        40,
    )
    doc_lines = _lines(
        [
            f"{d.get('title', 'document')}: {(d.get('summary') or '')[:200]}"
            for d in req.documents
            if isinstance(d, dict)
        ],
        30,
    )
    query_lines = _lines(
        [
            f"{q.get('name', 'query')}: {(q.get('description') or '')[:160]}"
            for q in req.queries
            if isinstance(q, dict)
        ],
        30,
    )
    dashboard_lines = _lines(
        [str(d.get("name") or d.get("title") or "") for d in req.dashboards
         if isinstance(d, dict)],
        20,
    )
    kpi_line = ", ".join(str(k) for k in req.kpis[:30]) if req.kpis else "(none)"
    kg_block = format_knowledge_graph_context(req.knowledge_graph_context)
    kg_block = f"\n{kg_block}\n" if kg_block else ""

    prompt = (
        f"{best_practices_block}"
        f"SELECTED PROJECT: {project.get('name', 'this project')} "
        f"(status: {project.get('status', 'unknown')})\n\n"
        f"Project tables:\n{table_lines}\n\n"
        f"Project documents:\n{doc_lines}\n\n"
        f"Project saved queries:\n{query_lines}\n\n"
        f"Project dashboards:\n{dashboard_lines}\n\n"
        f"Project KPIs: {kpi_line}\n"
        f"{kg_block}\n"
        "Produce a Project Insight report for the SELECTED project only. Use "
        "clear business language, be concise, and ground everything in the "
        "context above. Recommended dashboards/queries/KPIs are suggestions and "
        "do not need to already exist. Do not fabricate KPI values.\n\n"
        "Return ONLY a JSON object with EXACTLY these keys. Replace every "
        "descriptive placeholder below with real, project-specific content "
        "drawn from the context above — never echo the placeholder text and "
        "never leave a primary field (question, label, title, name) blank.\n"
        "{\n"
        '  "executiveSummary": {\n'
        '    "summary": "2-4 sentence project status summary",\n'
        '    "critical": ["short bullet", ...],\n'
        '    "warnings": ["short bullet", ...],\n'
        '    "opportunities": ["short bullet", ...],\n'
        '    "recommendations": ["short bullet", ...]\n'
        "  },\n"
        '  "questionsToAsk": [{"id":"q1","question":"<a real, specific question '
        'about THIS project\'s data>","reason":"<why it matters>",'
        '"suggestedAction":"ask_project"}],\n'
        '  "trendDetection": [{"id":"t1","label":"<short descriptive trend name '
        'derived from the actual trend, e.g. Rising Late Deliveries>",'
        '"title":"<one-line headline>","description":"<what the trend shows>",'
        '"possibleCause":"<likely cause>","sourceSummary":"<evidence>",'
        '"chartLink":"","confidence":0.0}],\n'
        '  "recommendedDashboards": [{"id":"d1","title":"<specific dashboard '
        'name>","description":"<what it shows>","reason":"<why>",'
        '"status":"suggested","confidence":0.0,"backingSignals":[],'
        '"suggestedWidgets":[],"action":"generate"}],\n'
        '  "recommendedQueries": [{"id":"rq1","title":"<specific query name>",'
        '"businessQuestion":"<the question it answers>","reason":"<why>",'
        '"status":"suggested","confidence":0.0,"backingSignals":[],'
        '"recommendedTables":[],"recommendedKpis":[],"action":"generate"}],\n'
        '  "recommendedKpis": [{"id":"k1","name":"<specific KPI name>",'
        '"description":"<what it measures>","status":"recommended",'
        '"currentValue":null,"targetValue":null,"unit":"","reason":"<why>",'
        '"confidence":0.0,"backingSignals":[],"relatedDashboards":[],'
        '"relatedQueries":[],"relatedDataSources":[]}],\n'
        '  "insightValidationWorkflow": [{"id":"i1","title":"<specific insight '
        'title>","type":"risk","priority":"medium","confidence":0.0,'
        '"status":"new","evidenceSummary":"<evidence>","recommendedAction":""}]\n'
        "}\n\n"
        "RULES:\n"
        "- Provide 3-6 questionsToAsk, each a real question tied to this "
        "project's tables, documents, queries, or KPIs.\n"
        "- trendDetection: include a trend only when the context supports it, "
        "and give it a descriptive label derived from the actual trend (never "
        "'Trend A' or any generic placeholder).\n"
        "- Every recommendedDashboards / recommendedQueries / recommendedKpis / "
        "insightValidationWorkflow item MUST have a concrete title/name; omit "
        "any item you cannot name specifically rather than emitting a blank.\n"
        "- Do NOT return items whose question/label/title/name is empty — "
        "return an empty array for that section instead.\n"
        "- Do NOT fabricate KPI values; use null when unknown.\n\n"
        "OUTPUT FORMAT: respond with this JSON object and nothing else — no "
        "prose, no markdown, no code fences. Begin with { and end with }."
    )

    raw = await llm_client.generate(
        prompt=prompt,
        system_prompt=_PROJECT_INSIGHT_SYSTEM_PROMPT,
        model=settings.reasoning_model,
        temperature=0.2,
        num_ctx=16384,
        response_format="json",
    )

    parsed = _parse_json_response(raw) or {}
    es = parsed.get("executiveSummary")
    es = es if isinstance(es, dict) else {}
    executive = ProjectInsightExecutiveSummary(
        summary=str(es.get("summary", "")).strip(),
        critical=_str_list(es.get("critical")),
        warnings=_str_list(es.get("warnings")),
        opportunities=_str_list(es.get("opportunities")),
        recommendations=_str_list(es.get("recommendations")),
    )

    update_activity(req.user_id, req.tenant_id, req.project_id)
    return ProjectInsightResponse(
        executiveSummary=executive,
        questionsToAsk=_dict_list(parsed.get("questionsToAsk"), 8),
        trendDetection=_dict_list(parsed.get("trendDetection"), 8),
        recommendedDashboards=_dict_list(parsed.get("recommendedDashboards"), 8),
        recommendedQueries=_dict_list(parsed.get("recommendedQueries"), 8),
        recommendedKpis=_dict_list(parsed.get("recommendedKpis"), 12),
        insightValidationWorkflow=_dict_list(
            parsed.get("insightValidationWorkflow"), 12
        ),
        request_id=request_id,
        model_used=settings.reasoning_model,
    )


@router.post("/project/scopes/analyze", response_model=AnalyzeScopesResponse)
async def analyze_scopes(req: AnalyzeScopesRequest) -> AnalyzeScopesResponse:
    """Use AI to analyze saved queries and suggest drill-down scopes.

    The LLM determines:
    1. Which columns are meaningful for drill-down (identifiers, names — not aggregates)
    2. Direction: summarized/aggregated query → detailed/raw query
    """
    request_id = str(uuid.uuid4())
    verify_signature(req.model_dump(exclude={"signature"}), req.signature)

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
        model=settings.reasoning_model,
        temperature=0.0,
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
        model_used=settings.reasoning_model,
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


@router.post("/analyze-file", response_model=AnalyzeFileResponse)
async def analyze_file(req: AnalyzeFileRequest):
    """Analyze a file profile and return structured metadata."""
    verify_signature(req.model_dump(exclude={"signature"}), req.signature)

    request_id = str(uuid.uuid4())
    logger.info("[%s] File analysis request", request_id)

    raw = await llm_client.generate(
        prompt=req.prompt,
        system_prompt=(
            "You are a data analyst that analyzes uploaded data files. "
            "Return ONLY valid JSON with the exact structure requested. "
            "Do not include markdown formatting, code fences, or any text outside the JSON."
        ),
        model=settings.reasoning_model,
        temperature=0.1,
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
        model_used=settings.reasoning_model,
    )


# ── Document Profile ─────────────────────────────────────────────────

@router.post("/document/profile", response_model=DocumentProfileResponse)
async def profile_document(req: DocumentProfileRequest):
    """Profile an uploaded document — extract summary, tags, entities, KPIs, relationships."""
    update_activity()
    verify_signature(req.model_dump(exclude={"signature"}), req.signature)
    request_id = uuid.uuid4().hex[:12]
    logger.info("[%s] document/profile file=%s type=%s", request_id, req.filename, req.asset_type)

    tags_str = ", ".join(req.enabled_reference_tags[:50]) if req.enabled_reference_tags else "none"
    kpis_str = ", ".join(req.enabled_reference_kpis[:50]) if req.enabled_reference_kpis else "none"

    chunk_text = ""
    for c in req.chunks[:5]:
        chunk_text += f"\n--- Chunk {c.get('chunk_index', 0)} ---\n{c.get('text', '')[:1500]}\n"

    prompt = f"""You are a document analyst. Analyze this document and return a JSON profile.

File: {req.filename}
Type: {req.asset_type}
Content-Type: {req.content_type}

Available reference tags (use these first): {tags_str}
Available reference KPIs (use these first): {kpis_str}

Document text preview:
{req.text_preview[:3000]}

Document chunks:
{chunk_text}

Return ONLY valid JSON with this exact structure:
{{
  "summary": "2-3 sentence summary of the document's purpose and key content",
  "document_type": "type classification (e.g., audit_report, policy, contract, procedure, meeting_notes)",
  "business_domain": "primary business domain (e.g., supply_chain, finance, it_operations, manufacturing)",
  "process_area": "relevant process area (e.g., supplier_performance, quality_management, cost_management)",
  "tags": [
    {{"tag_key": "matching_tag_from_catalog", "display_name": "Human Readable Name", "confidence": 0.9, "source": "catalog"}}
  ],
  "entities": [
    {{"entity_type": "supplier|customer|product|process|risk|action", "name": "Entity Name", "confidence": 0.85, "evidence": "Brief quote or reference from document"}}
  ],
  "recommended_kpis": [
    {{"kpi_key": "matching_kpi_from_catalog", "display_name": "KPI Name", "confidence": 0.8, "reason": "Why this KPI is relevant"}}
  ],
  "relationship_hints": [
    {{"from_type": "document", "from_name": "{req.filename}", "relationship_type": "references_supplier|identifies_risk|governs_process|describes_policy", "to_type": "supplier|risk|process|policy", "to_name": "Target Name", "confidence": 0.8, "evidence": "Brief evidence"}}
  ],
  "document_family": {{
    "family_name": "Human Readable Family Name (e.g. IT Change Management)",
    "family_key": "normalized_snake_case_key",
    "family_type": "policy_process|incident_case|supplier_case|audit_package|compliance_package|operational_review|project_package|service_operations|security_response|contract_package|procedure_set|dashboard_context|general_knowledge_group",
    "confidence": 0.94,
    "role": "governing_policy|procedure|standard_operating_procedure|evidence|postmortem|audit_report|meeting_notes|review_deck|runbook|source_data|supporting_document|exception|template|contract|requirements|unknown",
    "reason": "Why this document belongs to this family",
    "auto_link": true
  }},
  "family_relationships": [
    {{"relationship_type": "governs|implements|procedure_for|policy_for|references|supersedes|depends_on|evidence_for|postmortem_for|remediation_for|related_to_datasource|measures_process|incident_impact", "target_type": "process|datasource|document|kpi|entity", "target_name": "Target Name", "confidence": 0.88, "evidence": "Brief evidence"}}
  ],
  "family_members_suggested": [
    {{"member_type": "datasource|document|kpi|query|dashboard", "member_name": "Member Name", "relationship_type": "measures_process|related_family_member|supports", "confidence": 0.85, "reason": "Why this member belongs in the family"}}
  ],
  "data_quality_notes": ["Any data quality observations"],
  "suggested_questions": ["Question a user might ask about this document"]
}}

Rules:
- Use reference tags/KPIs from the catalog when they match. Only suggest custom tags if no catalog tag fits.
- Return confidence scores between 0.0 and 1.0.
- Return evidence strings for entities and relationships.
- Only include information supported by the actual document text.
- Be specific — don't suggest generic tags unrelated to this document's content.

Document family rules:
- A document family is a group of related documents, data sources, queries, dashboards, KPIs, entities, or processes that together describe a business process, operational process, incident, supplier, audit, policy, procedure, service, contract, or compliance package.
- Use the document title, summary, type, tags, entities, KPIs, domain, process area, and explicit references to infer a family.
- Prefer clear family names such as: IT Change Management, Incident Management, Patch Management, Vulnerability Management, CloudAuth Service Operations, Supplier Quality Management, Logistics Carrier Performance, Claims Denial Management, Budget Utilization, Audit & Compliance.
- family_key must be a normalized snake_case version of family_name (lowercase, words joined with underscores, no punctuation).
- Set auto_link=true ONLY when document_family.confidence >= 0.90.
- If confidence is 0.70 to 0.89, still return the family but set auto_link=false.
- If confidence is below 0.70, set "document_family" to null.
- Only return family_relationships and family_members_suggested when supported by evidence. Do not invent unsupported relationships. Every relationship must include confidence and evidence."""

    try:
        raw = await llm_client.generate(
            prompt=prompt,
            model=settings.reasoning_model,
            temperature=0.1,
            max_tokens=2600,
        )

        # Parse JSON from response
        profile = _parse_json_response(raw)
        if not profile:
            profile = {"summary": raw[:500], "tags": [], "entities": [], "recommended_kpis": [], "relationship_hints": []}

        family = _normalize_document_family(profile.get("document_family"))

        return DocumentProfileResponse(
            summary=profile.get("summary", ""),
            document_type=profile.get("document_type", ""),
            business_domain=profile.get("business_domain", ""),
            process_area=profile.get("process_area", ""),
            tags=profile.get("tags", []),
            entities=profile.get("entities", []),
            recommended_kpis=profile.get("recommended_kpis", []),
            relationship_hints=profile.get("relationship_hints", []),
            data_quality_notes=profile.get("data_quality_notes", []),
            suggested_questions=profile.get("suggested_questions", []),
            document_family=family,
            family_relationships=profile.get("family_relationships", []) or [],
            family_members_suggested=profile.get("family_members_suggested", []) or [],
            request_id=request_id,
            model_used=settings.reasoning_model,
        )
    except Exception as exc:
        logger.exception("[%s] document profile failed: %s", request_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Document profiling failed: {exc}",
        )


def _normalize_family_key(name: str) -> str:
    """Normalize a family name into a snake_case key."""
    key = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return key


_FAMILY_TYPES = {
    "policy_process", "incident_case", "supplier_case", "audit_package",
    "compliance_package", "operational_review", "project_package",
    "service_operations", "security_response", "contract_package",
    "procedure_set", "dashboard_context", "general_knowledge_group",
}
_FAMILY_ROLES = {
    "governing_policy", "procedure", "standard_operating_procedure", "evidence",
    "postmortem", "audit_report", "meeting_notes", "review_deck", "runbook",
    "source_data", "supporting_document", "exception", "template", "contract",
    "requirements", "unknown",
}


def _normalize_document_family(fam: object) -> dict | None:
    """Validate/normalize the document_family object from the LLM.

    Returns None when the family is missing or below the 0.70 confidence floor.
    Enforces the auto_link threshold (>= 0.90) regardless of what the LLM set.
    """
    if not isinstance(fam, dict):
        return None
    name = str(fam.get("family_name", "")).strip()
    if not name:
        return None
    try:
        confidence = float(fam.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < 0.70:
        return None

    family_type = str(fam.get("family_type", "")).strip().lower()
    if family_type not in _FAMILY_TYPES:
        family_type = "general_knowledge_group"
    role = str(fam.get("role", "")).strip().lower()
    if role not in _FAMILY_ROLES:
        role = "unknown"

    key = str(fam.get("family_key", "")).strip().lower()
    if not key:
        key = _normalize_family_key(name)

    return {
        "family_name": name,
        "family_key": key,
        "family_type": family_type,
        "confidence": round(confidence, 4),
        "role": role,
        "reason": str(fam.get("reason", "")).strip(),
        "auto_link": confidence >= 0.90,
    }


# ── Family summary ───────────────────────────────────────────────────

@router.post("/family/summarize", response_model=FamilySummarizeResponse)
async def summarize_family(req: FamilySummarizeRequest) -> FamilySummarizeResponse:
    """Summarize a document family from its active members.

    Used to (re)build the rolled-up description, supported KPIs, related
    processes, suggested dashboards, and gap analysis for a family node.
    """
    update_activity(req.user_id, req.tenant_id, req.project_id)
    verify_signature(req.model_dump(exclude={"signature"}), req.signature)
    request_id = uuid.uuid4().hex[:12]

    docs_str = "\n".join(
        f"  - {d.get('name', '')}: {d.get('summary', '')[:240]}"
        for d in req.member_documents[:30]
    ) or "  (none)"
    ds_str = "\n".join(
        f"  - {d.get('name', '')}" + (f" (columns: {d.get('columns', '')})" if d.get("columns") else "")
        for d in req.member_datasources[:30]
    ) or "  (none)"
    kpis_str = ", ".join(req.member_kpis[:40]) or "(none)"
    entities_str = ", ".join(req.member_entities[:40]) or "(none)"
    rels_str = "\n".join(
        f"  - {r.get('from', '')} {r.get('relationship_type', '')} {r.get('to', '')}"
        for r in req.relationships[:40]
    ) or "  (none)"

    prompt = f"""You are summarizing a project document family.

Family name: {req.family_name}
Family type: {req.family_type}
Business domain: {req.business_domain}

Member documents:
{docs_str}

Member data sources:
{ds_str}

Member KPIs: {kpis_str}
Member entities: {entities_str}

Known relationships:
{rels_str}

Return ONLY valid JSON with this exact structure:
{{
  "summary": "2-4 sentence summary of what this family describes",
  "primary_purpose": "One sentence describing the family's primary purpose",
  "supported_kpis": ["KPI names this family supports"],
  "related_processes": ["Business/operational processes this family relates to"],
  "suggested_dashboards": ["Dashboards that would be useful for this family"],
  "missing_documents": ["Document types that appear to be missing from this family"],
  "suggested_questions": ["Questions a user might ask about this family"]
}}

Rules:
- Only use information supported by the members listed above.
- Keep lists concise (max 6 items each).
- Do not invent member documents or data sources that were not provided."""

    try:
        raw = await llm_client.generate(
            prompt=prompt,
            model=settings.reasoning_model,
            temperature=0.2,
            max_tokens=1200,
        )
        parsed = _parse_json_response(raw) or {}
    except Exception as exc:
        logger.exception("[%s] family summarize failed: %s", request_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Family summarize failed: {exc}",
        )

    def _strlist(v: object) -> list[str]:
        if isinstance(v, list):
            return [str(x) for x in v if str(x).strip()]
        return []

    return FamilySummarizeResponse(
        summary=str(parsed.get("summary", "")),
        primary_purpose=str(parsed.get("primary_purpose", "")),
        supported_kpis=_strlist(parsed.get("supported_kpis")),
        related_processes=_strlist(parsed.get("related_processes")),
        suggested_dashboards=_strlist(parsed.get("suggested_dashboards")),
        missing_documents=_strlist(parsed.get("missing_documents")),
        suggested_questions=_strlist(parsed.get("suggested_questions")),
        request_id=request_id,
        model_used=settings.reasoning_model,
    )


@router.post("/reference-library/summarize", response_model=ReferenceSummarizeResponse)
async def summarize_reference_document(req: ReferenceSummarizeRequest) -> ReferenceSummarizeResponse:
    """Summarize a reference-library document (standard/regulation/policy).

    Produces a short, AI-grounding summary focused on what the document governs,
    who it applies to, and any specific thresholds/requirements an AI assistant
    should know when citing it.
    """
    update_activity(req.user_id, req.tenant_id, req.project_id)
    verify_signature(req.model_dump(exclude={"signature"}), req.signature)
    request_id = uuid.uuid4().hex[:12]
    logger.info(
        "[%s] reference-library/summarize doc=%s title=%s", request_id, req.document_id, req.title
    )

    text_preview = (req.extracted_text or "").strip()[:8000]
    if not text_preview:
        return ReferenceSummarizeResponse(
            summary="", request_id=request_id, model_used=settings.reasoning_model
        )

    prompt = f"""You are summarizing a reference document (standard, regulation, framework, or policy) for use as AI grounding context.

Title: {req.title}
Issuing body: {req.issuing_body or "unknown"}
Domain: {req.domain_tag or "unspecified"}

Document text:
{text_preview}

Write a 2-4 sentence summary for an AI assistant. Focus on:
- what this document governs (its scope/purpose),
- who it applies to,
- any specific thresholds, controls, or requirements an assistant should know when citing it.

Return ONLY the summary text — no preamble, no headings, no JSON."""

    try:
        raw = await llm_client.generate(
            prompt=prompt,
            model=settings.reasoning_model,
            temperature=0.2,
            max_tokens=400,
        )
    except Exception as exc:
        logger.exception("[%s] reference summarize failed: %s", request_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Reference summarize failed: {exc}",
        )

    return ReferenceSummarizeResponse(
        summary=(raw or "").strip(),
        request_id=request_id,
        model_used=settings.reasoning_model,
    )


@router.post("/reference-library/suggest", response_model=ReferenceSuggestResponse)
async def suggest_references(req: ReferenceSuggestRequest) -> ReferenceSuggestResponse:
    """Suggest which Industry reference domains add value for a project's signals.

    Only suggests domains clearly relevant to the project's data/documents — does
    not suggest broadly to maximize coverage.
    """
    update_activity(req.user_id, req.tenant_id, req.project_id)
    verify_signature(req.model_dump(exclude={"signature"}), req.signature)
    request_id = uuid.uuid4().hex[:12]

    candidate_str = ", ".join(req.candidate_domains[:40]) or "(none)"
    ds_str = ", ".join(req.data_source_types[:40]) or "(none)"
    tables_str = ", ".join(req.table_names[:80]) or "(none)"
    docs_str = ", ".join(req.document_types[:40]) or "(none)"
    topics_str = ", ".join(req.recent_query_topics[:40]) or "(none)"

    prompt = f"""Given this project's data and document signals, identify which Industry-tier reference domains would add valuable context. Only suggest domains clearly relevant — do not suggest broadly to maximize coverage.

Available reference domains: {candidate_str}

Project signals:
- Data source types: {ds_str}
- Table names: {tables_str}
- Document types: {docs_str}
- Recent query topics: {topics_str}

Return ONLY valid JSON with this exact structure:
{{
  "suggestions": [
    {{"domainTag": "one of the available domains", "reasoning": "one sentence on why this project would benefit"}}
  ]
}}

Rules:
- Only use domains from the available list above.
- Suggest at most 4 domains, fewest that are clearly justified.
- If nothing is clearly relevant, return an empty suggestions list."""

    try:
        raw = await llm_client.generate(
            prompt=prompt,
            model=settings.reasoning_model,
            temperature=0.2,
            max_tokens=800,
        )
        parsed = _parse_json_response(raw) or {}
    except Exception as exc:
        logger.exception("[%s] reference suggest failed: %s", request_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Reference suggest failed: {exc}",
        )

    allowed = {d.lower() for d in req.candidate_domains}
    suggestions: list[dict] = []
    for s in parsed.get("suggestions", []):
        if not isinstance(s, dict):
            continue
        domain = str(s.get("domainTag", "")).strip()
        if domain and domain.lower() in allowed:
            suggestions.append(
                {"domainTag": domain, "reasoning": str(s.get("reasoning", "")).strip()}
            )

    return ReferenceSuggestResponse(
        suggestions=suggestions,
        request_id=request_id,
        model_used=settings.reasoning_model,
    )


def _parse_json_response(text: str) -> dict | None:
    """Extract JSON object from LLM response text."""
    import json as _json

    # Try direct parse
    try:
        return _json.loads(text)
    except _json.JSONDecodeError:
        pass

    # Try to find JSON block
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return _json.loads(match.group())
        except _json.JSONDecodeError:
            pass

    # Truncation salvage: a response cut off mid-generation (context window
    # exhausted) is prefix-valid JSON. Trim back to the last complete object
    # boundary and close the open brackets, so every COMPLETE analysis in a
    # truncated plan survives instead of the whole plan degrading to [].
    return _repair_truncated_json(text)


def _repair_truncated_json(text: str) -> dict | None:
    """Best-effort recovery of a JSON object truncated mid-stream."""
    import json as _json

    start = text.find("{")
    if start == -1:
        return None
    snippet = text[start:]
    cut = snippet.rfind("}")
    while cut != -1:
        candidate = snippet[: cut + 1]
        open_braces = candidate.count("{") - candidate.count("}")
        open_arrays = candidate.count("[") - candidate.count("]")
        if open_braces >= 0 and open_arrays >= 0:
            try:
                repaired = _json.loads(
                    candidate + "]" * open_arrays + "}" * open_braces
                )
                logger.warning(
                    "Salvaged truncated JSON response: kept %s of %s chars",
                    cut + 1, len(snippet),
                )
                return repaired
            except _json.JSONDecodeError:
                pass
        cut = snippet.rfind("}", 0, cut)
    return None
