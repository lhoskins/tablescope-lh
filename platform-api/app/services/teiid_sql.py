"""Teiid-specific SQL normalizations for generated query previews.

The AI planner emits SQL that is closer to PostgreSQL/ANSI than to Teiid. The
most common failure mode is timestamp/date parsing: `to_timestamp(...)`,
`CAST('literal' AS timestamp)`, and `CAST("col" AS timestamp)` against a
string column all fail when the literal/column does not match Teiid's default
cast format. This module rewrites those expressions to Teiid's
`PARSETIMESTAMP` / `PARSEDATE` with the right SimpleDateFormat mask.

It is intentionally not a full SQL transpiler — only the timestamp/date
patterns that the preview execution path actually sees are handled here.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.file_source_meta import FileSourceMeta

# ISO/SimpleDateFormat letters are case sensitive.
# PostgreSQL-style templates are mapped onto Java SimpleDateFormat masks.
_PSQL_MASK_TOKENS = {
    "YYYY": "yyyy",
    "yyyy": "yyyy",
    "YY": "yy",
    "MM": "MM",
    "DD": "dd",
    "HH24": "HH",
    "HH12": "hh",
    "HH": "HH",
    "MI": "mm",
    "SS": "ss",
    "MS": "SSS",
    "US": "SSS",
    "TZ": "z",
    "OF": "XXX",
    "AM": "a",
    "PM": "a",
}


_PSQL_MASK_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _PSQL_MASK_TOKENS) + r")\b",
    re.IGNORECASE,
)


def _translate_psql_mask(mask: str) -> str:
    """Convert a PostgreSQL-style date format string to a Teiid/SimpleDateFormat mask."""
    def repl(m: re.Match[str]) -> str:
        return _PSQL_MASK_TOKENS.get(m.group(1).upper(), m.group(1))

    return _PSQL_MASK_RE.sub(repl, mask)


# Common timestamp/date literal patterns and the Teiid masks that parse them.
_LITERAL_MASKS: list[tuple[re.Pattern[str], str]] = [
    # ISO 8601 with timezone
    (
        re.compile(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:Z|[+-]\d{2}:?\d{2})$"
        ),
        "yyyy-MM-dd''T''HH:mm:ss",
    ),
    # ISO 8601 without timezone
    (
        re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?$")
        ,
        "yyyy-MM-dd''T''HH:mm:ss",
    ),
    # ANSI datetime
    (
        re.compile(
            r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d{1,3})?$"
        ),
        "yyyy-MM-dd HH:mm:ss",
    ),
    # Date only (ISO)
    (re.compile(r"^\d{4}-\d{2}-\d{2}$"), "yyyy-MM-dd"),
    # US slash date
    (re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$"), "M/d/yyyy"),
    (re.compile(r"^\d{1,2}/\d{1,2}/\d{2}$"), "M/d/yy"),
]


def _mask_for_literal(value: str) -> str | None:
    """Infer a Teiid PARSETIMESTAMP/PARSEDATE mask for a string literal."""
    text = value.strip()
    for pat, mask in _LITERAL_MASKS:
        if pat.match(text):
            return mask
    return None


# A single-quoted SQL string, possibly containing '' escapes.
_STRING_RE = re.compile(r"'(?:[^']|'')*'")


def _extract_string(sql: str) -> str:
    """Return the text inside a single-quoted SQL string, unescaping '' -> '."""
    text = sql[1:-1].replace("''", "'")
    return text


# CAST('literal' AS date|timestamp)
_CAST_LITERAL_RE = re.compile(
    r"CAST\s*\(\s*(_LIT_)\s+AS\s+(date|timestamp)\s*\)",
    re.IGNORECASE,
)

# CAST("col" AS date|timestamp)
_CAST_COLUMN_RE = re.compile(
    r'CAST\s*\(\s*("(?:[^"]|"")*")\s+AS\s+(date|timestamp)\s*\)',
    re.IGNORECASE,
)

# to_timestamp('literal')  or  to_timestamp('literal', 'format')
_TO_TIMESTAMP_RE = re.compile(
    r"to_timestamp\s*\(\s*(_LIT_)(?:\s*,\s*(_LIT_))?\s*\)",
    re.IGNORECASE,
)

# to_date('literal', 'format')
_TO_DATE_RE = re.compile(
    r"to_date\s*\(\s*(_LIT_)(?:\s*,\s*(_LIT_))?\s*\)",
    re.IGNORECASE,
)


