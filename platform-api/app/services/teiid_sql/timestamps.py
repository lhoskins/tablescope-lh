
from __future__ import annotations

import re

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


# SQL Server/MySQL-style DATEADD unit -> Teiid TIMESTAMPADD interval constant.
# Teiid has no DATEADD function at all (TEIID30068 "unknown form"), so a
# generated query using it fails outright regardless of the amount/expr --
# this is the single most common non-Teiid date function the model reaches
# for in production.
_DATEADD_UNIT_MAP = {
    "year": "SQL_TSI_YEAR",
    "years": "SQL_TSI_YEAR",
    "yy": "SQL_TSI_YEAR",
    "yyyy": "SQL_TSI_YEAR",
    "quarter": "SQL_TSI_QUARTER",
    "quarters": "SQL_TSI_QUARTER",
    "qq": "SQL_TSI_QUARTER",
    "q": "SQL_TSI_QUARTER",
    "month": "SQL_TSI_MONTH",
    "months": "SQL_TSI_MONTH",
    "mm": "SQL_TSI_MONTH",
    "week": "SQL_TSI_WEEK",
    "weeks": "SQL_TSI_WEEK",
    "wk": "SQL_TSI_WEEK",
    "ww": "SQL_TSI_WEEK",
    "day": "SQL_TSI_DAY",
    "days": "SQL_TSI_DAY",
    "dd": "SQL_TSI_DAY",
    "d": "SQL_TSI_DAY",
    "hour": "SQL_TSI_HOUR",
    "hours": "SQL_TSI_HOUR",
    "hh": "SQL_TSI_HOUR",
    "minute": "SQL_TSI_MINUTE",
    "minutes": "SQL_TSI_MINUTE",
    "mi": "SQL_TSI_MINUTE",
    "second": "SQL_TSI_SECOND",
    "seconds": "SQL_TSI_SECOND",
    "ss": "SQL_TSI_SECOND",
    "s": "SQL_TSI_SECOND",
}

_DATEADD_RE = re.compile(r"DATEADD\s*\(", re.IGNORECASE)


def _split_top_level_args(argstr: str) -> list[str]:
    """Split a function-call argument string on top-level commas only,
    respecting nested parens and quoted string literals."""
    args: list[str] = []
    depth = 0
    in_quote: str | None = None
    current: list[str] = []
    for ch in argstr:
        if in_quote:
            current.append(ch)
            if ch == in_quote:
                in_quote = None
            continue
        if ch in ("'", '"'):
            in_quote = ch
            current.append(ch)
        elif ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        args.append("".join(current))
    return [a.strip() for a in args]


def _find_matching_close_paren(sql: str, open_paren_index: int) -> int | None:
    """Return the index just past the ``)`` matching the ``(`` at
    ``open_paren_index - 1``, or ``None`` if the call is unbalanced."""
    depth = 1
    j = open_paren_index
    in_quote: str | None = None
    while j < len(sql) and depth > 0:
        ch = sql[j]
        if in_quote:
            if ch == in_quote:
                in_quote = None
        elif ch in ("'", '"'):
            in_quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        j += 1
    return j if depth == 0 else None


def _rewrite_dateadd(sql: str) -> str:
    """Rewrite ``DATEADD(unit, amount, expr)`` to Teiid's
    ``TIMESTAMPADD(SQL_TSI_<UNIT>, amount, expr)``.

    Uses manual paren/quote-aware scanning (not a single regex) because the
    third argument routinely contains its own parens, e.g.
    ``DATEADD(year, -1, CURRENT_DATE())``.
    """
    result: list[str] = []
    i = 0
    while True:
        m = _DATEADD_RE.search(sql, i)
        if not m:
            result.append(sql[i:])
            break
        result.append(sql[i:m.start()])
        close = _find_matching_close_paren(sql, m.end())
        if close is None:
            # Unbalanced -- leave the rest untouched rather than risk
            # mangling a query we can't safely parse.
            result.append(sql[m.start():])
            i = len(sql)
            break
        argstr = sql[m.end():close - 1]
        args = _split_top_level_args(argstr)
        if len(args) != 3:
            result.append(sql[m.start():close])
            i = close
            continue
        raw_unit = args[0].strip().strip("'\"").lower()
        teiid_unit = _DATEADD_UNIT_MAP.get(raw_unit)
        if teiid_unit is None:
            result.append(sql[m.start():close])
            i = close
            continue
        amount, expr = args[1], args[2]
        result.append(f"TIMESTAMPADD({teiid_unit}, {amount}, {expr})")
        i = close
    return "".join(result)


# MySQL DATE_FORMAT mask tokens -> Java SimpleDateFormat (Teiid's mask
# dialect for FORMATTIMESTAMP). Ordered longest-first isn't needed since
# every token here is exactly two characters (%X).
_MYSQL_MASK_TOKENS = {
    "%Y": "yyyy",
    "%y": "yy",
    "%m": "MM",
    "%c": "M",
    "%d": "dd",
    "%e": "d",
    "%H": "HH",
    "%h": "hh",
    "%I": "hh",
    "%i": "mm",
    "%s": "ss",
    "%S": "ss",
    "%p": "a",
    "%M": "MMMM",
    "%b": "MMM",
    "%W": "EEEE",
    "%a": "EEE",
}

_MYSQL_MASK_RE = re.compile("|".join(re.escape(k) for k in _MYSQL_MASK_TOKENS))

_DATE_FORMAT_RE = re.compile(
    r"DATE_FORMAT\s*\(\s*([^,]+?)\s*,\s*('(?:[^']|'')*')\s*\)",
    re.IGNORECASE,
)


def _translate_mysql_mask(mask: str) -> str:
    return _MYSQL_MASK_RE.sub(lambda m: _MYSQL_MASK_TOKENS[m.group(0)], mask)


def _rewrite_date_format(sql: str) -> str:
    """Rewrite MySQL-style ``DATE_FORMAT(expr, 'mask')`` to Teiid's
    ``FORMATTIMESTAMP(expr, 'javaMask')``. Teiid has no DATE_FORMAT function
    (TEIID30068 "unknown form"), so a generated query using it fails
    outright regardless of the expr/mask.

    Only matches a simple (non-comma, non-nested-call) first argument --
    the common case of a bare or qualified/quoted column reference -- and
    leaves anything else alone rather than risk mangling it.
    """

    def _repl(m: re.Match[str]) -> str:
        expr = m.group(1)
        mask = _translate_mysql_mask(_extract_string(m.group(2)))
        return f"FORMATTIMESTAMP({expr}, '{mask}')"

    return _DATE_FORMAT_RE.sub(_repl, sql)


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

    # Non-Teiid dialect functions the model reaches for that have no Teiid
    # equivalent under the same name at all -- rewrite before the
    # mask-inference passes below so their arguments are left untouched.
    sql = _rewrite_dateadd(sql)
    sql = _rewrite_date_format(sql)

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
