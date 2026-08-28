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

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(180.0, connect=10.0)

# vLLM's min_tokens suppresses an early stop (EOS or a matched stop sequence)
# until this many tokens are generated. muse-glimmer sometimes stops right
# after a short reasoning burst -- observed live as a 102-char reasoning-only
# completion with finish_reason=stop at ~30 tokens used, well under its 1024
# max_tokens budget -- and never reaches the content channel. Confirmed live
# against this deployment: the same prompt with min_tokens=150 forced it
# through to a complete, correct SQL query. Applied only to SQL generation/
# repair (the two calls this was reproduced against); a plain generate()
# call is unaffected unless a caller passes min_tokens explicitly.
_SQL_MIN_TOKENS = 150


def _is_openai_target(target_url: str) -> bool:
    """Heuristic: vLLM/OpenAI-compatible endpoints expose a /v1 base path."""
    return target_url.endswith("/v1") or "/v1/" in target_url


async def _generate_openai(
    prompt: str,
    system_prompt: str = "",
    model: str = "",
    target_url: str = "",
    temperature: float = 0.1,
    max_tokens: int | None = None,
    min_tokens: int | None = None,
    stop: list[str] | None = None,
    response_format: str | None = None,
) -> str:
    """Generate using a vLLM/OpenAI-compatible /v1/chat/completions endpoint."""
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if min_tokens is not None:
        payload["min_tokens"] = min_tokens
    if stop:
        payload["stop"] = stop
    if response_format == "json":
        payload["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            f"{target_url}/chat/completions",
            json=payload,
        )
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError:
            # raise_for_status() alone discards the response body, so a vLLM
            # rejection (e.g. requested max_tokens + prompt tokens exceeding
            # max_model_len) surfaced as a bare "400 Bad Request" with no
            # explanation anywhere in the logs. Log the body before
            # re-raising so the cause is visible without reproducing the
            # call by hand against the model server.
            logger.error(
                "vLLM target %s rejected the request (%s): %s",
                target_url, resp.status_code, resp.text[:1000],
            )
            raise
        data = resp.json()
        choice = data["choices"][0]
        message = choice["message"]
        content = message.get("content") or ""
        if not content and message.get("reasoning"):
            # A reasoning model (e.g. muse-glimmer) returns "reasoning" and
            # "content" as separate fields. When content comes back empty the
            # model spent its completion on the reasoning channel and never
            # emitted an answer -- falling back to the reasoning trace here
            # used to hand a paraphrase of the prompt to callers expecting
            # JSON, guaranteeing a downstream parse failure that looked like
            # malformed output rather than what it actually was: no output.
            # Log it for diagnosis and return empty so that failure is honest.
            #
            # finish_reason distinguishes the two ways this happens: "length"
            # means generation was cut off before it could reach the content
            # channel (a max_tokens/budget problem); "stop" means the model
            # reached a natural stopping point after only a short reasoning
            # burst, well under its max_tokens budget. Confirmed live against
            # this deployment (project 41 "revenue by quarter"): a bare
            # request stopped at 102 chars of reasoning with finish_reason
            # "stop" and max_tokens=1024 unused; the same request with
            # min_tokens=150 suppressed that early stop and produced a
            # complete, correct SQL query. generate_sql/repair_sql now pass
            # min_tokens for exactly this reason -- if this warning still
            # fires for either of those, min_tokens needs to go higher, not
            # max_tokens.
            logger.warning(
                "vLLM target %s returned no content, only reasoning (%d chars, "
                "finish_reason=%s, requested max_tokens=%s); treating as an "
                "empty completion",
                target_url,
                len(str(message.get("reasoning") or "")),
                choice.get("finish_reason"),
                payload.get("max_tokens"),
            )
        text = str(content)
        # Muse Glimmer emits channel-scoped messages (to=self reasoning,
        # assistant to=user final answer). When the vLLM parser does not split
        # them, keep only the final user-facing segment.
        for marker in ("assistant to=user", " to=user", "to=user"):
            if marker in text:
                text = text.split(marker)[-1]
        return text.strip()


