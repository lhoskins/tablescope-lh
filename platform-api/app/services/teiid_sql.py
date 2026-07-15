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


def normalize_teiid_timestamps(
    sql: str,
    *,
    column_samples: dict[str, str] | None = None,
) -> str:
    """Rewrite timestamp/date expressions to Teiid-parseable forms.

    Handles:
    - PostgreSQL ``to_timestamp('literal')`` and ``to_date('literal')``,
      with or without an explicit format string.
    - ``CAST('literal' AS timestamp|date)`` where the literal matches a known
      ISO/slash pattern.
    - ``CAST("col" AS timestamp|date)`` when a sample value is supplied for
      the column so a mask can be inferred.

    Unknown column casts are left as-is; the query will fail in the normal
    Teiid execution path and can be repaired by the existing AI SQL fix loop.
    """
    column_samples = column_samples or {}

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
    """Rewrite ``CAST("col" AS date|timestamp)`` to ``PARSETIMESTAMP(...)``
    for columns whose sample value matches a known mask.

    This is the same helper used by the Business Insight analyst loop so the
    query-suggestion and datasource-execution paths behave consistently.
    """
    for col, mask in date_masks.items():
        pat = re.compile(
            r'CAST\(\s*"' + re.escape(col) + r'"\s+AS\s+(?:date|timestamp)\s*\)',
            re.IGNORECASE,
        )
        sql = pat.sub(f'PARSETIMESTAMP("{col}", \'{mask}\')', sql)
    return sql
