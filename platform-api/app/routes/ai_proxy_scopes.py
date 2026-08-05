"""Project scope-map analysis and auto-creation endpoints."""

from __future__ import annotations

import logging
from typing import Any, cast

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.query_scope import QueryScope
from app.models.saved_query import SavedQuery
from app.services.auto_scope import _get_or_create_ai_scope_set

from .ai_proxy_schemas import (
    AIGenerateRelationshipsRequest,
)
from .ai_proxy_shared import (
    _check_project_access,
    _forward_to_ai,
)

logger = logging.getLogger(__name__)
router = APIRouter()

def _is_numeric_column(name: str) -> bool:
    """Return True if a column name looks like a numeric/aggregate value.

    Numeric columns (Revenue, Amount, Cost, Price, Quantity, Count, Sum, Total,
    etc.) should NOT be used for drill-down scopes — only identifier/name columns
    (ProductName, CategoryName, CustomerID, OrderID, etc.) are meaningful for
    drill-down relationships.
    """
    numeric_keywords = {
        "revenue", "amount", "cost", "price", "quantity", "count", "sum",
        "total", "average", "avg", "min", "max", "profit", "discount",
        "sales", "units", "weight", "balance", "fee", "rate", "percent",
        "percentage", "margin", "tax", "freight", "subtotal",
    }
    lower = name.lower()
    for kw in numeric_keywords:
        if kw in lower:
            return True
    return False


def _is_summarized_query(sql: str) -> bool:
    """Return True if the SQL is an aggregated/summarized query.

    A query is considered summarized if it contains GROUP BY or aggregate
    functions (SUM, COUNT, AVG, MIN, MAX). Summarized queries drill DOWN
    into detailed queries, not the other way around.
    """
    import re
    upper = sql.upper()
    if re.search(r"\bGROUP\s+BY\b", upper):
        return True
    if re.search(r"\b(SUM|COUNT|AVG|MIN|MAX)\s*\(", upper):
        return True
    return False


def _extract_select_columns(sql: str) -> list[str]:
    """Extract column names/aliases from a SQL SELECT clause using regex.

    Returns the alias (AS name) or the raw column reference for each item.
    """
    import re

    cols: list[str] = []

    # Extract text between SELECT and FROM (first occurrence, skip nested subqueries)
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
        # Check for AS alias
        alias_match = re.search(r"\bAS\s+[\"']?(\w+)[\"']?\s*$", item, re.IGNORECASE)
        if alias_match:
            cols.append(alias_match.group(1))
            continue
        # No alias — take the last identifier (column name after any dot)
        # Strip surrounding quotes
        ident_match = re.search(r'[\".]?(\w+)[\"]*\s*$', item.rstrip())
        if ident_match:
            cols.append(ident_match.group(1))
    return cols


async def _sample_query_values(
    *,
    sql: str,
    database: str,
    teiid_host: str | None = None,
    teiid_port: int | None = None,
) -> dict[str, set[str]]:
    """Execute a query with LIMIT 10 and return distinct string values per column.

    Returns a dict mapping column_name → set of non-null, non-numeric
    distinct string values found in the sample rows.
    """
    from app.routes.query import _auto_cast_aggregates, _run_sql

    sample_sql = _auto_cast_aggregates(sql.rstrip().rstrip(";")) + " LIMIT 10"
    try:
        result = await _run_sql(
            database=database, sql=sample_sql,
            teiid_host=teiid_host, teiid_port=teiid_port,
        )
    except Exception:
        logger.warning("Failed to sample query for scope validation: %s", sql[:80])
        return {}

    col_values: dict[str, set[str]] = {}
    for col in result.get("columns", []):
        col_values[col] = set()
    for row in result.get("rows", []):
        for col, val in row.items():
            if val is None:
                continue
            s = str(val).strip()
            if not s:
                continue
            col_values.setdefault(col, set()).add(s)
    return col_values


def _has_string_values(vals: set[str]) -> bool:
    """Return True if the set contains at least one non-numeric string value."""
    for v in vals:
        try:
            float(v.replace(",", ""))
        except ValueError:
            return True
    return False