async def _generate_ollama(
    prompt: str,
    system_prompt: str = "",
    model: str = "",
    target_url: str = "",
    temperature: float = 0.1,
    max_tokens: int | None = None,
    stop: list[str] | None = None,
    num_ctx: int | None = None,
    response_format: str | None = None,
) -> str:
    """Generate using an Ollama /api/generate endpoint."""
    options: dict[str, Any] = {"temperature": temperature}
    if max_tokens is not None:
        options["num_predict"] = max_tokens
    if stop:
        options["stop"] = stop
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

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            f"{target_url}/api/generate",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()["response"]


async def generate(
    prompt: str,
    system_prompt: str = "",
    model: str | None = None,
    ollama_url: str | None = None,
    temperature: float = 0.1,
    max_tokens: int | None = None,
    min_tokens: int | None = None,
    stop: list[str] | None = None,
    num_ctx: int | None = None,
    response_format: str | None = None,
) -> str:
    """Generate text completion from Ollama or a vLLM/OpenAI-compatible target.

    ``response_format="json"`` forces constrained JSON decoding so the model can
    only emit a syntactically valid JSON value — use it for any call whose
    response is parsed as JSON.
    """
    model = model or settings.reasoning_model
    target_url = (ollama_url or settings.ollama_url).rstrip("/")

    if _is_openai_target(target_url):
        # vLLM/OpenAI-compatible targets have no per-request context-window
        # override -- max_model_len is fixed by the server at startup, unlike
        # Ollama's num_ctx -- so num_ctx has no meaningful translation here
        # and is intentionally left unused for this path.
        #
        # A prior version of this function derived an explicit max_tokens
        # from num_ctx (halved and capped at 4096) to try to guarantee
        # reasoning models a completion budget. That is unsafe: ai-server has
        # no tokenizer, so it cannot know the actual prompt token count, and
        # vLLM rejects prompt_tokens + max_tokens > max_model_len with a 400
        # rather than truncating -- turning a large prompt's soft failure
        # (empty content, 0 widgets) into a hard 500 on every call. Passing
        # max_tokens through unset (the caller's default) lets vLLM size the
        # completion itself from the real prompt it just tokenized, which is
        # strictly safer than any client-side guess.
        return await _generate_openai(
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
            target_url=target_url,
            temperature=temperature,
            max_tokens=max_tokens,
            min_tokens=min_tokens,
            stop=stop,
            response_format=response_format,
        )

    return await _generate_ollama(
        prompt=prompt,
        system_prompt=system_prompt,
        model=model,
        target_url=target_url,
        temperature=temperature,
        max_tokens=max_tokens,
        stop=stop,
        num_ctx=num_ctx,
        response_format=response_format,
    )


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
    "12. Wrap every table and column identifier in double quotes to avoid "
    "Teiid reserved-word errors. Quote table names (FROM \"it_backup_jobs_CSV\") "
    "and every column reference (SELECT \"Status\", COUNT(*) FROM "
    "\"it_backup_jobs_CSV\" GROUP BY \"Status\"). Do NOT quote SQL keywords, "
    "function names, string literals, or aliases.\n"
    "13. For any WHERE clause comparing a string/text column to a literal value, "
    "ALWAYS use case-insensitive comparison: LOWER(\"ColumnName\") = LOWER('value'). "
    "Example: WHERE LOWER(\"Status\") = LOWER('failed'). Never write "
    "WHERE \"Status\" = 'failed' or WHERE \"Status\" = 'Failed'. This ensures "
    "natural-language filters match stored values regardless of capitalization.\n"
    "14. Never place an aggregate function (SUM, AVG, COUNT, MIN, MAX) in the "
    "GROUP BY clause. GROUP BY must contain ONLY the non-aggregated SELECT "
    "expressions, repeated verbatim.\n"
    "15. Never wrap PARSETIMESTAMP, PARSEDATE, FORMATDATE, or CAST around an "
    "expression that is already a date/timestamp (e.g. do NOT write "
    "PARSETIMESTAMP(PARSETIMESTAMP(\"Month\", 'yyyy-MM-dd'), 'M/d/yyyy')). "
    "Use the exact same date expression in SELECT, GROUP BY, and ORDER BY.\n"
    "16. Generate a single SELECT statement. Do NOT use UNION or UNION ALL "
    "unless the user explicitly asks to combine rows from two different tables. "
    "Never place ORDER BY inside a UNION branch; in Teiid ORDER BY is only "
    "valid at the very end of the entire query.\n"
    "17. If the user asks for a specific display format (currency/dollars, "
    "percentage, etc.) for a value, alias that column so its name reflects "
    "the requested format instead of adding SQL formatting functions — e.g. "
    "alias a dollar amount as ...USD or TotalRevenueUSD, alias a percentage "
    "as ...Percent or DefectRatePercent. The alias is used downstream to "
    "render the value correctly.\n"
    "18. Translate plain-language grouping phrases directly into GROUP BY: "
    "'group by X', 'broken down by X', 'per X', and 'for each X' all mean "
    "GROUP BY <X's column>, added to both SELECT and GROUP BY (see rule 9).\n"
    "19. Translate plain-language value-mapping phrases into a CASE WHEN "
    "expression: 'if <column> is/contains/equals <text> then <label>' "
    "becomes CASE WHEN LOWER(\"Column\") = LOWER('text') THEN 'label' ... "
    "ELSE ... END (case-insensitive per rule 13). Alias the CASE expression "
    "with a descriptive name.\n"
)

