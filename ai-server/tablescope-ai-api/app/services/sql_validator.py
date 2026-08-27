"""SQL validation — ensures generated SQL is safe and scoped.

Validates:
1. Only allowed tables are referenced
2. Only allowed columns are referenced (when column list available)
3. Read-only (no INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/CREATE)
4. No SELECT *
5. No cross-project datasource references
"""

import logging
import re

logger = logging.getLogger(__name__)

# Dangerous SQL keywords (case-insensitive)
WRITE_KEYWORDS = {
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE",
    "CREATE", "GRANT", "REVOKE", "EXEC", "EXECUTE", "MERGE",
}

SELECT_STAR_PATTERN = re.compile(r"\bSELECT\s+\*", re.IGNORECASE)

# SQL/Teiid keywords, functions and type names that are never column references.
# Used to avoid false positives when checking bare (unqualified) identifiers.
_NON_COLUMN_WORDS = {
    "SELECT", "FROM", "WHERE", "GROUP", "BY", "ORDER", "HAVING", "JOIN",
    "INNER", "LEFT", "RIGHT", "FULL", "OUTER", "CROSS", "ON", "AS", "AND",
    "OR", "NOT", "IN", "IS", "NULL", "LIKE", "BETWEEN", "DISTINCT", "LIMIT",
    "OFFSET", "UNION", "ALL", "CASE", "WHEN", "THEN", "ELSE", "END", "ASC",
    "DESC", "WITH", "OVER", "PARTITION", "EXISTS", "ANY", "SOME", "USING",
    "CAST", "EXTRACT", "YEAR", "MONTH", "DAY", "HOUR", "MINUTE", "SECOND",
    "QUARTER", "WEEK", "FORMATDATE", "DATE_TRUNC", "PARSEDATE", "CURRENT_DATE",
    "CURRENT_TIMESTAMP", "COUNT", "SUM", "AVG", "MIN", "MAX", "COALESCE",
    "ROUND", "ABS", "CEILING", "FLOOR", "SUBSTRING", "CONCAT", "TRIM",
    "UPPER", "LOWER", "LENGTH", "NULLIF", "ROW_NUMBER", "RANK", "DENSE_RANK",
    "DATE", "DOUBLE", "INTEGER", "INT", "BIGINT", "SMALLINT", "VARCHAR",
    "CHAR", "STRING", "BOOLEAN", "FLOAT", "DECIMAL", "NUMERIC", "REAL",
    "TIMESTAMP", "TIME", "TRUE", "FALSE", "LONG", "SHORT", "BYTE", "OBJECT",
}

_STRING_LITERAL_RE = re.compile(r"'[^']*'")
_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_QUALIFIED_REF_RE = re.compile(r'"?(\w+)"?\.\s*"?(\w+)"?')
_TABLE_ALIAS_RE = re.compile(
    r'(?:FROM|JOIN)\s+"?(\w+)"?(?:\s+(?:AS\s+)?"?(\w+)"?)?', re.IGNORECASE
)
_OUTPUT_ALIAS_RE = re.compile(r'\bAS\s+"?(\w+)"?', re.IGNORECASE)
_BARE_IDENT_RE = re.compile(r'(?<![\w."])"?([A-Za-z_]\w*)"?(?![\w("])')

# Keywords that precede a ``(`` for a subquery or clause, not a function call.
_NON_FUNCTION_OPENERS = {
    "SELECT", "WITH", "FROM", "JOIN", "WHERE", "GROUP", "ORDER", "HAVING",
    "ON", "AS", "CASE", "WHEN", "THEN", "ELSE", "UNION", "INTERSECT",
    "EXCEPT", "OVER", "PARTITION", "LIMIT", "OFFSET",
}


def _is_inside_function_call(sql: str, pos: int) -> bool:
    """Return True if ``pos`` is inside a parenthesised function argument list.

    Scans backward from ``pos`` to find the nearest unmatched ``(``. If that
    paren was opened by a function name (a word, not a SQL clause keyword),
    the position is inside a function call and ``FROM``/``JOIN`` tokens there
    are not table references (e.g. ``EXTRACT(YEAR FROM "Month")``).
    """
    depth = 0
    i = pos - 1
    while i >= 0:
        ch = sql[i]
        if ch == ")":
            depth += 1
        elif ch == "(":
            if depth > 0:
                depth -= 1
            else:
                # Found the enclosing paren. Check what token precedes it.
                j = i - 1
                while j >= 0 and sql[j].isspace():
                    j -= 1
                m = re.match(r"[A-Za-z_]\w*$", sql[: j + 1])
                if m:
                    token = m.group(0).upper()
                    if token not in _NON_FUNCTION_OPENERS:
                        return True
                break
        i -= 1
    return False


