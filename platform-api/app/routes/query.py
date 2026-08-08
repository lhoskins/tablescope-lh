"""Query execution routes.

SQL building/execution helpers live in :mod:`app.routes.query_sql_helpers` and
are re-exported here: several modules (and their tests) reach them through
``app.routes.query``.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.membership import require_membership
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.routes.query_sql_helpers import (
    _auto_cast_aggregates,
    _cast_timestampdiff,
    _execute_sql_with_repair,
    _prepare_sql,
    _resolve_vdb_database,
    _run_sql,
    _sample_project_columns,
)
from app.schemas.query import QueryRequest, QueryResponse
from app.services.query_executor import (
    QueryValidationError,
    TeiidQueryExecutor,
)
from app.services.scope_proxy import ScopeProxyService
from app.services.teiid_sql import project_table_schema
from app.services.tenant_teiid_resolver import TenantTeiidResolver
from app.services.vdb_routing import (
    VDBInactiveError,
    VDBNotConfiguredError,
    VDBNotFoundError,
    VDBRoutingService,
)
from app.services.visualization_engine import select_visualization

__all__ = [
    "DatasourceQueryRequest",
    "_auto_cast_aggregates",
    "_cast_timestampdiff",
    "_execute_sql_with_repair",
    "_prepare_sql",
    "_resolve_vdb_database",
    "_run_sql",
    "_sample_project_columns",
    "fetch_table_data",
    "query_datasource",
    "router",
]

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/query", tags=["query"])

# View names can start with a digit (e.g. a file named "0_revenue.csv" maps to
# the view "0_revenueTest_CSV"); the name is always emitted inside double quotes
# in generated SQL, so a leading digit is safe.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_$.]*$")


class DatasourceQueryRequest(BaseModel):
    # Optional when an explicit ``sql`` is supplied (e.g. previewing a saved /
    # suggested query); required only for the plain ``SELECT * FROM table`` path.
    tableName: str | None = Field(default=None)
    limit: int = Field(default=1000, ge=1, le=10_000)
    project_id: int | None = Field(default=None)
    sql: str | None = Field(default=None)


@router.post("/fetch", response_model=QueryResponse)
async def fetch_table_data(
    payload: QueryRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_membership),
) -> QueryResponse:
    routing = VDBRoutingService(session)
    scopes = ScopeProxyService()
    executor = TeiidQueryExecutor(routing=routing, scopes=scopes)
    endpoint = await TenantTeiidResolver(session).resolve_for_org(context.tenant_id)
    try:
        result = await executor.fetch_table_data(
            context=context,
            project_id=payload.projectId,
            table_name=payload.tableName,
            column_name=payload.columnName,
            value=payload.value,
            limit=payload.limit,
            teiid_host=endpoint.pg_host,
            teiid_port=endpoint.pg_port,
        )
    except QueryValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (VDBNotConfiguredError, VDBNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VDBInactiveError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        await scopes.aclose()

    return QueryResponse(
        columns=result.columns,
        rows=result.rows,
        drilldownUsed=result.drilldown_used,
        targetTable=result.target_table,
        targetColumn=result.target_column,
    )


@router.post("/datasource")
async def query_datasource(
    payload: DatasourceQueryRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Query a datasource (view) from the appropriate VDB.

    When project_id is provided and the project is shared, the query runs
    against the project owner's VDB (where the views live). Otherwise it
    queries the current user's personal VDB.

    Generated SQL is normalized against the project schema and, if it still
    fails, repaired through the AI ``fix-sql`` endpoint so preview modals render
    rather than surfacing raw Teiid errors.
    """
    if not payload.sql and not (
        payload.tableName and _IDENTIFIER_RE.match(payload.tableName)
    ):
        raise HTTPException(
            status_code=400, detail=f"Invalid table name: {payload.tableName!r}"
        )

    database = await _resolve_vdb_database(
        session=session, context=context, project_id=payload.project_id
    )

    endpoint = await TenantTeiidResolver(session).resolve_for_org(context.tenant_id)

    table_schema: list[dict[str, Any]] = []
    allowed_tables: list[str] = []
    column_types: dict[str, str] = {}
    column_samples: dict[str, str] = {}

    project_id = payload.project_id
    if project_id:
        table_schema = await project_table_schema(
            session, tenant_id=context.tenant_id, project_id=project_id
        )
        allowed_tables = [
            str(t)
            for entry in table_schema
            if (t := entry.get("table")) is not None
        ]
        column_types = {
            str(col.get("name")): str(col.get("type") or "")
            for entry in table_schema
            for col in (entry.get("columns") or [])
            if isinstance(col, dict) and col.get("name")
        }
        column_samples = await _sample_project_columns(
            database=database,
            tables=allowed_tables,
            teiid_host=endpoint.pg_host,
            teiid_port=endpoint.pg_port,
        )

    if payload.sql:
        if project_id is None:
            raise HTTPException(
                status_code=400, detail="project_id is required when executing SQL"
            )
        result, final_sql = await _execute_sql_with_repair(
            raw_sql=payload.sql,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            project_id=project_id,
            database=database,
            endpoint=endpoint,
            table_schema=table_schema,
            allowed_tables=allowed_tables,
            column_types=column_types,
            column_samples=column_samples,
        )
    else:
        sql = f'SELECT * FROM "{payload.tableName}" LIMIT {payload.limit}'
        result = await _run_sql(
            database=database,
            sql=sql,
            teiid_host=endpoint.pg_host,
            teiid_port=endpoint.pg_port,
        )
        final_sql = sql

    if result is None:
        raise HTTPException(status_code=502, detail=f"Query failed: {final_sql}")

    # Attach a data-driven visualization suggestion so preview surfaces render
    # the right chart family instead of a hardcoded bar.
    if payload.sql and result.get("columns"):
        decision = select_visualization(result["columns"], result.get("rows", []))
        viz = decision.to_dict()
        result["suggestedVisualization"] = {
            "type": viz.get("chartType", "table"),
            "chartStyle": viz.get("chartStyle"),
            "xField": viz.get("xField"),
            "yField": viz.get("yField"),
            "metricField": viz.get("metricField"),
            "topN": viz.get("topN"),
        }
        result["sql"] = final_sql

    return result
