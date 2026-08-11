"""Executes queries against Teiid via asyncpg, with drill-down support.

Mirrors `FetchTableDataServlet`:

- `SELECT * FROM <table>` for normal table fetches.
- If a scope is configured for the column, swap in
  `SELECT * FROM <target_table> WHERE <target_column> = $1` instead.

Inputs are validated to prevent SQL injection: table and column names are
restricted to identifier characters; value bindings use parameterized queries.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import asyncpg

from app.auth.context import RequestContext
from app.services.connection_pool import pool_manager
from app.services.scope_proxy import ScopeProxyService
from app.services.vdb_routing import VDBConnectionInfo, VDBRoutingService

logger = logging.getLogger(__name__)


# Allow a leading digit: file views like "0_revenueTest_CSV" are valid view
# names and are always quoted when interpolated into SQL.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_$.]*$")


class QueryValidationError(Exception):
    """Raised when input identifiers fail validation."""


@dataclass(slots=True)
class QueryResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    drilldown_used: bool
    target_table: str | None = None
    target_column: str | None = None


def _validate_identifier(name: str, *, kind: str) -> str:
    if not _IDENTIFIER_RE.match(name):
        raise QueryValidationError(f"Invalid {kind}: {name!r}")
    return name


class TeiidQueryExecutor:
    """Runs SELECT statements against a tenant's VDB."""

    def __init__(
        self,
        *,
        routing: VDBRoutingService | None = None,
        scopes: ScopeProxyService,
    ) -> None:
        self._routing = routing
        self._scopes = scopes

    async def fetch_table_data(
        self,
        *,
        context: RequestContext,
        project_id: int,
        table_name: str,
        column_name: str | None = None,
        value: str | None = None,
        limit: int = 1000,
        teiid_host: str | None = None,
        teiid_port: int | None = None,
        connection_info: VDBConnectionInfo | None = None,
    ) -> QueryResult:
        _validate_identifier(table_name, kind="table")
        if column_name is not None:
            _validate_identifier(column_name, kind="column")

        if connection_info is None:
            if self._routing is None:
                raise RuntimeError("VDBRoutingService is required when connection_info is not provided")
            connection_info = await self._routing.get_connection_info(
                context=context, project_id=project_id
            )

        drill_target_table: str | None = None
        drill_target_column: str | None = None
        if column_name and value is not None:
            scope = await self._scopes.find_for_column(
                tenant_id=context.tenant_id, column_name=column_name
            )
            if scope is not None:
                drill_target_table = _validate_identifier(scope.target_table, kind="target table")
                drill_target_column = _validate_identifier(scope.target_column, kind="target column")

        if drill_target_table is not None and drill_target_column is not None:
            sql = f'SELECT * FROM "{drill_target_table}" WHERE "{drill_target_column}" = $1 LIMIT $2'
            params: tuple[Any, ...] = (value, limit)
        else:
            sql = f'SELECT * FROM "{table_name}" LIMIT $1'
            params = (limit,)

        # A tenant bound to a dedicated data plane is routed to its own Teiid
        # container; otherwise we use the VDB row's host/port (shared global).
        pool = await pool_manager.get_pool(
            host=teiid_host or connection_info.host,
            port=teiid_port or connection_info.port,
            database=connection_info.database,
            username=connection_info.username,
            password=connection_info.password,
        )

        async with pool.acquire() as conn:
            records: list[asyncpg.Record] = await conn.fetch(sql, *params)

        columns: list[str] = list(records[0].keys()) if records else []
        rows = [dict(record) for record in records]

        return QueryResult(
            columns=columns,
            rows=rows,
            drilldown_used=drill_target_table is not None,
            target_table=drill_target_table,
            target_column=drill_target_column,
        )