def _string_values(vals: set[str]) -> set[str]:
    """Return only the non-numeric string values from a set."""
    result: set[str] = set()
    for v in vals:
        try:
            float(v.replace(",", ""))
        except ValueError:
            result.add(v)
    return result


def _value_overlap(
    vals_a: set[str],
    vals_b: set[str],
    *,
    same_column_name: bool = False,
) -> float:
    """Return the fraction of overlapping values (Jaccard-like).

    When ``same_column_name`` is False (different column names), filters
    out numeric values before comparing so that ID columns (1, 2, 3)
    don't get matched against name columns.

    When ``same_column_name`` is True, compares ALL values including
    numeric ones — two columns both named "CategoryID" with values
    {1, 2, 3} should match.
    """
    if same_column_name:
        a, b = vals_a, vals_b
    else:
        a = _string_values(vals_a)
        b = _string_values(vals_b)
    if not a or not b:
        return 0.0
    intersection = a & b
    union = a | b
    return len(intersection) / len(union) if union else 0.0


async def _analyze_project_scopes(
    *,
    session: AsyncSession,
    context: RequestContext,
    project_id: int,
    query_ids: list[int] | None = None,
) -> tuple[list[dict[str, Any]], dict[int, str]]:
    """Hybrid scope analysis: AI suggestions validated by cell-level data.

    Phase 1 — AI Analysis: LLM analyzes SQL structure to suggest scopes
      (direction, meaningful columns).
    Phase 2 — Cell Validation: execute each query with LIMIT 10, compare
      actual cell values to validate AI suggestions and discover cross-column
      relationships the AI may have missed (e.g. CategoryID ↔ CategoryName
      when they share actual values).

    Returns ``(validated_scopes, query_names)`` where each validated scope is a
    directional (summarized→detailed source→target) dict. Shared by both the
    persist path (``_ai_analyze_and_create_scopes``) and the canvas-suggestion
    path (``ai_suggest_scopes``). When ``query_ids`` is given, analysis is
    restricted to those saved queries (used by AI Suggest on the canvas).
    """
    import asyncio

    from app.routes.query import _resolve_vdb_database
    from app.services.tenant_teiid_resolver import TenantTeiidResolver

    # Get all saved queries for this project
    queries_result = await session.scalars(
        select(SavedQuery).where(SavedQuery.project_id == project_id)
    )
    queries = list(queries_result)
    if query_ids is not None:
        wanted = set(query_ids)
        queries = [q for q in queries if q.id in wanted]

    if not queries:
        return [], {}

    # Only send queries that have SQL — include extracted columns for clarity
    query_infos: list[dict[str, Any]] = []
    query_names: dict[int, str] = {}
    for q in queries:
        query_names[q.id] = q.name
        if q.sql_text:
            cols = _extract_select_columns(q.sql_text)
            query_infos.append({
                "id": q.id,
                "name": q.name,
                "sql": q.sql_text,
                "columns": cols,
            })

    if not query_infos:
        return [], query_names

    # ── Phase 1: AI structural analysis via the dedicated scopes endpoint ──
    # Uses /ai/project/scopes/analyze (NOT the generic /ai/ask): the AI server
    # has a purpose-built prompt that returns structured ScopeSuggestion JSON.
    payload = {
        "tenant_id": context.tenant_id,
        "user_id": context.user_id,
        "project_id": project_id,
        "queries": [
            {"id": q["id"], "name": q["name"], "sql": q["sql"]}
            for q in query_infos
        ],
    }

    # Run AI analysis and data sampling in parallel
    database = await _resolve_vdb_database(
        session=session, context=context, project_id=project_id,
    )
    endpoint = await TenantTeiidResolver(session).resolve_for_org(context.tenant_id)

    async def _sample_one(q: dict[str, Any]) -> tuple[int, dict[str, set[str]]]:
        vals = await _sample_query_values(
            sql=q["sql"], database=database,
            teiid_host=endpoint.pg_host, teiid_port=endpoint.pg_port,
        )
        return q["id"], vals

    ai_task = asyncio.create_task(
        _forward_to_ai("/ai/project/scopes/analyze", payload)
    )
    sample_tasks = [asyncio.create_task(_sample_one(q)) for q in query_infos]
    ai_response, *sample_results = await asyncio.gather(ai_task, *sample_tasks)

    # Build query_id → {column_name: set(values)} from samples
    query_values: dict[int, dict[str, set[str]]] = {}
    for qid, col_vals in sample_results:
        query_values[qid] = col_vals

    # The dedicated endpoint returns structured scope suggestions directly.
    scopes_list: list[dict[str, Any]] = ai_response.get("scopes", []) or []

    # Build column map: query_id → set of column names (lowercase)
    query_col_map: dict[int, set[str]] = {}
    for q in queries:
        if q.sql_text:
            cols = _extract_select_columns(q.sql_text)
            query_col_map[q.id] = {c.lower() for c in cols}
        else:
            query_col_map[q.id] = set()

    # ── Phase 2: Validate AI suggestions with cell-level data ────────
    valid_ids = {q.id for q in queries}
    validated_scopes: list[dict[str, Any]] = []

    for suggestion in scopes_list:
        src_qid = suggestion.get("source_query_id")
        tgt_qid = suggestion.get("target_query_id")
        src_field = suggestion.get("source_field", "")
        tgt_field = suggestion.get("target_field", "")

        if src_qid not in valid_ids or tgt_qid not in valid_ids:
            continue
        if not src_field or not tgt_field:
            continue

        # Check fields exist in SELECT clauses
        src_cols = query_col_map.get(cast(int, src_qid), set())
        tgt_cols = query_col_map.get(cast(int, tgt_qid), set())
        if src_field.lower() not in src_cols or tgt_field.lower() not in tgt_cols:
            continue

        # Validate with sampled cell values — require some overlap.
        # When column names match (e.g. CategoryID↔CategoryID), compare ALL
        # values including numeric ones. When names differ (e.g.
        # CategoryName↔CategoryID), only compare string values to prevent
        # false matches between text and numeric columns.
        src_vals = query_values.get(cast(int, src_qid), {}).get(src_field, set())
        tgt_vals = query_values.get(cast(int, tgt_qid), {}).get(tgt_field, set())
        names_match = src_field.lower() == tgt_field.lower()
        overlap = _value_overlap(src_vals, tgt_vals, same_column_name=names_match)

        src_sampled = src_qid in query_values and bool(query_values[src_qid])
        tgt_sampled = tgt_qid in query_values and bool(query_values[tgt_qid])
        if overlap == 0.0 and src_sampled and tgt_sampled:
            logger.info(
                "Rejected AI scope %s.%s → %s.%s — zero value overlap "
                "(src=%r, tgt=%r, names_match=%s)",
                src_qid, src_field, tgt_qid, tgt_field,
                list(src_vals)[:3], list(tgt_vals)[:3], names_match,
            )
            continue

        conf = suggestion.get("confidence", 1.0)
        if overlap > 0:
            conf = max(conf, overlap)

        validated_scopes.append({
            "source_query_id": src_qid,
            "source_query_name": suggestion.get("source_query_name", query_names.get(cast(int, src_qid), "")),
            "source_field": src_field,
            "target_query_id": tgt_qid,
            "target_query_name": suggestion.get("target_query_name", query_names.get(cast(int, tgt_qid), "")),
            "target_field": tgt_field,
            "confidence": conf,
            "reason": suggestion.get("reason", ""),
        })

    # ── Phase 2b: Discover cross-column relationships via value overlap ──
    # Find columns across different queries that share values even if
    # the AI didn't suggest them (e.g. CategoryID ↔ CategoryName when the
    # underlying values are the same entity strings).
    MIN_OVERLAP = 0.3
    discovered_keys = {
        (s["source_query_id"], s["source_field"],
         s["target_query_id"], s["target_field"])
        for s in validated_scopes
    }

    for i, qi in enumerate(query_infos):
        for qj in query_infos[i + 1:]:
            if qi["id"] == qj["id"]:
                continue
            vals_i = query_values.get(qi["id"], {})
            vals_j = query_values.get(qj["id"], {})
            for col_i, v_i in vals_i.items():
                if _is_numeric_column(col_i):
                    continue
                for col_j, v_j in vals_j.items():
                    if _is_numeric_column(col_j):
                        continue
                    names_match = col_i.lower() == col_j.lower()
                    overlap = _value_overlap(v_i, v_j, same_column_name=names_match)
                    if overlap < MIN_OVERLAP:
                        continue

                    # Determine direction: summarized → detailed
                    i_summ = _is_summarized_query(qi["sql"])
                    j_summ = _is_summarized_query(qj["sql"])
                    if i_summ and not j_summ:
                        src_qid, src_field = qi["id"], col_i
                        tgt_qid, tgt_field = qj["id"], col_j
                    elif j_summ and not i_summ:
                        src_qid, src_field = qj["id"], col_j
                        tgt_qid, tgt_field = qi["id"], col_i
                    elif i_summ and j_summ:
                        continue  # both summarized — skip
                    else:
                        # Neither is summarized — pick the shorter one as source
                        if len(qi["columns"]) <= len(qj["columns"]):
                            src_qid, src_field = qi["id"], col_i
                            tgt_qid, tgt_field = qj["id"], col_j
                        else:
                            src_qid, src_field = qj["id"], col_j
                            tgt_qid, tgt_field = qi["id"], col_i

                    key = (src_qid, src_field, tgt_qid, tgt_field)
                    rev_key = (tgt_qid, tgt_field, src_qid, src_field)
                    if key in discovered_keys or rev_key in discovered_keys:
                        continue
                    discovered_keys.add(key)

                    validated_scopes.append({
                        "source_query_id": src_qid,
                        "source_query_name": query_names.get(src_qid, ""),
                        "source_field": src_field,
                        "target_query_id": tgt_qid,
                        "target_query_name": query_names.get(tgt_qid, ""),
                        "target_field": tgt_field,
                        "confidence": overlap,
                        "reason": f"Cell-level value overlap ({overlap:.0%})",
                    })

    # ── Phase 2c: Exact column-name matching (fallback) ────────────
    # When sampling fails or the AI omits a suggestion, matching column
    # names across two queries is still a strong signal.  This catches
    # cases like CategoryID↔CategoryID where the AI skipped it and
    # sampling returned no data.
    for i, qi in enumerate(query_infos):
        for qj in query_infos[i + 1:]:
            if qi["id"] == qj["id"]:
                continue
            common_cols = set(c.lower() for c in qi["columns"]) & set(
                c.lower() for c in qj["columns"]
            )
            for col_lower in common_cols:
                if _is_numeric_column(col_lower):
                    continue
                # Find original-case column name from each query
                col_i = next((c for c in qi["columns"] if c.lower() == col_lower), col_lower)
                col_j = next((c for c in qj["columns"] if c.lower() == col_lower), col_lower)

                # Determine direction
                i_summ = _is_summarized_query(qi["sql"])
                j_summ = _is_summarized_query(qj["sql"])
                if i_summ and not j_summ:
                    src_qid, src_field = qi["id"], col_i
                    tgt_qid, tgt_field = qj["id"], col_j
                elif j_summ and not i_summ:
                    src_qid, src_field = qj["id"], col_j
                    tgt_qid, tgt_field = qi["id"], col_i
                elif i_summ and j_summ:
                    continue
                else:
                    if len(qi["columns"]) <= len(qj["columns"]):
                        src_qid, src_field = qi["id"], col_i
                        tgt_qid, tgt_field = qj["id"], col_j
                    else:
                        src_qid, src_field = qj["id"], col_j
                        tgt_qid, tgt_field = qi["id"], col_i

                key = (src_qid, src_field, tgt_qid, tgt_field)
                rev_key = (tgt_qid, tgt_field, src_qid, src_field)
                if key in discovered_keys or rev_key in discovered_keys:
                    continue
                discovered_keys.add(key)

                validated_scopes.append({
                    "source_query_id": src_qid,
                    "source_query_name": query_names.get(src_qid, ""),
                    "source_field": src_field,
                    "target_query_id": tgt_qid,
                    "target_query_name": query_names.get(tgt_qid, ""),
                    "target_field": tgt_field,
                    "confidence": 0.85,
                    "reason": f"Exact column name match ({col_lower})",
                })

    return validated_scopes, query_names


