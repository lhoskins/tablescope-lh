"""AST-based authorization gate for direct datasource SQL execution.

Security fix for TS-ISO-002: ``/api/query/datasource`` used to execute the
caller's initial SQL directly -- no read-only check, no table-allowlist
enforcement -- before ever attempting repair. ``allowed_tables`` existed
only to help the AI self-repair agent phrase a rewrite after a Teiid
failure; it was never an execution gate. A regex/prefix check (e.g. "starts
with SELECT") is not sufficient defense: it cannot see a write statement
smuggled in a second stacked statement, hidden inside a CTE, or masked by a
comment. This module parses with a real SQL AST (sqlglot) instead.

Dialect note: parsed with ``dialect="postgres"`` because Teiid speaks the
Postgres wire protocol and its SQL surface is close enough for *structural*
validation (statement count, statement kind, referenced tables) -- this is
a defense-in-depth authorization gate, not a Teiid-compatibility linter.
Teiid itself remains the final authority on whether a query that passes
this gate actually executes.
"""

from __future__ import annotations

import logging

import sqlglot
from sqlglot import exp

logger = logging.getLogger(__name__)

_DIALECT = "postgres"

#: Only these statement kinds may reach Teiid through this path.
_ALLOWED_ROOT_TYPES: tuple[type[exp.Expression], ...] = (
    exp.Select,
    exp.Union,
    exp.Except,
    exp.Intersect,
)

#: Node types that must never appear anywhere in the parsed tree -- including
#: nested inside a CTE, a subquery, or one branch of a UNION. sqlglot falls
#: back to a generic ``Command`` node for syntax it doesn't have a specific
#: node for (this is how ``CALL proc()`` and most procedural/administrative
#: statements come through), so rejecting ``Command`` closes that class of
#: bypass too, not just the named DML/DDL kinds.
_DISALLOWED_NODE_TYPES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.TruncateTable,
    exp.Grant,
    exp.Command,
    exp.Copy,
    exp.Transaction,
    exp.Set,
)


class SQLAuthorizationError(Exception):
    """Raised when SQL fails the read-only/table-allowlist gate."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def authorize_sql(sql: str, allowed_tables: list[str]) -> None:
    """Raise :class:`SQLAuthorizationError` unless ``sql`` is a single
    read-only statement referencing only ``allowed_tables``.

    Call this BEFORE the first execution attempt of any caller-supplied SQL,
    not only on a rewrite after a failure -- the whole point is that the
    very first thing sent to Teiid has already been authorized.
    """
    text = (sql or "").strip().rstrip(";").strip()
    if not text:
        raise SQLAuthorizationError("Empty query")

    try:
        statements = [s for s in sqlglot.parse(text, dialect=_DIALECT) if s is not None]
    except Exception as exc:
        raise SQLAuthorizationError(f"Could not parse SQL: {exc}") from exc

    if len(statements) != 1:
        raise SQLAuthorizationError(
            "Only a single SQL statement is allowed (no stacked statements)"
        )
    root = statements[0]

    if not isinstance(root, _ALLOWED_ROOT_TYPES):
        raise SQLAuthorizationError(
            "Only read-only SELECT/WITH/UNION statements are allowed "
            f"(got {type(root).__name__})"
        )

    for node in root.walk():
        if isinstance(node, _DISALLOWED_NODE_TYPES):
            raise SQLAuthorizationError(
                f"Disallowed SQL construct: {type(node).__name__}"
            )

    if allowed_tables:
        allowed_upper = {t.upper() for t in allowed_tables}
        # A CTE's own name (WITH x AS (...) ... FROM x) is a query-scoped
        # virtual table, not a real data source -- referencing it is
        # legitimate even though it's never in allowed_tables. Its
        # definition body is still checked normally: the real table(s) it
        # selects FROM must themselves be authorized.
        cte_names = {cte.alias.upper() for cte in root.find_all(exp.CTE) if cte.alias}
        for table in root.find_all(exp.Table):
            name = table.name
            if not name or name.upper() in cte_names:
                continue
            if name.upper() not in allowed_upper:
                raise SQLAuthorizationError(f"Unauthorized table reference: {name}")
