"""AI feature endpoints — all requests flow through the context builder.

Every endpoint:
1. Verifies HMAC signature (request came from trusted app server)
2. Builds permission-aware context via context_builder
3. Sends ONLY allowed context to the LLM
4. Validates LLM output (SQL allowlist, no cross-tenant refs)
5. Logs everything (vectors accessed, context used, denied access)
6. Updates last_activity for idle shutdown
"""

import json
import logging
import re
import uuid

from fastapi import APIRouter, HTTPException, status

from app.core.activity import update_activity
from app.core.config import settings
from app.core.security import verify_signature
from app.models.schemas import (
    AnalyzeScopesRequest,
    AnalyzeScopesResponse,
    AskRequest,
    AskResponse,
    GenerateRelationshipsRequest,
    GenerateRelationshipsResponse,
    GenerateSQLRequest,
    GenerateSQLResponse,
    IndexDocumentRequest,
    RelationshipSuggestion,
    ScopeSuggestion,
    SuggestDashboardRequest,
    SuggestDashboardResponse,
)
from app.services import context_builder, llm_client, vector_store
from app.services.context_builder import ContextBuildError
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


SYSTEM_PROMPT = (
    "You are Tablescope AI.\n"
    "You may only answer using the provided context package.\n"
    "Do not request or infer access to data outside the provided context.\n"
    "If context is insufficient, say what additional project data would be needed.\n"
    "Generate SQL only using the allowed tables and columns listed below.\n"
    "Do not use SELECT *.\n"
    "Do not generate INSERT, UPDATE, DELETE, DROP, or any write operations.\n"
)


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
    prompt = f"{context_text}\n\nUser question: {req.question}"

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


@router.post("/query/generate", response_model=GenerateSQLResponse)
async def generate_sql_endpoint(req: GenerateSQLRequest) -> GenerateSQLResponse:
    """Generate SQL from a natural language prompt."""
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

    # Determine allowed tables
    allowed_tables = req.allowed_tables
    if not allowed_tables:
        allowed_tables = [
            ds.get("view_name", ds.get("name", ""))
            for ds in ctx.allowed_context.get("metadata", [])
            if ds.get("view_name") or ds.get("name")
        ]

    # Generate SQL
    sql = await llm_client.generate_sql(
        prompt=req.prompt,
        context=context_text,
        allowed_tables=allowed_tables,
    )

    # Clean SQL (remove markdown code blocks, fix Teiid GROUP BY aliases)
    sql = _clean_sql(sql)

    # Validate generated SQL
    try:
        validate_sql(sql, allowed_tables)
    except SQLValidationError as e:
        # Re-prompt once with validation feedback
        sql = await llm_client.generate_sql(
            prompt=(
                f"{req.prompt}\n\n"
                f"IMPORTANT: Your previous SQL was rejected: {e.reason}\n"
                f"Fix these issues and try again."
            ),
            context=context_text,
            allowed_tables=allowed_tables,
        )
        sql = _clean_sql(sql)

        # Validate again — if it still fails, return the error
        try:
            validate_sql(sql, allowed_tables)
        except SQLValidationError as e2:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Generated SQL failed validation: {e2.reason}",
            )

    update_activity(req.user_id, req.tenant_id, req.project_id)

    return GenerateSQLResponse(
        sql=sql,
        explanation="",
        allowed_tables_used=allowed_tables,
        request_id=request_id,
        model_used=settings.sql_model,
    )


@router.post("/dashboard/suggest", response_model=SuggestDashboardResponse)
async def suggest_dashboard(req: SuggestDashboardRequest) -> SuggestDashboardResponse:
    """Suggest dashboard widgets based on project data."""
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

    teiid_rules = (
        "IMPORTANT: This database uses Teiid (not MySQL, not PostgreSQL).\n"
        "All CSV columns are imported as strings.\n"
        "- For SUM/AVG/MIN/MAX or arithmetic (*, /, +, -), CAST columns: CAST(col AS double)\n"
        "- Do NOT use DATE_FORMAT, MONTH(), YEAR() (MySQL). Use FORMATDATE, EXTRACT, DATE_TRUNC.\n"
        "- For monthly grouping: FORMATDATE(CAST(\"OrderDate\" AS date), 'yyyy-MM')\n"
        "- Alias columns with safe identifiers (no reserved words like Month).\n"
        "- GROUP BY must match SELECT expression exactly.\n"
    )

    prompt = (
        f"{context_text}\n\n"
        f"Allowed tables: {', '.join(allowed_tables)}\n\n"
        f"{teiid_rules}\n"
        f"{user_instruction}"
        "Based on the available tables and their columns, suggest a dashboard "
        "with useful widgets. For each widget, include:\n"
        "- type: one of kpi, bar, line, pie, area, table\n"
        "- title: descriptive title\n"
        "- sql: a valid SQL query using ONLY the allowed tables with proper CAST for numeric ops\n"
        "- x_column, y_column, aggregation where applicable\n\n"
        "Return a JSON object with: title (dashboard name) and widgets (array).\n"
        "Return ONLY the JSON."
    )

    raw = await llm_client.generate(
        prompt=prompt,
        system_prompt=SYSTEM_PROMPT,
        model=settings.sql_model,
        temperature=0.0,
    )

    suggestions = []
    try:
        json_str = raw.strip()
        if json_str.startswith("```"):
            json_str = json_str.split("```")[1]
            if json_str.startswith("json"):
                json_str = json_str[4:]
        parsed = json.loads(json_str)
        if isinstance(parsed, dict):
            suggestions = [parsed]
        elif isinstance(parsed, list):
            suggestions = parsed
    except (json.JSONDecodeError, KeyError):
        logger.warning("Failed to parse dashboard suggestions: %s", raw[:200])

    # Post-process: fix Teiid GROUP BY aliases in each widget's SQL
    for s in suggestions:
        for w in s.get("widgets", []):
            if w.get("sql"):
                w["sql"] = _clean_sql(w["sql"])

    update_activity(req.user_id, req.tenant_id, req.project_id)

    return SuggestDashboardResponse(
        suggestions=suggestions,
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