_UNION_SPLIT_RE = re.compile(r"\bUNION\s+(?:ALL|DISTINCT)\b|\bUNION\b", re.IGNORECASE)
_ORDER_BY_RE = re.compile(r"\bORDER\s+BY\b", re.IGNORECASE)


def _validate_union_order_by(sql: str, violations: list[str]) -> None:
    """Reject ORDER BY inside a UNION/INTERSECT/EXCEPT branch."""
    # Work on a normalized copy where string literals are blanked so a literal
    # containing the words does not trigger a false positive.
    masked = _BLOCK_COMMENT_RE.sub(" ", sql)
    masked = _LINE_COMMENT_RE.sub(" ", masked)
    masked = _STRING_LITERAL_RE.sub("''", masked)

    if not _UNION_SPLIT_RE.search(masked):
        return

    branches = _UNION_SPLIT_RE.split(masked)
    # The last branch is allowed to have an ORDER BY. Any earlier branch with
    # ORDER BY is invalid SQL.
    for branch in branches[:-1]:
        if _ORDER_BY_RE.search(branch):
            violations.append(
                "ORDER BY is not allowed inside a UNION branch; place it only "
                "at the end of the entire query"
            )
            return


def _validate_columns(
    sql: str,
    table_columns: dict[str, list[str]],
    violations: list[str],
) -> None:
    """Reject references to columns a source does not expose.

    Only sources with a known column list are checked. Qualified references
    (``alias.Column``) are validated against the aliased table; unqualified
    identifiers are validated only when a single known table is in scope, to
    keep the check high-precision (no false positives on aliases/keywords).
    Violations list the real available columns so the repair pass can remap
    hallucinated names (e.g. ``DefectRate`` → ``DefectQty``).
    """
    # Upper-cased lookups plus original-cased names for readable messages.
    upper_cols = {
        t.upper(): {c.upper() for c in cols}
        for t, cols in table_columns.items()
        if cols
    }
    orig_names = {t.upper(): t for t in table_columns}
    orig_cols = {t.upper(): list(cols) for t, cols in table_columns.items()}
    if not upper_cols:
        return

    # Strip comments and string literals so words inside a note like
    # ``-- Avoid division by zero`` or a literal like ``'Late'`` are never
    # mistaken for column references (a false positive that would wrongly
    # reject valid SQL).
    sql = _BLOCK_COMMENT_RE.sub(" ", sql)
    sql = _LINE_COMMENT_RE.sub(" ", sql)
    sql = _STRING_LITERAL_RE.sub("''", sql)

    # Map every table and its alias to the canonical (upper) table name.
    alias_to_table: dict[str, str] = {}
    for table, alias in _TABLE_ALIAS_RE.findall(sql):
        tu = table.upper()
        if tu not in upper_cols:
            continue
        alias_to_table[tu] = tu
        if alias and alias.upper() not in _NON_COLUMN_WORDS:
            alias_to_table[alias.upper()] = tu

    def _flag(col: str, table_upper: str) -> None:
        available = ", ".join(orig_cols.get(table_upper, []))
        violations.append(
            f"Column '{col}' does not exist in "
            f"'{orig_names.get(table_upper, table_upper)}'. "
            f"Available columns: {available}"
        )

    seen: set[str] = set()

    # Qualified references: alias.Column
    for qual, col in _QUALIFIED_REF_RE.findall(sql):
        table_upper = alias_to_table.get(qual.upper())
        if not table_upper:
            continue
        if col.upper() not in upper_cols[table_upper]:
            key = f"{table_upper}.{col.upper()}"
            if key not in seen:
                seen.add(key)
                _flag(col, table_upper)

    # Unqualified identifiers — only when exactly one known table is in scope.
    used = set(alias_to_table.values())
    if len(used) == 1:
        (table_upper,) = tuple(used)
        valid = upper_cols[table_upper]
        aliases_upper = set(alias_to_table)
        output_aliases = {a.upper() for a in _OUTPUT_ALIAS_RE.findall(sql)}
        for ident in _BARE_IDENT_RE.findall(sql):
            u = ident.upper()
            if (
                u in _NON_COLUMN_WORDS
                or u in aliases_upper
                or u in output_aliases
                or u in valid
            ):
                continue
            key = f"{table_upper}.{u}"
            if key not in seen:
                seen.add(key)
                _flag(ident, table_upper)