# Default: no cross-table JOINs (many tables share column names, causing
# ambiguity errors). Swapped for _TEIID_JOIN_EXCEPTION_RULE only when the
# caller supplies verified relationship_hint_lines (from platform-api's
# _relationship_hints, rendered by ai_plan_prompt._build_relationship_hint_lines).
# Mirrors ai_shared.py's dashboard-pipeline single-table/join-exception
# pattern, defined locally here since this service module must not import
# the router layer.
_TEIID_NO_JOIN_RULE = (
    "JOIN POLICY: Query a SINGLE table per analysis. Do NOT write JOINs. "
    '(Many tables share column names like "SupplierID" — joining causes '
    "ambiguity errors. One table per query avoids this entirely.)\n"
)

_TEIID_JOIN_EXCEPTION_RULE = (
    "JOIN POLICY: Query a SINGLE table per analysis, with ONE exception: a "
    "cross-table analysis may JOIN exactly the two tables of a pair listed "
    "in RELATIONSHIP EVIDENCE below, on exactly the listed keys. Alias both "
    'tables and table-qualify EVERY column reference (e.g. i."DefectQty", '
    's."Region") — many tables share column names and an unqualified column '
    "in a join is an ambiguity error. Reference ONLY columns listed under "
    "the table(s) you actually use.\n"
)

