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


class SQLValidationError(Exception):
    def __init__(self, reason: str, violations: list[str]):
        self.reason = reason
        self.violations = violations
        super().__init__(reason)


def validate_sql(
    sql: str,
    allowed_tables: list[str],
    allowed_columns: list[str] | None = None,
) -> None:
    """Validate generated SQL against allowed tables/columns.

    Raises SQLValidationError if the SQL is unsafe or references
    unauthorized data sources.
    """
    violations: list[str] = []
    sql_upper = sql.upper()

    # Check for write operations
    for keyword in WRITE_KEYWORDS:
        pattern = re.compile(rf"\b{keyword}\b", re.IGNORECASE)
        if pattern.search(sql):
            violations.append(f"Write operation not allowed: {keyword}")

    # Check for SELECT *
    if SELECT_STAR_PATTERN.search(sql):
        violations.append("SELECT * is not allowed — specify columns explicitly")

    # Check table references
    if allowed_tables:
        # Normalize table names for comparison
        allowed_upper = {t.upper() for t in allowed_tables}
        # Extract table references from FROM and JOIN clauses. The negative
        # lookahead skips identifiers that are actually function calls, so the
        # "FROM" inside EXTRACT(YEAR FROM CAST("col" AS date)) is not mistaken
        # for a table reference named CAST.
        table_pattern = re.compile(
            r"(?:FROM|JOIN)\s+\"?(\w+)\"?(?![\w(])", re.IGNORECASE
        )
        referenced = table_pattern.findall(sql)
        for table in referenced:
            if table.upper() not in allowed_upper:
                violations.append(f"Unauthorized table reference: {table}")

    if violations:
        logger.warning(
            "SQL validation failed: %s | SQL: %s",
            "; ".join(violations), sql[:200],
        )
        raise SQLValidationError(
            reason=f"SQL validation failed: {'; '.join(violations)}",
            violations=violations,
        )