# Strip leading SQL comments so a query prefixed with a ``-- ...`` or
# ``/* ... */`` note still passes the "starts with SELECT/WITH" guard.
_LEADING_COMMENT_RE = re.compile(
    r"^(?:\s*(?:--[^\n]*\n|/\*.*?\*/))+", re.DOTALL
)
_STATEMENT_START_RE = re.compile(r"^(?:SELECT|WITH)\b", re.IGNORECASE)


class SQLValidationError(Exception):
    def __init__(self, reason: str, violations: list[str]):
        self.reason = reason
        self.violations = violations
        super().__init__(reason)


def validate_sql(
    sql: str,
    allowed_tables: list[str],
    allowed_columns: list[str] | None = None,
    table_columns: dict[str, list[str]] | None = None,
) -> None:
    """Validate generated SQL against allowed tables/columns.

    Raises SQLValidationError if the SQL is unsafe or references
    unauthorized data sources. When ``table_columns`` (source name → real
    column names) is supplied, references to columns a source does not expose
    are rejected so the repair pass can remap hallucinated column names.
    """
    violations: list[str] = []

    # Must be a single read-only statement — reject prose or non-SELECT text
    # before it can reach Teiid (e.g. "To calculate the defect rate ...").
    body = _LEADING_COMMENT_RE.sub("", sql.strip()).lstrip()
    if not _STATEMENT_START_RE.match(body):
        violations.append(
            "Query must be a single read-only statement starting with "
            "SELECT or WITH"
        )

    # Check for write operations
    for keyword in WRITE_KEYWORDS:
        pattern = re.compile(rf"\b{keyword}\b", re.IGNORECASE)
        if pattern.search(sql):
            violations.append(f"Write operation not allowed: {keyword}")

    # Check for SELECT *
    if SELECT_STAR_PATTERN.search(sql):
        violations.append("SELECT * is not allowed — specify columns explicitly")

    # Check for invalid UNION/ORDER BY placement. In Teiid an ORDER BY is only
    # valid at the end of the entire UNION statement; inside a branch it fails.
    _validate_union_order_by(sql, violations)

    # Check table references
    if allowed_tables:
        # Normalize table names for comparison
        allowed_upper = {t.upper() for t in allowed_tables}
        # Extract table references from FROM and JOIN clauses.  Ignore matches
        # that sit inside a function call's argument list (e.g. the ``FROM`` in
        # ``EXTRACT(YEAR FROM "Month")`` or ``SUBSTRING(col FROM 1 FOR 5)``).
        table_pattern = re.compile(
            r"(?:FROM|JOIN)\s+\"?(\w+)\"?(?![\w(])", re.IGNORECASE
        )
        referenced = [
            m.group(1)
            for m in table_pattern.finditer(sql)
            if not _is_inside_function_call(sql, m.start())
        ]
        if not referenced:
            # Every real query against these sources needs a FROM/JOIN --
            # there is no legitimate reason to generate one without it.
            # Confirmed live: an aggregate query (SUM/COUNT with a CASE
            # WHEN) can come back with the aggregate expression present but
            # the FROM clause missing entirely, which Teiid rejects with a
            # confusing "aggregate functions only allowed in ..." error
            # instead of a clear missing-table one. Catch it here so it
            # reads as what it is and never reaches the engine.
            violations.append("Query is missing a FROM clause")
        for table in referenced:
            if table.upper() not in allowed_upper:
                violations.append(f"Unauthorized table reference: {table}")

    # Check column references against each source's real columns.
    if table_columns:
        _validate_columns(sql, table_columns, violations)

    if violations:
        logger.warning(
            "SQL validation failed: %s | SQL: %s",
            "; ".join(violations), sql[:200],
        )
        raise SQLValidationError(
            reason=f"SQL validation failed: {'; '.join(violations)}",
            violations=violations,
        )
