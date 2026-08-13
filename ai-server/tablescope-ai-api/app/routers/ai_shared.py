"""Helpers shared by the AI feature routers.

SQL cleanup/extraction, conversation-history formatting, LLM JSON
parsing and the Teiid SQL rule blocks used across several endpoints."""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


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
        # Support both quoted and unquoted aliases: ``AS Month`` and ``AS "Month"``.
        as_match = re.match(
            r'(.+?)\s+AS\s+["\[]?(\w+)["\]]?\s*$', part, re.IGNORECASE
        )
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
            # Replace the alias whether it is bare or double-quoted/bracketed.
            body = re.sub(
                rf'(?:"{re.escape(alias_upper)}"|\[{re.escape(alias_upper)}\]|\b{re.escape(alias_upper)}\b)',
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


def _infer_chart_columns(sql: str) -> tuple[str | None, str | None, str | None]:
    """Infer label, value, and second value column names from SELECT aliases.

    The first non-aggregate alias is the label (usually ``Period``); the first
    one or two aggregate aliases are the value columns.  ``dual_line`` and
    ``scatter`` require two aggregate measures.
    """
    select_match = re.search(
        r"SELECT\s+(.*?)\s+FROM\s", sql, re.IGNORECASE | re.DOTALL
    )
    if not select_match:
        return None, None, None
    select_body = select_match.group(1)
    # Split on top-level commas, respecting nested parentheses.
    depth = 0
    parts: list[str] = []
    current: list[str] = []
    for ch in select_body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(ch)
    parts.append("".join(current).strip())

    agg_re = re.compile(r"\b(?:AVG|SUM|COUNT|MIN|MAX)\s*\(", re.IGNORECASE)
    label_col: str | None = None
    value_cols: list[str] = []
    for part in parts:
        as_match = re.search(r"\bAS\s+(\w+)\s*$", part, re.IGNORECASE)
        if not as_match:
            continue
        alias = as_match.group(1).strip()
        if agg_re.search(part):
            value_cols.append(alias)
        elif label_col is None:
            label_col = alias
    return label_col, (
        value_cols[0] if value_cols else None
    ), (value_cols[1] if len(value_cols) > 1 else None)


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
    "NEVER show your chain-of-thought, reasoning, or internal planning. "
    "Output only the final answer. Do not preface with phrases like 'Here is', "
    "'I think', 'Based on the context', or 'The answer is'.\n"
    "\n"
    "Decide how to respond based on the question:\n"
    "- If the user asks about an uploaded document, a concept, a policy, a "
    "summary, or anything explanatory, answer in clear natural language grounded "
    "in the document context. Reference the relevant document by name and quote "
    "or paraphrase the supporting passage.\n"
    "- If the user asks for data, metrics, or records from the project's tables, "
    "generate a single read-only SQL query using only the allowed tables and "
    "columns. Do not use SELECT *. Never generate INSERT, UPDATE, DELETE, DROP, "
    "or any write operation. Output only the SQL.\n"
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


_TEIID_RULES_HEADER = (
    "This database uses Teiid (not MySQL/PostgreSQL). Text-backed (CSV/file) "
    "columns are stored as STRINGS no matter what logical type is shown.\n"
)

# Default table rule: strictly one table per query. Used verbatim whenever no
# relationship evidence is in play (dashboard suggestion, scope analysis, and
# any plan request without hints), so single-table behaviour never changes.
_TEIID_SINGLE_TABLE_RULE = (
    "- Query a SINGLE table per analysis. Do NOT write JOINs. (Many tables "
    'share column names like "SupplierID" — joining causes ambiguity errors. '
    "One table per query avoids this entirely.)\n"
    "- Reference ONLY columns listed under the table you select FROM; never "
    "invent columns and never borrow a column from another table.\n"
)

# Swapped in for the rule above ONLY when the plan prompt carries a
# RELATIONSHIP EVIDENCE block. Without this, the unconditional "Do NOT write
# JOINs" sits later in the prompt than the cross-table mandate and suppresses
# the very joins the mandate asks for.
_TEIID_JOIN_EXCEPTION_RULE = (
    "- Query a SINGLE table per analysis, with ONE exception: a cross-table "
    "analysis may JOIN exactly the two tables of a pair listed in "
    "RELATIONSHIP EVIDENCE, on exactly the listed keys. Alias both tables "
    'and table-qualify EVERY column reference (e.g. i."DefectQty", '
    's."Region") — many tables share column names and an unqualified column '
    "in a join is an ambiguity error.\n"
    "- Reference ONLY columns listed under the table(s) in your FROM/JOIN; "
    "never invent columns and never borrow a column from any other table.\n"
)

# Used by the SQL repair endpoint when the failing query already joins two
# tables (a planner-mandated cross-table analysis): the repair must keep the
# join rather than "fixing" it back to a single-table query.
_TEIID_FIX_JOIN_RULE = (
    "- This query intentionally JOINs two tables (a verified relationship). "
    "KEEP the same two tables and the same join keys — do NOT rewrite it as "
    "a single-table query and do NOT add more tables. Alias both tables and "
    "table-qualify EVERY column reference to avoid ambiguity errors.\n"
    "- Reference ONLY columns listed under the two joined tables; never "
    "invent columns.\n"
)

_TEIID_RULES_COMMON = (
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

_TEIID_SQL_RULES = (
    _TEIID_RULES_HEADER + _TEIID_SINGLE_TABLE_RULE + _TEIID_RULES_COMMON
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