def _build_re(raw: str) -> re.Pattern[str]:
    """Insert the SQL string literal matcher into a regex template."""
    return re.compile(
        raw.replace("_LIT_", r"'(?:[^']|'')*'"),
        re.IGNORECASE,
    )


_CAST_LITERAL_RE = _build_re(r"CAST\s*\(\s*(_LIT_)\s+AS\s+(date|timestamp)\s*\)")
_TO_TIMESTAMP_RE = _build_re(
    r"to_timestamp\s*\(\s*(_LIT_)(?:\s*,\s*(_LIT_))?\s*\)"
)
_TO_DATE_RE = _build_re(
    r"to_date\s*\(\s*(_LIT_)(?:\s*,\s*(_LIT_))?\s*\)"
)


def _cleanup_stray_string_literals(sql: str) -> str:
    """Remove LLM hallucinated string-literal fragments after function calls.

    Models sometimes emit malformed expressions like
    ``PARSETIMESTAMP("col", 'M/d/yyyy')'col', 'M/d/yyyy')`` where a stray
    quoted literal pair is appended. This pattern never occurs in valid SQL,
    so we safely collapse it back to the intended closing parenthesis.
    """
    if not sql:
        return sql
    # A closing `)` followed immediately by 'x', 'y') is malformed; keep the
    # original `)` and drop the stray pair.
    return re.sub(
        r"(\))\s*'(?:[^']|'')*'\s*,\s*'(?:[^']|'')*'\s*\)",
        r"\1",
        sql,
    )


_DATE_TYPES = frozenset({"date", "datetime", "timestamp"})


def _mask_or_cast_for_column(
    raw_col: str,
    current_mask: str,
    *,
    column_samples: dict[str, str],
    lower_types: dict[str, str],
    is_date: bool,
) -> str:
    """Return the best Teiid expression for parsing/formatting a column.

    For ``date``/``datetime``/``timestamp`` typed columns we prefer a plain
    ``CAST`` when we have no sample. When a sample is available we infer the
    correct SimpleDateFormat mask and keep ``PARSETIMESTAMP`` / ``PARSEDATE``
    so slash-formatted string columns still parse correctly.
    """
    col = raw_col[1:-1].replace('""', '"')
    col_type = lower_types.get(col.lower(), "")
    sample = column_samples.get(col)
    if sample:
        mask = date_mask_for_value(sample)
        if mask is not None:
            func = "PARSEDATE" if is_date else "PARSETIMESTAMP"
            return f"{func}({raw_col}, '{mask}')"
    if col_type in _DATE_TYPES:
        cast_type = "date" if is_date else "timestamp"
        return f"CAST({raw_col} AS {cast_type})"
    # We cannot determine the right mask; leave the original call alone.
    return f"{'PARSEDATE' if is_date else 'PARSETIMESTAMP'}({raw_col}, {current_mask})"


