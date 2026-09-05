"""KG-17: parsed SQL table lineage for saved queries.

``SavedQuery.left_datasource``/``right_datasource`` only capture the
two-table join-builder UI's inputs. A query with more than two tables, a
subquery, or a hand-written/AI-generated ``sql_text`` (the join-builder
fields are never populated for those) produced no lineage at all under the
old substring-on-two-fields approach. This parses ``sql_text`` with the
same sqlglot AST parser already used for authorization
(``app.services.sql_authorization``) and returns every real table name the
query actually references, so lineage reflects the query's real read set
instead of only what the join-builder form happened to record.
"""

from __future__ import annotations

import logging

import sqlglot
from sqlglot import exp

logger = logging.getLogger(__name__)

_DIALECT = "postgres"


def extract_referenced_tables(sql: str | None) -> set[str]:
    """Every real table name referenced anywhere in ``sql``.

    A CTE's own name is excluded (it's a query-scoped virtual table, not a
    real data source -- matching the same distinction ``sql_authorization``
    draws). Returns an empty set for missing or unparsable SQL: lineage
    extraction is best-effort evidence for the knowledge graph, and must
    never raise into the graph-collection path over a malformed or
    dialect-mismatched query.
    """
    text = (sql or "").strip()
    if not text:
        return set()

    try:
        statements = [s for s in sqlglot.parse(text, dialect=_DIALECT) if s is not None]
    except Exception:
        logger.debug("KG-17: could not parse saved-query SQL for lineage", exc_info=True)
        return set()

    tables: set[str] = set()
    for stmt in statements:
        cte_names = {cte.alias.upper() for cte in stmt.find_all(exp.CTE) if cte.alias}
        for table in stmt.find_all(exp.Table):
            name = table.name
            if name and name.upper() not in cte_names:
                tables.add(name)
    return tables


def extract_join_keys(sql: str | None) -> list[dict[str, str]]:
    """KG-28: the join-key column pairs a query's ``JOIN ... ON`` clauses
    actually use, parsed from ``sql_text`` rather than relying solely on
    the join-builder's ``left_column``/``right_column`` fields (which are
    never populated for a hand-written/AI-generated query).

    Each returned dict is ``{"left_table", "left_column", "right_table",
    "right_column", "join_type"}`` -- table names are resolved from their
    query alias back to the real table name where possible (falling back
    to the alias itself for a table this statement doesn't declare, e.g.
    a correlated outer reference). Only equality conditions where *both*
    sides are plain column references count as a join key -- an ON clause
    like ``a.id = b.id AND a.active = true`` has exactly one join key and
    one filter condition, and the filter must not be reported as if it
    were a key. Returns an empty list for missing/unparsable SQL or a
    query with no joins: this is best-effort evidence, not a required
    field, and must never raise into the graph-collection path.
    """
    text = (sql or "").strip()
    if not text:
        return []

    try:
        statements = [s for s in sqlglot.parse(text, dialect=_DIALECT) if s is not None]
    except Exception:
        logger.debug("KG-28: could not parse saved-query SQL for join keys", exc_info=True)
        return []

    join_keys: list[dict[str, str]] = []
    for stmt in statements:
        alias_to_table = {
            (table.alias or table.name): table.name
            for table in stmt.find_all(exp.Table)
            if table.name
        }
        for join in stmt.find_all(exp.Join):
            side = str(join.args.get("side") or "").strip()
            kind = str(join.args.get("kind") or "").strip()
            join_type = " ".join(p for p in (side, kind) if p) or "INNER"

            on_condition = join.args.get("on")
            if on_condition is None:
                continue
            for eq in on_condition.find_all(exp.EQ):
                left, right = eq.left, eq.right
                if not isinstance(left, exp.Column) or not isinstance(right, exp.Column):
                    continue
                join_keys.append({
                    "left_table": alias_to_table.get(left.table, left.table),
                    "left_column": left.name,
                    "right_table": alias_to_table.get(right.table, right.table),
                    "right_column": right.name,
                    "join_type": join_type,
                })
    return join_keys
