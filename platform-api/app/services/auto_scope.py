"""Auto-create QueryScope records when queries are saved or updated.

Analyzes the SQL SELECT clause of every saved query in the project,
finds common column names between query pairs, and creates QueryScope
records for each match so drill-down scoping works automatically.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.query_scope import QueryScope
from app.models.saved_query import SavedQuery

logger = logging.getLogger(__name__)


def extract_select_columns(sql: str) -> list[str]:
    """Extract column names/aliases from a SQL SELECT clause using regex."""
    cols: list[str] = []

    m = re.search(r"\bSELECT\s+(.*?)\s+FROM\s+", sql, re.IGNORECASE | re.DOTALL)
    if not m:
        return cols
    raw = m.group(1)

    # Split by commas (respecting parentheses)
    items: list[str] = []
    current: list[str] = []
    paren_depth = 0
    for ch in raw:
        if ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth -= 1
        if ch == "," and paren_depth == 0:
            items.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        items.append("".join(current).strip())

    for item in items:
        if not item or item == "*":
            continue
        alias_match = re.search(r"\bAS\s+[\"']?(\w+)[\"']?\s*$", item, re.IGNORECASE)
        if alias_match:
            cols.append(alias_match.group(1))
            continue
        ident_match = re.search(r'[\".]?(\w+)[\"]*\s*$', item.rstrip())
        if ident_match:
            cols.append(ident_match.group(1))
    return cols


async def auto_create_scopes_for_query(
    session: AsyncSession,
    *,
    query: SavedQuery,
    tenant_id: int,
    user_id: int,
) -> int:
    """Auto-create QueryScope records for a saved query.

    Compares columns from this query against all other queries in the same
    project and creates QueryScope records for matching column names.

    Returns the number of new scopes created.
    """
    if not query.sql_text:
        return 0

    new_cols = extract_select_columns(query.sql_text)
    if not new_cols:
        return 0

    # Get all other queries in the same project
    others_result = await session.scalars(
        select(SavedQuery).where(
            SavedQuery.project_id == query.project_id,
            SavedQuery.id != query.id,
        )
    )
    others = list(others_result)
    if not others:
        return 0

    # Get existing scopes for this project
    existing_result = await session.scalars(
        select(QueryScope).where(
            QueryScope.project_id == query.project_id,
            QueryScope.tenant_id == tenant_id,
        )
    )
    existing_keys = {
        (s.query_id, s.source_field, s.target_query_id, s.target_field)
        for s in existing_result
    }

    scopes_created = 0
    new_cols_lower = {c.lower(): c for c in new_cols}

    for other_q in others:
        if not other_q.sql_text:
            continue
        other_cols = extract_select_columns(other_q.sql_text)
        other_cols_lower = {c.lower(): c for c in other_cols}

        common_lower = set(new_cols_lower.keys()) & set(other_cols_lower.keys())

        for field_lower in common_lower:
            src_field = new_cols_lower[field_lower]
            tgt_field = other_cols_lower[field_lower]

            # new query → other query
            key_fwd = (query.id, src_field, other_q.id, tgt_field)
            if key_fwd not in existing_keys:
                session.add(QueryScope(
                    tenant_id=tenant_id,
                    project_id=query.project_id,
                    query_id=query.id,
                    source_field=src_field,
                    target_query_id=other_q.id,
                    target_field=tgt_field,
                    created_by=user_id,
                ))
                existing_keys.add(key_fwd)
                scopes_created += 1

            # other query → new query
            key_rev = (other_q.id, tgt_field, query.id, src_field)
            if key_rev not in existing_keys:
                session.add(QueryScope(
                    tenant_id=tenant_id,
                    project_id=query.project_id,
                    query_id=other_q.id,
                    source_field=tgt_field,
                    target_query_id=query.id,
                    target_field=src_field,
                    created_by=user_id,
                ))
                existing_keys.add(key_rev)
                scopes_created += 1

    if scopes_created > 0:
        logger.info(
            "Auto-created %d scope(s) for query %d in project %d",
            scopes_created, query.id, query.project_id,
        )

    return scopes_created
