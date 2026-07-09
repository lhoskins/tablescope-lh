"""Ollama LLM client with model routing.

- SQL generation → qwen2.5-coder:7b
- Reasoning/explanation → llama3.1:8b
- Embeddings → nomic-embed-text

The LLM only sees the context package built by the context_builder.
It never has direct access to files, databases, or vector collections.
"""

import logging
from typing import Any

import httpx

from app.core.config import settings
from app.services import ai_gate

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(180.0, connect=10.0)


async def generate(
    prompt: str,
    system_prompt: str = "",
    model: str | None = None,
    temperature: float = 0.1,
    max_tokens: int | None = None,
    num_ctx: int | None = None,
    response_format: str | None = None,
    tenant_id: int | None = None,
) -> str:
    """Generate text completion from Ollama.

    ``response_format="json"`` forces Ollama's constrained JSON decoding so the
    model can only emit a syntactically valid JSON value — use it for any call
    whose response is parsed as JSON, to stop the model from wrapping output in
    prose/markdown.
    """
    model = model or settings.reasoning_model

    options: dict[str, Any] = {"temperature": temperature}
    if max_tokens is not None:
        options["num_predict"] = max_tokens
    if num_ctx is not None:
        options["num_ctx"] = num_ctx

    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": options,
    }
    if response_format == "json":
        payload["format"] = "json"
    if system_prompt:
        payload["system"] = system_prompt

    async with ai_gate.acquire(tenant_id):
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{settings.ollama_url}/api/generate",
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()["response"]


_TEIID_RULES = (
    "IMPORTANT: This database uses Teiid (not MySQL, not PostgreSQL).\n"
    "Teiid imports CSV columns as strings.\n"
    "Rules for Teiid SQL:\n"
    "1. For ANY arithmetic (*, /, +, -) or aggregation (SUM, AVG, MIN, MAX) "
    "on numeric columns, CAST each column: CAST(col AS double).\n"
    "   Example: SUM(CAST(\"UnitPrice\" AS double) * CAST(\"Quantity\" AS double))\n"
    "2. COUNT does not need CAST.\n"
    "3. Do NOT use DATE_FORMAT, MONTH(), YEAR(), DAY() — these are MySQL functions.\n"
    "4. For date formatting use FORMATDATE(date_col, 'yyyy-MM') or "
    "CAST date columns: CAST(col AS date).\n"
    "5. For date extraction use EXTRACT(YEAR FROM col), EXTRACT(MONTH FROM col).\n"
    "6. For date truncation use DATE_TRUNC('MONTH', col) or DATE_TRUNC('YEAR', col).\n"
    "7. For grouping by month, use: FORMATDATE(CAST(\"OrderDate\" AS date), 'yyyy-MM')\n"
    "8. Alias columns using valid identifiers (letters/digits/underscore only, "
    "no reserved words like Month). Use SalesMonth, OrderYear, etc.\n"
    "9. The GROUP BY clause must match the SELECT expression exactly. Any "
    "non-aggregated column in SELECT/ORDER BY must appear in GROUP BY.\n"
    "10. For a ratio/rate/percentage, CAST BOTH operands of the division: "
    "CAST(\"DefectQty\" AS double) / CAST(\"ReceivedQty\" AS double). Guard "
    "divide-by-zero with NULLIF(CAST(\"denom\" AS double), 0).\n"
    "11. Never use DATEDIFF, DATE_DIFF or DATE_PART, and NEVER subtract two "
    "dates/timestamps (d2 - d1 raises TEIID30070) or wrap a subtraction in "
    "EXTRACT(DAY FROM ...). For a day count between two dates use "
    "TIMESTAMPDIFF(SQL_TSI_DAY, <earlier>, <later>), parsing text dates first. "
    "When you aggregate the day count, CAST it to double so it decodes: "
    "AVG(CAST(TIMESTAMPDIFF(SQL_TSI_DAY, "
    "PARSETIMESTAMP(\"ShipDate\", 'M/d/yyyy'), "
    "PARSETIMESTAMP(\"DeliveryDate\", 'M/d/yyyy')) AS double)).\n"
)

_SEMANTIC_RULES = (
    "SOURCE DISCOVERY — read carefully:\n"
    "- The user describes the analysis in plain English. They will NOT give you "
    "exact table or column names.\n"
    "- NEVER treat words from the user's request as table names. For example, "
    "in 'monthly ticket ratio for network', 'ticket' and 'network' are concepts, "
    "NOT tables.\n"
    "- You may ONLY reference tables from the 'Available sources' catalog below. "
    "Semantically map the user's intent to the closest matching source name(s) "
    "and their real columns.\n"
    "- Use ONLY column names that the chosen source actually exposes (listed in "
    "the catalog). Do not invent columns.\n"
    "- If no available source reasonably matches the request, return exactly "
    "'NEED_CLARIFICATION' (and nothing else) instead of guessing.\n"
)


def _catalog_text(
    allowed_tables: list[str],
    source_catalog: list[Any] | None,
) -> str:
    """Render the available-source catalog (name + columns + description)."""
    if source_catalog:
        lines: list[str] = []
        for entry in source_catalog:
            name = getattr(entry, "name", None) or (
                entry.get("name") if isinstance(entry, dict) else None
            )
            if not name:
                continue
            columns = getattr(entry, "columns", None)
            description = getattr(entry, "description", None)
            kind = getattr(entry, "kind", None)
            if isinstance(entry, dict):
                columns = entry.get("columns")
                description = entry.get("description")
                kind = entry.get("kind")
            col_str = ", ".join(columns or []) or "(columns unknown)"
            label = "saved query" if kind == "query" else "data source"
            desc = f" — {description}" if description else ""
            lines.append(f'- "{name}" [{label}]{desc}\n    columns: {col_str}')
        if lines:
            return "Available sources (use ONLY these):\n" + "\n".join(lines)
    return "Available sources (use ONLY these table names): " + ", ".join(
        allowed_tables
    )


