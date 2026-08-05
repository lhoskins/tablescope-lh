"""Dashboard datasource schema + widget query routes.

Includes:
- Schema endpoint: returns column metadata for a datasource/query
- Widget query endpoint: generates aggregation SQL (GROUP BY, DATE_TRUNC,
  filters, sort, limit) and executes it against the tenant's Teiid
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.file_source_meta import FileSourceMeta
from app.models.user_vdb import UserVDB
from app.routes.dashboards_crud import _require_project_access
from app.services.connection_pool import pool_manager
from app.services.tenant_teiid_resolver import TenantTeiidResolver

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects/{project_id}/dashboards", tags=["dashboards"])

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_$.]*$")


# ── Schema endpoint ──────────────────────────────────────────────────

class ColumnInfo(BaseModel):
    name: str
    type: str  # "string", "number", "date", "boolean"


class SchemaResponse(BaseModel):
    columns: list[ColumnInfo]


@router.get("/schema/{view_name}", response_model=SchemaResponse)
async def get_datasource_schema(
    project_id: int,
    view_name: str,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> SchemaResponse:
    """Return column names and inferred types for a datasource view.

    First checks file_source_meta.column_types (populated on upload).
    Falls back to querying Teiid ``SELECT * ... LIMIT 1`` to infer types.
    """
    await _require_project_access(project_id, session, context)

    # Try file_source_meta first (has column_types from upload)
    meta = await session.scalar(
        select(FileSourceMeta).where(
            FileSourceMeta.tenant_id == context.tenant_id,
            FileSourceMeta.view_name == view_name,
        )
    )
    if meta and meta.column_types:
        columns = [
            ColumnInfo(name=c["name"], type=_normalize_type(c.get("type", "string")))
            for c in meta.column_types
        ]
        return SchemaResponse(columns=columns)

    # Fallback: query Teiid for one row and infer from values
    if not _IDENTIFIER_RE.match(view_name):
        raise HTTPException(status_code=400, detail=f"Invalid view name: {view_name!r}")

    database = await _resolve_vdb(session=session, context=context, project_id=project_id)
    endpoint = await TenantTeiidResolver(session).resolve_for_org(context.tenant_id)
    sql = f'SELECT * FROM "{view_name}" LIMIT 1'
    result = await _run_widget_sql(
        database=database, sql=sql,
        teiid_host=endpoint.pg_host, teiid_port=endpoint.pg_port,
    )
    inferred: list[ColumnInfo] = []
    if result["rows"]:
        for col_name in result["columns"]:
            val = result["rows"][0].get(col_name)
            inferred.append(ColumnInfo(name=col_name, type=_infer_type(val)))
    else:
        for col_name in result["columns"]:
            inferred.append(ColumnInfo(name=col_name, type="string"))
    return SchemaResponse(columns=inferred)


def _normalize_type(raw: str) -> str:
    """Normalize column type string to one of: string, number, date, boolean."""
    raw_lower = raw.lower()
    if raw_lower in ("date", "datetime", "timestamp", "time"):
        return "date"
    if raw_lower in ("number", "integer", "float", "decimal", "currency", "int", "bigint", "double"):
        return "number"
    if raw_lower in ("boolean", "bool"):
        return "boolean"
    return "string"


def _infer_type(value: Any) -> str:
    """Infer column type from a sample value."""
    if value is None:
        return "string"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    val_str = str(value)
    # Check for date-like patterns
    if re.match(r"^\d{4}-\d{2}-\d{2}", val_str):
        return "date"
    # Check if numeric string
    try:
        float(val_str.replace(",", ""))
        return "number"
    except ValueError:
        pass
    return "string"


# ── Widget query endpoint ────────────────────────────────────────────

class WidgetFilter(BaseModel):
    column: str
    operator: str  # eq, neq, gt, lt, gte, lte, between, in, not_in, contains
    value: Any
    value2: Any = None  # for "between"


class WidgetQueryRequest(BaseModel):
    view_name: str
    x_column: str
    y_column: str
    aggregation: str = Field(default="sum")  # sum, avg, count, min, max
    date_granularity: str | None = None  # day, week, month, quarter, year
    group_by_column: str | None = None
    sort_by: str = "x_asc"  # x_asc, x_desc, y_asc, y_desc
    limit: int | None = None  # top N
    filters: list[WidgetFilter] = Field(default_factory=list)
    global_filters: list[WidgetFilter] = Field(default_factory=list)


class WidgetQueryResponse(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    sql: str  # Generated SQL for transparency


@router.post("/widget-query", response_model=WidgetQueryResponse)
async def execute_widget_query(
    project_id: int,
    body: WidgetQueryRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> WidgetQueryResponse:
    """Execute an aggregation query for a dashboard widget.

    Generates SQL with:
    - Aggregation function (SUM/AVG/COUNT/MIN/MAX) on Y column
    - Optional DATE_TRUNC on X column for date granularity
    - Optional GROUP BY on a color/series dimension
    - WHERE clause from widget-level + dashboard-level filters
    - ORDER BY and LIMIT
    """
    await _require_project_access(project_id, session, context)

    if not _IDENTIFIER_RE.match(body.view_name):
        raise HTTPException(status_code=400, detail=f"Invalid view name: {body.view_name!r}")

    # Defense-in-depth: the requested view must be one of this project's own
    # datasources. The per-user VDB already isolates tenants, but this rejects
    # any widget (e.g. an AI-hallucinated one) that references a foreign table.
    from app.routes.projects_datasources import list_project_datasources

    project_sources = await list_project_datasources(
        project_id=project_id,
        include_archived=True,
        session=session,
        context=context,
    )
    allowed_views = {ds.get("viewName") for ds in project_sources}
    if body.view_name not in allowed_views:
        raise HTTPException(
            status_code=403,
            detail=f"View {body.view_name!r} is not a datasource of this project",
        )

    sql = _build_widget_sql(body)

    database = await _resolve_vdb(session=session, context=context, project_id=project_id)
    endpoint = await TenantTeiidResolver(session).resolve_for_org(context.tenant_id)
    result = await _run_widget_sql(
        database=database, sql=sql,
        teiid_host=endpoint.pg_host, teiid_port=endpoint.pg_port,
    )
    return WidgetQueryResponse(columns=result["columns"], rows=result["rows"], sql=sql)


def _build_widget_sql(body: WidgetQueryRequest) -> str:
    """Generate aggregation SQL from widget configuration."""
    agg = body.aggregation.upper()
    if agg not in ("SUM", "AVG", "COUNT", "MIN", "MAX"):
        agg = "SUM"

    y_col = _quote_ident(body.y_column)
    x_col = _quote_ident(body.x_column)

    # X expression: apply DATE_TRUNC if granularity is set
    if body.date_granularity and body.date_granularity in ("day", "week", "month", "quarter", "year"):
        # Teiid supports: TIMESTAMPADD / FORMATDATE / parseable casting
        # Use a simpler approach: CAST + string formatting for grouping
        gran = body.date_granularity
        if gran == "day":
            x_expr = f"CAST({x_col} AS DATE)"
            x_alias = "date_day"
        elif gran == "week":
            x_expr = f"CAST({x_col} AS DATE)"
            x_alias = "date_week"
        elif gran == "month":
            x_expr = f"FORMATDATE(CAST({x_col} AS DATE), 'yyyy-MM')"
            x_alias = "date_month"
        elif gran == "quarter":
            x_expr = f"CONCAT(YEAR(CAST({x_col} AS DATE)), '-Q', QUARTER(CAST({x_col} AS DATE)))"
            x_alias = "date_quarter"
        else:  # year
            x_expr = f"YEAR(CAST({x_col} AS DATE))"
            x_alias = "date_year"
    else:
        x_expr = x_col
        x_alias = body.x_column

    # SELECT clause
    select_parts = [f"{x_expr} AS \"{x_alias}\""]
    group_parts = [x_expr]

    # Group by additional dimension (color by)
    if body.group_by_column:
        gb_col = _quote_ident(body.group_by_column)
        select_parts.append(f"{gb_col} AS \"{body.group_by_column}\"")
        group_parts.append(gb_col)

    # Aggregation on Y — CAST to double for numeric aggregations since CSV
    # columns are often imported as string type by Teiid
    if agg == "COUNT":
        agg_expr = f"COUNT({y_col})"
    else:
        agg_expr = f"{agg}(CAST({y_col} AS double))"
    agg_alias = f"{agg.lower()}_{body.y_column}"
    select_parts.append(f"{agg_expr} AS \"{agg_alias}\"")

    # FROM
    table = f"\"{body.view_name}\""

    # WHERE (combine widget filters + global filters)
    all_filters = list(body.filters) + list(body.global_filters)
    where_clauses = _build_where(all_filters)
    where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    # GROUP BY
    group_sql = f" GROUP BY {', '.join(group_parts)}"

    # ORDER BY
    sort_col: str
    sort_dir: str
    if body.sort_by == "y_desc":
        sort_col = agg_expr
        sort_dir = "DESC"
    elif body.sort_by == "y_asc":
        sort_col = agg_expr
        sort_dir = "ASC"
    elif body.sort_by == "x_desc":
        sort_col = x_expr
        sort_dir = "DESC"
    else:
        sort_col = x_expr
        sort_dir = "ASC"
    order_sql = f" ORDER BY {sort_col} {sort_dir}"

    # LIMIT
    limit_sql = f" LIMIT {body.limit}" if body.limit and body.limit > 0 else ""

    sql = f"SELECT {', '.join(select_parts)} FROM {table}{where_sql}{group_sql}{order_sql}{limit_sql}"
    return sql


def _build_where(filters: list[WidgetFilter]) -> list[str]:
    """Build WHERE clause parts from filter definitions."""
    clauses: list[str] = []
    for f in filters:
        col = _quote_ident(f.column)
        op = f.operator
        val = f.value

        if op == "eq":
            clauses.append(f"{col} = {_sql_val(val)}")
        elif op == "neq":
            clauses.append(f"{col} != {_sql_val(val)}")
        elif op == "gt":
            clauses.append(f"{col} > {_sql_val(val)}")
        elif op == "lt":
            clauses.append(f"{col} < {_sql_val(val)}")
        elif op == "gte":
            clauses.append(f"{col} >= {_sql_val(val)}")
        elif op == "lte":
            clauses.append(f"{col} <= {_sql_val(val)}")
        elif op == "between" and f.value2 is not None:
            clauses.append(f"{col} BETWEEN {_sql_val(val)} AND {_sql_val(f.value2)}")
        elif op == "in":
            if isinstance(val, list):
                vals = ", ".join(_sql_val(v) for v in val)
                clauses.append(f"{col} IN ({vals})")
            else:
                # comma-separated string
                parts = [v.strip() for v in str(val).split(",") if v.strip()]
                vals = ", ".join(_sql_val(v) for v in parts)
                clauses.append(f"{col} IN ({vals})")
        elif op == "not_in":
            if isinstance(val, list):
                vals = ", ".join(_sql_val(v) for v in val)
                clauses.append(f"{col} NOT IN ({vals})")
            else:
                parts = [v.strip() for v in str(val).split(",") if v.strip()]
                vals = ", ".join(_sql_val(v) for v in parts)
                clauses.append(f"{col} NOT IN ({vals})")
        elif op == "contains":
            clauses.append(f"{col} LIKE {_sql_val(f'%{val}%')}")
        elif op == "begins_with":
            clauses.append(f"{col} LIKE {_sql_val(f'{val}%')}")
        elif op == "ends_with":
            clauses.append(f"{col} LIKE {_sql_val(f'%{val}')}")
        elif op == "like":
            clauses.append(f"{col} LIKE {_sql_val(val)}")
    return clauses


def _quote_ident(name: str) -> str:
    """Quote a column/table identifier for safe SQL inclusion."""
    safe = name.replace('"', '""')
    return f'"{safe}"'


def _sql_val(val: Any) -> str:
    """Format a value for safe SQL inclusion."""
    if val is None:
        return "NULL"
    if isinstance(val, int | float):
        return str(val)
    # String — escape single quotes
    s = str(val).replace("'", "''")
    return f"'{s}'"


# ── Shared helpers ───────────────────────────────────────────────────

async def _resolve_vdb(
    *,
    session: AsyncSession,
    context: RequestContext,
    project_id: int,
) -> str:
    """Resolve the Teiid database name for a project/user."""
    from app.models.project import Project as ProjectModel

    target_user_id = context.user_id
    project = await session.get(ProjectModel, project_id)
    if project is not None and project.is_shared and project.owner_id:
        target_user_id = project.owner_id

    user_vdb = await session.scalar(
        select(UserVDB).where(
            UserVDB.tenant_id == context.tenant_id,
            UserVDB.user_id == target_user_id,
        )
    )
    if user_vdb is None:
        raise HTTPException(status_code=404, detail="No VDB configured for this project.")
    if not user_vdb.is_active:
        raise HTTPException(status_code=503, detail="VDB is not active.")
    return f"{user_vdb.vdb_id}.1"


async def _run_widget_sql(
    *,
    database: str,
    sql: str,
    teiid_host: str,
    teiid_port: int,
) -> dict[str, Any]:
    """Execute SQL against Teiid and return {columns, rows}."""
    from app.config import get_settings

    settings = get_settings()
    host = teiid_host or settings.teiid_pg_host
    port = teiid_port or settings.teiid_pg_port

    try:
        pool = await pool_manager.get_pool(
            host=host, port=port, database=database,
            username="test", password="test",
        )
        async with pool.acquire() as conn:
            records = list(await conn.fetch(sql))
    except Exception as exc:
        logger.error("Widget query failed: %s | SQL: %s", exc, sql)
        raise HTTPException(status_code=502, detail=f"Query failed: {exc}") from exc

    if records:
        columns = list(records[0].keys())
        rows = [dict(record) for record in records]
        # Convert non-serializable types to strings
        for row in rows:
            for k, v in row.items():
                if not isinstance(v, str | int | float | bool | type(None)):
                    row[k] = str(v)
    else:
        columns = []
        rows = []
    return {"columns": columns, "rows": rows}