async def _ai_analyze_and_create_scopes(
    *,
    session: AsyncSession,
    context: RequestContext,
    project_id: int,
) -> dict[str, Any]:
    """Analyze the project's queries via the LLM analyzer and persist the
    validated directional scopes into the project's "AI Generated Scopes" set.
    """
    validated_scopes, _query_names = await _analyze_project_scopes(
        session=session, context=context, project_id=project_id
    )
    if not validated_scopes:
        return {"relationships": [], "scopes_created": 0, "status": "ok"}

    # ── Write validated scopes to database ───────────────────────────
    existing_scopes = await session.scalars(
        select(QueryScope).where(
            QueryScope.project_id == project_id,
            QueryScope.tenant_id == context.tenant_id,
        )
    )
    existing_keys = {
        (s.query_id, s.source_field, s.target_query_id, s.target_field)
        for s in existing_scopes
    }

    relationships: list[dict[str, Any]] = []
    scopes_created = 0
    ai_set = None
    for s in validated_scopes:
        key = (s["source_query_id"], s["source_field"],
               s["target_query_id"], s["target_field"])

        rel = {
            "left_table": s["source_query_name"],
            "left_column": s["source_field"],
            "right_table": s["target_query_name"],
            "right_column": s["target_field"],
            "source_query_id": s["source_query_id"],
            "target_query_id": s["target_query_id"],
            "confidence": s["confidence"],
            "reason": s["reason"],
            "scope_exists": True,
        }

        if key in existing_keys:
            relationships.append(rel)
            continue

        # Group AI-discovered scopes under the project's "AI Generated Scopes"
        # set so they surface (with a count + toggle) in the new Scopes UI.
        if ai_set is None:
            ai_set = await _get_or_create_ai_scope_set(
                session,
                tenant_id=context.tenant_id,
                project_id=project_id,
                user_id=context.user_id,
            )
        scope = QueryScope(
            tenant_id=context.tenant_id,
            project_id=project_id,
            scope_set_id=ai_set.id,
            query_id=s["source_query_id"],
            source_field=s["source_field"],
            source_table=s["source_query_name"],
            target_query_id=s["target_query_id"],
            target_field=s["target_field"],
            target_table=s["target_query_name"],
            confidence_score=s.get("confidence"),
            created_by_ai=True,
            enabled=ai_set.enabled,
            created_by=context.user_id,
        )
        session.add(scope)
        existing_keys.add(key)
        scopes_created += 1
        relationships.append(rel)

    if scopes_created > 0:
        await session.commit()

    return {
        "relationships": relationships,
        "scopes_created": scopes_created,
        "status": "ok",
    }


@router.post("/project/scope-map/generate")
async def generate_scope_map(
    req: AIGenerateRelationshipsRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Generate query-based scope map using AI analysis.

    Sends all saved queries to the AI server which determines:
    1. Which columns are meaningful for drill-down (not aggregates)
    2. The correct direction (summarized → detailed)
    Auto-creates QueryScope records from AI suggestions.
    """
    await _check_project_access(session, context, req.project_id)
    return await _ai_analyze_and_create_scopes(
        session=session, context=context, project_id=req.project_id
    )


@router.post("/project/scope-map/auto-create")
async def auto_create_scopes_from_queries(
    req: AIGenerateRelationshipsRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Auto-create QueryScope records using AI analysis.

    When scoping is toggled ON, this endpoint sends all saved queries to
    the AI server which determines meaningful drill-down scopes and their
    direction (summarized → detailed).
    """
    await _check_project_access(session, context, req.project_id)
    result = await _ai_analyze_and_create_scopes(
        session=session, context=context, project_id=req.project_id
    )
    return {
        "scopes_created": result["scopes_created"],
        "total_queries": len(result.get("relationships", [])),
        "message": f"Created {result['scopes_created']} scope(s) via AI analysis",
    }
