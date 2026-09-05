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