def _resolver_hint(
    preferred_sources: list[str] | None,
    relevant_columns: list[str] | None,
) -> str:
    """Render the resolver's preferred source/column guidance, if any."""
    if not preferred_sources and not relevant_columns:
        return ""
    lines = ["Resolved source guidance (from the semantic source resolver):"]
    if preferred_sources:
        lines.append(
            "- Preferred source(s) — use these unless they cannot answer the "
            f"request: {', '.join(preferred_sources)}"
        )
    if relevant_columns:
        lines.append(
            "- Relevant columns to prioritize: "
            f"{', '.join(relevant_columns)}"
        )
    lines.append(
        "- Only fall back to another authorized source if the preferred "
        "source genuinely cannot answer the request."
    )
    return "\n".join(lines) + "\n\n"


async def generate_sql(
    prompt: str,
    context: str,
    allowed_tables: list[str],
    source_catalog: list[Any] | None = None,
    preferred_sources: list[str] | None = None,
    relevant_columns: list[str] | None = None,
    tenant_id: int | None = None,
) -> str:
    """Generate SQL using the code-specialized model with semantic discovery."""
    catalog = _catalog_text(allowed_tables, source_catalog)
    hint = _resolver_hint(preferred_sources, relevant_columns)
    system_prompt = (
        "You are Tablescope AI.\n"
        "You may only answer using the provided context package.\n"
        "Do not request or infer access to data outside the provided context.\n"
        "Generate SQL only using the allowed sources and columns listed below.\n"
        "Do not use SELECT *.\n"
        "Do not generate INSERT, UPDATE, DELETE, DROP, or any write operations.\n"
        "Return only the SQL query, no explanation.\n"
        "When a Knowledge Graph context block is present, prioritize SQL that "
        "measures or validates its risks, opportunities, gaps, warnings, "
        "recommended/measured KPIs, documented processes, and entity "
        "relationships. If the graph names a recommended KPI but no datasource "
        "or query can measure it, do NOT invent SQL. Reference Library "
        "documents are guidance only — never use a reference document as a SQL "
        "data source.\n\n"
        f"{_SEMANTIC_RULES}\n"
        f"{_TEIID_RULES}\n"
        f"{hint}"
        f"{catalog}\n\n"
        f"Context:\n{context}"
    )

    return await generate(
        prompt=prompt,
        system_prompt=system_prompt,
        model=settings.sql_model,
        temperature=0.0,
        tenant_id=tenant_id,
    )


async def repair_sql(
    prompt: str,
    context: str,
    allowed_tables: list[str],
    failed_sql: str,
    validation_error: str,
    source_catalog: list[Any] | None = None,
    preferred_sources: list[str] | None = None,
    relevant_columns: list[str] | None = None,
    tenant_id: int | None = None,
) -> str:
    """Ask the model to fix SQL that failed validation, preserving intent."""
    catalog = _catalog_text(allowed_tables, source_catalog)
    hint = _resolver_hint(preferred_sources, relevant_columns)
    system_prompt = (
        "You are Tablescope AI repairing a SQL query that failed validation.\n"
        "Fix the SQL so it passes, while preserving the user's analytical intent.\n"
        "- Do NOT invent table names.\n"
        "- Replace any unauthorized table reference with the closest matching "
        "authorized source from the catalog.\n"
        "- Words from the user's request (e.g. 'your', 'tickets') are concepts, "
        "NOT tables — map them to real sources.\n"
        "- Use only known source names and their real columns.\n"
        "- Do not use SELECT *. Read-only queries only.\n"
        "- If no authorized source can satisfy the request, return exactly "
        "'NEED_CLARIFICATION'.\n"
        "Return ONLY the corrected SQL, no explanation.\n\n"
        f"{_TEIID_RULES}\n"
        f"{hint}"
        f"{catalog}\n\n"
        f"Context:\n{context}"
    )
    repair_prompt = (
        f"User request: {prompt}\n\n"
        f"The following SQL was rejected:\n{failed_sql}\n\n"
        f"Validation error: {validation_error}\n\n"
        "Return the corrected SQL."
    )
    return await generate(
        prompt=repair_prompt,
        system_prompt=system_prompt,
        model=settings.sql_model,
        temperature=0.0,
        tenant_id=tenant_id,
    )


async def generate_embeddings(texts: list[str]) -> list[list[float]]:
    """Generate embeddings using nomic-embed-text."""
    embeddings = []
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for text in texts:
            async with ai_gate.acquire(None):
                resp = await client.post(
                    f"{settings.ollama_url}/api/embeddings",
                    json={
                        "model": settings.embedding_model,
                        "prompt": text,
                    },
                )
                resp.raise_for_status()
                embeddings.append(resp.json()["embedding"])
    return embeddings


async def generate_embedding(text: str) -> list[float]:
    """Generate a single embedding vector."""
    result = await generate_embeddings([text])
    return result[0]


async def check_health() -> str:
    """Check if Ollama is reachable and has models loaded."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.get(f"{settings.ollama_url}/api/tags")
            resp.raise_for_status()
            models = resp.json().get("models", [])
            if models:
                return "ok"
            return "no_models"
    except Exception as e:
        logger.error("Ollama health check failed: %s", e)
        return "unavailable"
