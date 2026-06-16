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
    IntelligenceInterpretRequest,
    IntelligenceInterpretResponse,
    IntelligencePlanRequest,
    IntelligencePlanResponse,
    InterpretedInsight,
    MatchQueryRequest,
    MatchQueryResponse,
    PlannedAnalysis,
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
        "CRITICAL: Use ONLY the tables listed in 'Allowed tables' above. Do NOT "
        "invent or assume any other tables (e.g. Sales, Product, Customers) — "
        "every widget's SQL must reference only those exact table names.\n\n"
        f"{teiid_rules}\n"
        f"{user_instruction}"
        "Based on the available tables and their columns, suggest a dashboard "
        "with useful widgets. Analyze the data carefully and choose the BEST "
        "chart type for each metric — do NOT default everything to bar charts.\n\n"
        "Guidelines for chart type selection:\n"
        "- kpi: single-number metrics (totals, counts, averages) — use gridW=3 or 4, gridH=2\n"
        "- bar: comparisons across categories — use gridW=6, gridH=4\n"
        "- line: trends over time — use gridW=6 or 8, gridH=4\n"
        "- pie: proportions/shares of a whole (limit to 5-8 slices) — use gridW=4 or 6, gridH=4\n"
        "- area: cumulative trends or stacked comparisons — use gridW=6, gridH=4\n"
        "- table: detailed data listings — use gridW=12, gridH=5\n\n"
        "For each widget provide:\n"
        "- type: one of kpi, bar, line, pie, area, table\n"
        "- title: descriptive title\n"
        "- sql: valid SQL using ONLY the allowed tables with proper CAST for numeric ops\n"
        "- x_column: the column for the X axis or category\n"
        "- y_column: the column for the Y axis or value\n"
        "- aggregation: count, sum, avg, min, max\n"
        "- gridX: X position on a 12-column grid (0-11)\n"
        "- gridY: Y position in grid rows\n"
        "- gridW: width in grid columns (1-12)\n"
        "- gridH: height in grid rows (2 for kpi, 4-5 for charts)\n\n"
        "Layout rules:\n"
        "- Grid is 12 columns wide. Place KPI widgets across the top row.\n"
        "- Vary the layout — mix sizes, use full-width charts where appropriate.\n"
        "- Don't place all widgets in the same size or same column arrangement.\n"
        "- Create a visually balanced dashboard with 4-8 widgets.\n\n"
        "Return a JSON object with: title (dashboard name) and widgets (array).\n"
        "Return ONLY the JSON."
    )

    raw = await llm_client.generate(
        prompt=prompt,
        system_prompt=SYSTEM_PROMPT,
        model=settings.sql_model,
        temperature=0.3,
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

    # Post-process: fix Teiid GROUP BY aliases in each widget's SQL, then drop
    # any widget whose SQL references a table outside the project's allowed set.
    # The LLM occasionally hallucinates generic tables (e.g. "Sales", "Product")
    # that do not belong to this tenant/project; those must never reach the user.
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
        s["widgets"] = kept_widgets

    update_activity(req.user_id, req.tenant_id, req.project_id)

    return SuggestDashboardResponse(
        suggestions=suggestions,
        request_id=request_id,
        model_used=settings.reasoning_model,
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
        doc_lines = "\nProject documents (title — summary — tags):\n" + "\n".join(
            f"  - {d.get('title', 'document')}: {(d.get('summary') or '')[:300]}"
            + (f"  [tags: {', '.join(d.get('tags', []))}]" if d.get("tags") else "")
            for d in req.documents[:25]
        )

    teiid_rules = (
        "This database uses Teiid (not MySQL/PostgreSQL). CSV columns are strings.\n"
        "- For SUM/AVG/MIN/MAX or arithmetic, CAST columns: CAST(col AS double).\n"
        "- Do NOT use DATE_FORMAT/MONTH()/YEAR(). Use FORMATDATE, EXTRACT, DATE_TRUNC.\n"
        "- Monthly grouping: FORMATDATE(CAST(\"OrderDate\" AS date), 'yyyy-MM').\n"
        "- Alias columns with safe identifiers (no reserved words). GROUP BY must "
        "match the SELECT expression exactly. Never use SELECT *.\n"
    )

    prompt = (
        f"{context_text}\n{doc_lines}\n\n"
        f"Allowed tables (use ONLY these, exact names): {', '.join(allowed_tables)}\n\n"
        f"{teiid_rules}\n"
        f"Propose up to {req.max_analyses} of the MOST valuable analyses for this "
        "project. Cover a mix of risks, trends, and opportunities where the data "
        "supports it. Each analysis must be answerable from the allowed tables OR "
        "grounded in a listed document.\n\n"
        "For data analyses, write a single read-only SQL query that returns a small "
        "result suitable for a chart or KPI (aggregate/group — not raw dumps). "
        "Choose the chart type that best fits: 'bar' (compare categories), 'line' "
        "(trend over time), 'kpi_grid' (a few headline numbers).\n"
        "For document-based findings, leave sql empty, set chart_type to 'none', and "
        "list the relevant document titles in source_documents.\n\n"
        "Return ONLY a JSON object: {\"analyses\": [ {\n"
        "  \"id\": \"a1\",\n"
        "  \"category\": \"risk|trend|opportunity\",\n"
        "  \"title\": \"short headline\",\n"
        "  \"rationale\": \"why this matters for the business (1 sentence)\",\n"
        "  \"sql\": \"SELECT ... (empty for document findings)\",\n"
        "  \"chart_type\": \"bar|line|kpi_grid|none\",\n"
        "  \"label_column\": \"alias used for the category/x axis\",\n"
        "  \"value_column\": \"alias used for the numeric value\",\n"
        "  \"severity_hint\": \"critical|urgent|watch|opportunity|info\",\n"
        "  \"source_documents\": [\"doc title\"]\n"
        "} ] }"
    )

    raw = await llm_client.generate(
        prompt=prompt,
        system_prompt=_INTEL_SYSTEM_PROMPT,
        model=settings.reasoning_model,
        temperature=0.3,
    )

    parsed = _parse_json_response(raw)
    analyses: list[PlannedAnalysis] = []
    if parsed and isinstance(parsed.get("analyses"), list):
        for i, a in enumerate(parsed["analyses"][: req.max_analyses]):
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
            if category not in ("risk", "trend", "opportunity"):
                category = "trend"
            chart_type = str(a.get("chart_type", "bar")).lower()
            if chart_type not in ("bar", "line", "kpi_grid", "none"):
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

    return None