# Used by repair_sql when the failing query already joins two tables (a
# caller-verified cross-table analysis): keep the repair from "fixing" the
# join away.
_TEIID_FIX_JOIN_RULE = (
    "This query intentionally JOINs two tables (a verified relationship). "
    "KEEP the same two tables and the same join keys — do NOT rewrite it as "
    "a single-table query and do NOT add more tables. Alias both tables and "
    "table-qualify EVERY column reference to avoid ambiguity errors.\n"
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
    "- When a source below has a 'profile' line, it tells you the row count "
    "and, for the date column, its real range. Before applying a relative "
    "date filter ('last 30 days', 'this quarter', 'year over year'), check "
    "that range: if 'now' or the requested window falls outside it, or the "
    "range covers less time than the requested window, do NOT add a filter "
    "that would exclude all the rows the profile shows exist — query the "
    "data as it is instead of a filter guessed from wall-clock time.\n"
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
            profile_summary = getattr(entry, "profile_summary", None)
            if isinstance(entry, dict):
                columns = entry.get("columns")
                description = entry.get("description")
                kind = entry.get("kind")
                profile_summary = entry.get("profile_summary")
            col_str = ", ".join(columns or []) or "(columns unknown)"
            label = "saved query" if kind == "query" else "data source"
            desc = f" — {description}" if description else ""
            lines.append(f'- "{name}" [{label}]{desc}\n    columns: {col_str}')
            if profile_summary:
                lines.append(f"    profile: {profile_summary}")
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
    relationship_hint_lines: str = "",
    model: str | None = None,
    ollama_url: str | None = None,
) -> str:
    """Generate SQL using the code-specialized model with semantic discovery."""
    catalog = _catalog_text(allowed_tables, source_catalog)
    hint = _resolver_hint(preferred_sources, relevant_columns)
    join_rule = (
        _TEIID_JOIN_EXCEPTION_RULE if relationship_hint_lines else _TEIID_NO_JOIN_RULE
    )
    system_prompt = (
        "You are Tablescope AI.\n"
        "You may only answer using the provided context package.\n"
        "Do not request or infer access to data outside the provided context.\n"
        "Generate SQL only using the allowed sources and columns listed below.\n"
        "Do not use SELECT *.\n"
        "Do not generate INSERT, UPDATE, DELETE, DROP, or any write operations.\n"
        "Return ONLY the final SQL query. Do not explain, reason, or preface. "
        "Do not wrap the SQL in markdown unless the user explicitly asks for it. "
        "No chain-of-thought, no commentary, no 'Here is the query' introductions.\n"
        "When a Knowledge Graph context block is present, prioritize SQL that "
        "measures or validates its risks, opportunities, gaps, warnings, "
        "recommended/measured KPIs, documented processes, and entity "
        "relationships. If the graph names a recommended KPI but no datasource "
        "or query can measure it, do NOT invent SQL. Reference Library "
        "documents are guidance only — never use a reference document as a SQL "
        "data source.\n\n"
        f"{_SEMANTIC_RULES}\n"
        f"{_TEIID_RULES}"
        f"{join_rule}\n"
        f"{hint}"
        f"{catalog}\n"
        f"{relationship_hint_lines}\n\n"
        f"Context:\n{context}"
    )

    return await generate(
        prompt=prompt,
        system_prompt=system_prompt,
        model=model or settings.sql_model,
        ollama_url=ollama_url,
        temperature=0.0,
        # Confirmed live: a reasoning model can spend the whole 1024-token
        # budget on its reasoning trace before ever reaching the SQL answer
        # (finish_reason=length) -- but raising this to a bigger fixed value
        # would reintroduce the regression _generate_openai's own comment
        # and test_num_ctx_has_no_effect_on_vllm_targets already fixed once
        # (project 44: an explicit max_tokens reservation overflowed
        # max_model_len and turned a soft failure into a hard 400, since
        # ai-server has no tokenizer and cannot verify a fixed number is
        # safe against every prompt's real token count -- a SQL-generation
        # prompt's catalog/schema/relationship hints can get large). Leave
        # it unset on vLLM/OpenAI-compatible targets so vLLM sizes the
        # completion itself from the prompt it just tokenized; Ollama has no
        # equivalent per-request sizing, so it keeps an explicit cap.
        max_tokens=None if _is_openai_target(
            (ollama_url or settings.ollama_url).rstrip("/")
        ) else 1024,
        min_tokens=_SQL_MIN_TOKENS,
        stop=[";"],
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
    relationship_hint_lines: str = "",
    model: str | None = None,
    ollama_url: str | None = None,
) -> str:
    """Ask the model to fix SQL that failed validation, preserving intent."""
    catalog = _catalog_text(allowed_tables, source_catalog)
    hint = _resolver_hint(preferred_sources, relevant_columns)
    # If the failing SQL already joins tables, a verified relationship exists
    # (the caller only passes hints when it found one) — keep the join intact
    # instead of "fixing" it back to single-table. Otherwise reaffirm the
    # default no-join policy so repair can't introduce an ungrounded join.
    join_rule = (
        _TEIID_FIX_JOIN_RULE if relationship_hint_lines else _TEIID_NO_JOIN_RULE
    )
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
        f"{_TEIID_RULES}"
        f"{join_rule}\n"
        f"{hint}"
        f"{catalog}\n"
        f"{relationship_hint_lines}\n\n"
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
        model=model or settings.sql_model,
        ollama_url=ollama_url,
        temperature=0.0,
        # See generate_sql's matching comment: unset on vLLM/OpenAI-compatible
        # targets to avoid overflowing max_model_len, capped on Ollama.
        max_tokens=None if _is_openai_target(
            (ollama_url or settings.ollama_url).rstrip("/")
        ) else 1024,
        min_tokens=_SQL_MIN_TOKENS,
        stop=[";"],
    )


async def generate_embeddings(texts: list[str], *, model: str | None = None) -> list[list[float]]:
    """Generate embeddings using the configured or requested model."""
    embeddings = []
    selected_model = model or settings.embedding_model
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for text in texts:
            resp = await client.post(
                f"{settings.ollama_url}/api/embeddings",
                json={
                    "model": selected_model,
                    "prompt": text,
                },
            )
            resp.raise_for_status()
            embeddings.append(resp.json()["embedding"])
    return embeddings


async def generate_embeddings_with_model(
    texts: list[str], *, model: str
) -> list[list[float]]:
    """Generate embeddings with an explicit model name."""
    return await generate_embeddings(texts, model=model)


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