def _normalize_existing_parse_calls(
    sql: str,
    column_samples: dict[str, str],
    lower_types: dict[str, str],
) -> str:
    """Fix ``PARSETIMESTAMP("col", 'mask')`` / ``PARSEDATE("col", 'mask')``

    The model frequently emits these with a wrong mask (e.g. ``M/d/yyyy`` on
    an ISO date column) or on a column that is already typed as a date. We
    rewrite the call to a ``CAST`` or to the correct mask inferred from a
    sample value.
    """

    def _repl_parse(m: re.Match[str]) -> str:
        raw_col = m.group(1)
        raw_mask = m.group(2)
        return _mask_or_cast_for_column(
            raw_col,
            raw_mask,
            column_samples=column_samples,
            lower_types=lower_types,
            is_date=False,
        )

    def _repl_date(m: re.Match[str]) -> str:
        raw_col = m.group(1)
        raw_mask = m.group(2)
        return _mask_or_cast_for_column(
            raw_col,
            raw_mask,
            column_samples=column_samples,
            lower_types=lower_types,
            is_date=True,
        )

    sql = re.sub(
        r"PARSETIMESTAMP\s*\(\s*(\"(?:[^\"]|\"\")*\")\s*,\s*('(?:[^']|'')*')\s*\)",
        _repl_parse,
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(
        r"PARSEDATE\s*\(\s*(\"(?:[^\"]|\"\")*\")\s*,\s*('(?:[^']|'')*')\s*\)",
        _repl_date,
        sql,
        flags=re.IGNORECASE,
    )
    return sql


def normalize_teiid_timestamps(
    sql: str,
    *,
    column_samples: dict[str, str] | None = None,
    column_types: dict[str, str] | None = None,
) -> str:
    """Rewrite timestamp/date expressions to Teiid-parseable forms.

    Handles:
    - PostgreSQL ``to_timestamp('literal')`` and ``to_date('literal')``,
      with or without an explicit format string.
    - ``CAST('literal' AS timestamp|date)`` where the literal matches a known
      ISO/slash pattern.
    - ``CAST("col" AS timestamp|date)`` when a sample value is supplied for
      the column so a mask can be inferred.
    - ``PARSETIMESTAMP("col", 'mask')`` / ``PARSEDATE("col", 'mask')`` when
      the column is typed as a date or a sample reveals the real format.

    Unknown column casts are left as-is; the query will fail in the normal
    Teiid execution path and can be repaired by the existing AI SQL fix loop.
    """
    column_samples = column_samples or {}
    lower_types = {k.lower(): v.lower() for k, v in (column_types or {}).items()}

    # Clean duplicated string-literal fragments before parsing functions.
    sql = _cleanup_stray_string_literals(sql)

    def _replace_to_timestamp(m: re.Match[str]) -> str:
        value = _extract_string(m.group(1))
        if m.group(2):
            mask: str | None = _translate_psql_mask(_extract_string(m.group(2)))
        else:
            mask = _mask_for_literal(value)
        if mask is None:
            return m.group(0)
        return f"PARSETIMESTAMP({m.group(1)}, '{mask}')"

    def _replace_to_date(m: re.Match[str]) -> str:
        value = _extract_string(m.group(1))
        if m.group(2):
            mask: str | None = _translate_psql_mask(_extract_string(m.group(2)))
        else:
            mask = _mask_for_literal(value)
        if mask is None:
            return m.group(0)
        return f"PARSEDATE({m.group(1)}, '{mask}')"

    def _replace_cast_literal(m: re.Match[str]) -> str:
        raw_value = m.group(1)
        value = _extract_string(raw_value)
        type_ = m.group(2).lower()
        mask = _mask_for_literal(value)
        if mask is None:
            return m.group(0)
        if type_ == "date":
            return f"PARSEDATE({raw_value}, '{mask}')"
        return f"PARSETIMESTAMP({raw_value}, '{mask}')"

    def _replace_cast_column(m: re.Match[str]) -> str:
        raw_col = m.group(1)
        col = raw_col[1:-1].replace('""', '"')
        sample = column_samples.get(col)
        if not sample:
            return m.group(0)
        type_ = m.group(2).lower()
        mask = _mask_for_literal(sample)
        if mask is None:
            return m.group(0)
        if type_ == "date":
            return f"PARSEDATE({raw_col}, '{mask}')"
        return f"PARSETIMESTAMP({raw_col}, '{mask}')"

    sql = _TO_TIMESTAMP_RE.sub(_replace_to_timestamp, sql)
    sql = _TO_DATE_RE.sub(_replace_to_date, sql)
    sql = _CAST_LITERAL_RE.sub(_replace_cast_literal, sql)
    sql = _CAST_COLUMN_RE.sub(_replace_cast_column, sql)
    sql = _normalize_existing_parse_calls(sql, column_samples, lower_types)
    return sql


# Slash-date detector (M/d/yyyy or M/d/yy) used for column masks.
_SLASH_DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/(\d{4}|\d{2})$")


def date_mask_for_value(value: str) -> str | None:
    """Return a Teiid mask for a known date/timestamp sample value."""
    text = value.strip()
    mask = _mask_for_literal(text)
    if mask is not None:
        return mask
    if _SLASH_DATE_RE.match(text):
        year = text.rsplit("/", 1)[-1]
        return "M/d/yyyy" if len(year) == 4 else "M/d/yy"
    return None


def date_masks_from_samples(
    samples_per_table: list[dict[str, str]],
) -> dict[str, str]:
    """Map columns to a Teiid parse mask from one example value per column.

    The result is keyed by column name; the first non-empty sample wins.
    """
    masks: dict[str, str] = {}
    for samples in samples_per_table:
        for col, val in samples.items():
            if col in masks or not val:
                continue
            text = val.strip()
            if not text:
                continue
            mask = date_mask_for_value(text)
            if mask:
                masks[col] = mask
    return masks


def normalize_date_casts(sql: str, date_masks: dict[str, str]) -> str:
    """Rewrite ``CAST("col" AS date|timestamp)`` and existing
    ``PARSETIMESTAMP("col", 'mask')`` calls to use the mask inferred from the
    column's sample value.

    This is the same helper used by the Business Insight analyst loop so the
    query-suggestion and datasource-execution paths behave consistently.
    """
    for col, mask in date_masks.items():
        pat = re.compile(
            r'CAST\(\s*"' + re.escape(col) + r'"\s+AS\s+(?:date|timestamp)\s*\)',
            re.IGNORECASE,
        )
        sql = pat.sub(f'PARSETIMESTAMP("{col}", \'{mask}\')', sql)

    # The small model often emits PARSETIMESTAMP with a hard-coded M/d/yyyy mask
    # from the prompt examples; override it with the measured mask when known.
    def _col_from_arg(arg: str) -> str:
        return arg.split(".")[-1].strip().strip('"').replace('""', '"')

    def _replace_parse(m: re.Match[str]) -> str:
        arg = m.group(1).strip()
        col = _col_from_arg(arg)
        mask = date_masks.get(col)
        if not mask:
            return m.group(0)
        func = m.group(0).split("(", 1)[0]
        return f"{func}({arg}, '{mask}')"

    sql = re.sub(
        r"PARSETIMESTAMP\s*\(\s*([^,]+?)\s*,\s*'(?:[^']|'')*'\s*\)",
        _replace_parse,
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(
        r"PARSEDATE\s*\(\s*([^,]+?)\s*,\s*'(?:[^']|'')*'\s*\)",
        _replace_parse,
        sql,
        flags=re.IGNORECASE,
    )
    return sql


async def project_table_schema(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
) -> list[dict[str, Any]]:
    """Build the exact per-source column schema for SQL repair/normalization.

    Shape: ``[{"table": view, "columns": [{"name", "type"}]}]`` — the same
    contract the AI server's ``fix-sql`` endpoint consumes.
    """
    rows = (
        await session.scalars(
            select(FileSourceMeta).where(
                FileSourceMeta.project_id == project_id,
                FileSourceMeta.tenant_id == tenant_id,
                FileSourceMeta.archived.is_(False),
            )
        )
    ).all()
    schema: list[dict[str, Any]] = []
    for ds in rows:
        columns = [
            {"name": str(c.get("name")), "type": str(c.get("type") or "")}
            for c in (ds.column_types or [])
            if isinstance(c, dict) and c.get("name")
        ]
        schema.append({"table": ds.view_name, "columns": columns})
    return schema


def _split_top_level(text: str, delimiter: str = ",") -> list[str]:
    """Split ``text`` by ``delimiter`` respecting nested parentheses and strings."""
    parts: list[str] = []
    current = ""
    depth = 0
    in_str = False
    quote = ""
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if not in_str and ch in ("'", '"'):
            in_str = True
            quote = ch
        elif in_str:
            # Handle escaped quotes inside SQL string literals.
            escapes = 0
            j = i - 1
            while j >= 0 and text[j] == "\\":
                escapes += 1
                j -= 1
            if ch == quote and escapes % 2 == 0:
                in_str = False
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == delimiter and depth == 0:
            parts.append(current)
            current = ""
            i += 1
            continue
        current += ch
        i += 1
    parts.append(current)
    return parts


def _fix_string_literal_columns(sql: str, names: set[str]) -> str:
    """Replace string literals that are actually column names inside functions.

    The AI sometimes emits ``CAST('LaborCostUSD' AS double)`` or
    ``PARSETIMESTAMP('Month', 'M/d/yyyy')`` because it mis-quotes the column.
    This rewrites those string-literal placeholders to double-quoted
    identifiers when the literal matches a real column/table name in the
    schema, but only inside function argument positions where a column/expression
    is expected (not in ``WHERE Status = 'At Risk'`` comparisons).
    """
    if not sql or not names:
        return sql

    lower_names = {n.lower(): n for n in names}
    func_positions: dict[str, list[int]] = {
        "cast": [0],
        "parsetimestamp": [0],
        "parsedate": [0],
        "formatdate": [0],
        "formattimestamp": [0],
        "sum": [0],
        "avg": [0],
        "min": [0],
        "max": [0],
        "count": [0],
        "timestampdiff": [1, 2],
    }
    funcs = "|".join(re.escape(f) for f in func_positions)
    func_pattern = re.compile(rf"\b({funcs})\s*\(", re.IGNORECASE)

    def _quoted_if_name(text: str) -> str:
        stripped = text.strip()
        if (
            len(stripped) >= 2
            and stripped.startswith("'")
            and stripped.endswith("'")
        ):
            inner = stripped[1:-1].replace("''", "'")
            if inner.lower() in lower_names:
                return f'"{lower_names[inner.lower()]}"'
        return text

    def _process_segment(text: str) -> str:
        out: list[str] = []
        i = 0
        n = len(text)
        while i < n:
            m = func_pattern.search(text, i)
            if not m:
                out.append(text[i:])
                break
            out.append(text[i : m.start()])
            func = m.group(1).lower()
            # Find the matching closing parenthesis, respecting nested
            # parentheses and string literals.
            depth = 1
            j = m.end()
            in_str = False
            quote = ""
            while j < n and depth > 0:
                ch = text[j]
                if in_str:
                    if ch == quote and (j == 0 or text[j - 1] != "\\"):
                        in_str = False
                else:
                    if ch in ("'", '"'):
                        in_str = True
                        quote = ch
                    elif ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                j += 1
            if depth != 0:
                out.append(text[m.start() : j])
                i = j
                continue
            args_str = _process_segment(text[m.end() : j - 1])
            args = _split_top_level(args_str)
            allowed = func_positions[func]
            new_args: list[str] = []
            for idx, arg in enumerate(args):
                if idx in allowed:
                    if func == "cast":
                        # The first argument of CAST is the expression, followed
                        # by ``AS <type>``. Only rewrite the expression part.
                        as_match = re.search(r"\bAS\b", arg, flags=re.IGNORECASE)
                        if as_match:
                            expr = arg[: as_match.start()].strip()
                            suffix = arg[as_match.start() :]
                            new_expr = _quoted_if_name(expr)
                            if new_expr is not expr:
                                arg = f"{new_expr} {suffix.strip()}"
                                arg = _quoted_if_name(arg)
                        else:
                            arg = _quoted_if_name(arg)
                    else:
                        arg = _quoted_if_name(arg)
                new_args.append(arg)
            out.append(f"{m.group(1)}({', '.join(new_args)})")
            i = j
        return "".join(out)

    return _process_segment(sql)


def normalize_teiid_string_filters(
    sql: str,
    table_schema: list[dict[str, Any]],
) -> str:
    """Wrap string-column equality filters in LOWER() so natural-language values
    match stored values regardless of capitalization.

    Only rewrites comparisons where the column is known to be a string/text type
    in the project schema and the literal is a single-quoted string.
    """
    if not sql or not table_schema:
        return sql

    string_types = {"string", "text", "varchar", "char", "clob", "nstring"}
    string_cols: set[str] = set()
    for entry in table_schema:
        for col in entry.get("columns", []) or []:
            ctype = ""
            cname = ""
            if isinstance(col, dict):
                ctype = str(col.get("type") or "").lower()
                cname = str(col.get("name") or "").strip().strip('"')
            elif isinstance(col, str):
                cname = col.strip().strip('"')
            if cname and (ctype in string_types or not ctype):
                string_cols.add(cname.lower())
    if not string_cols:
        return sql

    col_token = r'"(?:[^"]|"")*"|[A-Za-z_][A-Za-z0-9_]*'
    lit_token = r"'(?:[^']|'')*'"

    def col_name(token: str) -> str | None:
        name = token.strip().strip('"')
        if name.lower() in string_cols:
            return token
        return None

    def _quoted_col(token: str) -> str:
        name = token.strip().strip('"')
        return f'"{name}"'

    # Equality / inequality: "Column" = 'value' or Column = 'value'
    eq_re = re.compile(
        rf"(?<![\w\"'])({col_token})\s*(=|!=|<>|<=|>=)\s*({lit_token})",
        re.IGNORECASE,
    )

    def _eq_replace(m: re.Match[str]) -> str:
        col = m.group(1)
        op = m.group(2)
        val = m.group(3)
        if not col_name(col):
            return m.group(0)
        # Only rewrite equality/inequality operators, not range operators.
        if op in ("<=", ">="):
            return m.group(0)
        return f"LOWER({_quoted_col(col)}) {op} LOWER({val})"

    sql = eq_re.sub(_eq_replace, sql)

    # IN list: "Column" IN ('a','b','c')
    in_re = re.compile(
        rf"(?<![\w\"'])({col_token})\s+IN\s*\(((?:\s*{lit_token}\s*,?)+)\)",
        re.IGNORECASE,
    )

    def _in_replace(m: re.Match[str]) -> str:
        col = m.group(1)
        values_block = m.group(2)
        if not col_name(col):
            return m.group(0)
        lit_re = re.compile(lit_token)
        new_values = lit_re.sub(r"LOWER(\g<0>)", values_block)
        return f"LOWER({_quoted_col(col)}) IN ({new_values})"

    return in_re.sub(_in_replace, sql)


# Teiid reserved words that the model often uses as aliases.  They must be
# quoted when emitted as column/output aliases (``AS Year``, ``AS Quarter``).
_TEIID_RESERVED_ALIASES = {
    "YEAR", "MONTH", "DAY", "HOUR", "MINUTE", "SECOND", "QUARTER", "WEEK",
    "YEAROFERA", "MONTHOFYEAR", "WEEKOFYEAR", "DAYOFWEEK", "DAYOFMONTH",
    "DAYOFYEAR", "EPOCH", "MILLISECOND", "NANOSECOND",
}


def normalize_teiid_identifiers(
    sql: str,
    table_schema: list[dict[str, Any]],
) -> str:
    """Quote bare table/column identifiers that conflict with Teiid reserved words.

    Uses the project schema so only real table/column names are quoted.  Tokens
    immediately after an ``AS`` alias clause are left unquoted unless the alias
    is a Teiid reserved word, and tokens inside string literals are ignored.
    """
    if not sql or not table_schema:
        return sql

    names: set[str] = set()
    for entry in table_schema:
        table = entry.get("table")
        if table:
            names.add(str(table))
        for col in entry.get("columns", []):
            if isinstance(col, dict):
                cname = col.get("name")
            else:
                cname = col
            if cname:
                names.add(str(cname))
    if not names:
        return sql

    # Fix the common AI mistake of using a single-quoted string literal where a
    # column identifier was intended (e.g. CAST('Month' AS date)).
    sql = _fix_string_literal_columns(sql, names)

    # Longest first so multi-word names match before their substrings.
    sorted_names = sorted(names, key=len, reverse=True)
    pattern = re.compile(
        r'(?<![\w"])(' + "|".join(re.escape(n) for n in sorted_names) + r')(?![\w("])',
        re.IGNORECASE,
    )

    def _escaped(text: str, pos: int) -> bool:
        escapes = 0
        i = pos - 1
        while i >= 0 and text[i] == "\\":
            escapes += 1
            i -= 1
        return escapes % 2 == 1

    def _in_string(text: str, end: int) -> bool:
        in_str = False
        quote = ""
        i = 0
        while i < end:
            ch = text[i]
            if not in_str:
                if ch in ("'", '"'):
                    in_str = True
                    quote = ch
            else:
                if ch == quote and not _escaped(text, i):
                    in_str = False
            i += 1
        return in_str

    out: list[str] = []
    prev = 0
    for m in pattern.finditer(sql):
        start = m.start()
        if _in_string(sql, start):
            # Append the segment up to and including this match unchanged.
            out.append(sql[prev : m.end()])
            prev = m.end()
            continue
        out.append(sql[prev:start])
        token = m.group(1)
        prefix = sql[:start]
        if re.search(r"\bAS\s+$", prefix, re.IGNORECASE) and token.upper() not in _TEIID_RESERVED_ALIASES:
            out.append(token)
        else:
            out.append(f'"{token}"')
        prev = m.end()
    out.append(sql[prev:])
    sql = "".join(out)

    # Final pass: quote any remaining reserved-word aliases and their uses in
    # GROUP BY / ORDER BY.  The schema-name pass above skips tokens not present
    # in the project schema, so aliases like ``AS Year`` or ``GROUP BY Year``
    # (common model output) must be handled explicitly.  Skip tokens that are
    # actually function calls (``GROUP BY QUARTER(...)``) so we do not split the
    # expression.
    alias_re = re.compile(
        r'\b(AS|GROUP\s+BY|ORDER\s+BY)\s+([A-Za-z_]\w*)(?!\s*\()',
        re.IGNORECASE,
    )

    def _quote_alias_ref(m: re.Match[str]) -> str:
        token = m.group(2)
        if token.upper() in _TEIID_RESERVED_ALIASES:
            return f'{m.group(1)} "{token}"'
        return m.group(0)

    return alias_re.sub(_quote_alias_ref, sql)
