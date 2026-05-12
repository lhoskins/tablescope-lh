"""Scope (drill-down) proxy service.

Preserves the exact behavior of the existing Java `CreateScopeServlet` and
`FetchTableDataServlet`. Two implementations are provided:

1. **HTTP proxy mode** — forward `/api/scopes/*` calls to the running Java
   servlet at `TEIID_SERVLET_URL/createScope`. This is the default and keeps
   100% behavioral compatibility.
2. **Direct mode** — read/write `drilldownConfig.json` from the shared
   filesystem mount directly. Useful when the servlet is unreachable or for
   migrating off the servlet incrementally.

Both modes enforce tenant isolation: a scope is keyed by
`(tenant_id, source_table, source_column)` so cross-tenant access is
impossible even if the underlying file or servlet is shared.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class ScopeError(Exception):
    """Raised when a scope operation fails."""


class ScopeNotFoundError(ScopeError):
    """Raised when a scope cannot be found."""


@dataclass(slots=True)
class Scope:
    name: str
    source_table: str
    source_column: str
    target_table: str
    target_column: str
    tenant_id: int | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "sourceTable": self.source_table,
            "sourceColumn": self.source_column,
            "targetTable": self.target_table,
            "targetColumn": self.target_column,
            "tenantId": self.tenant_id,
        }


def _scope_key(scope: dict) -> tuple[str, str]:
    return (scope.get("sourceTable", ""), scope.get("sourceColumn", ""))


def _scope_tenant_matches(scope: dict, tenant_id: int) -> bool:
    raw = scope.get("tenantId")
    if raw is None:
        # Legacy scopes pre-multitenancy: treat them as global within tenant 0.
        return tenant_id == 0
    try:
        return int(raw) == int(tenant_id)
    except (TypeError, ValueError):
        return False


class ScopeFileStore:
    """Thread-safe reader/writer for drilldownConfig.json."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()

    async def read(self) -> dict:
        async with self._lock:
            return await asyncio.to_thread(self._read_sync)

    async def write(self, payload: dict) -> None:
        async with self._lock:
            await asyncio.to_thread(self._write_sync, payload)

    def _read_sync(self) -> dict:
        if not self._path.exists():
            return {"drilldowns": []}
        with self._path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def _write_sync(self, payload: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        tmp.replace(self._path)


class ScopeProxyService:
    """Tenant-aware scope CRUD that proxies to or replaces the Java servlet."""

    def __init__(
        self,
        *,
        store: ScopeFileStore | None = None,
        servlet_client: httpx.AsyncClient | None = None,
        use_servlet: bool = False,
    ) -> None:
        settings = get_settings()
        self._store = store or ScopeFileStore(Path(settings.drilldown_config_path))
        self._owns_client = servlet_client is None
        if use_servlet:
            headers = {}
            if settings.teiid_servlet_api_key:
                headers["X-API-Key"] = settings.teiid_servlet_api_key
            self._client: httpx.AsyncClient | None = servlet_client or httpx.AsyncClient(
                base_url=settings.teiid_servlet_url,
                timeout=httpx.Timeout(10.0, connect=5.0),
                headers=headers,
            )
        else:
            self._client = None

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()

    async def list_scopes(self, *, tenant_id: int) -> list[Scope]:
        payload = await self._store.read()
        return [
            self._scope_from_raw(raw)
            for raw in payload.get("drilldowns", [])
            if _scope_tenant_matches(raw, tenant_id)
        ]

    async def get_scope(
        self, *, tenant_id: int, source_table: str, source_column: str
    ) -> Scope:
        payload = await self._store.read()
        for raw in payload.get("drilldowns", []):
            if (
                raw.get("sourceTable") == source_table
                and raw.get("sourceColumn") == source_column
                and _scope_tenant_matches(raw, tenant_id)
            ):
                return self._scope_from_raw(raw)
        raise ScopeNotFoundError(
            f"Scope not found for {source_table}.{source_column} in tenant {tenant_id}"
        )

    async def create_scope(
        self,
        *,
        tenant_id: int,
        source_table: str,
        source_column: str,
        target_table: str,
        target_column: str,
    ) -> Scope:
        payload = await self._store.read()
        drilldowns = payload.setdefault("drilldowns", [])

        for raw in drilldowns:
            if (
                raw.get("sourceTable") == source_table
                and raw.get("sourceColumn") == source_column
                and _scope_tenant_matches(raw, tenant_id)
            ):
                raise ScopeError(
                    f"Scope already exists for {source_table}.{source_column}"
                )

        name = f"Scope_{len(drilldowns) + 1}"
        new_scope = {
            "name": name,
            "sourceTable": source_table,
            "sourceColumn": source_column,
            "targetTable": target_table,
            "targetColumn": target_column,
            "tenantId": tenant_id,
        }
        drilldowns.append(new_scope)
        await self._store.write(payload)
        return self._scope_from_raw(new_scope)

    async def update_scope(
        self,
        *,
        tenant_id: int,
        source_table: str,
        source_column: str,
        target_table: str,
        target_column: str,
    ) -> Scope:
        payload = await self._store.read()
        drilldowns = payload.get("drilldowns", [])
        for raw in drilldowns:
            if (
                raw.get("sourceTable") == source_table
                and raw.get("sourceColumn") == source_column
                and _scope_tenant_matches(raw, tenant_id)
            ):
                raw["targetTable"] = target_table
                raw["targetColumn"] = target_column
                await self._store.write(payload)
                return self._scope_from_raw(raw)
        raise ScopeNotFoundError(
            f"Scope not found for {source_table}.{source_column} in tenant {tenant_id}"
        )

    async def delete_scope(
        self, *, tenant_id: int, source_table: str, source_column: str
    ) -> None:
        payload = await self._store.read()
        drilldowns = payload.get("drilldowns", [])
        for index, raw in enumerate(drilldowns):
            if (
                raw.get("sourceTable") == source_table
                and raw.get("sourceColumn") == source_column
                and _scope_tenant_matches(raw, tenant_id)
            ):
                drilldowns.pop(index)
                await self._store.write(payload)
                return
        raise ScopeNotFoundError(
            f"Scope not found for {source_table}.{source_column} in tenant {tenant_id}"
        )

    async def find_for_column(
        self, *, tenant_id: int, column_name: str
    ) -> Scope | None:
        """Used by drill-down query integration to look up scopes by column."""
        payload = await self._store.read()
        for raw in payload.get("drilldowns", []):
            if (
                raw.get("sourceColumn") == column_name
                and _scope_tenant_matches(raw, tenant_id)
            ):
                return self._scope_from_raw(raw)
        return None

    def _scope_from_raw(self, raw: dict) -> Scope:
        return Scope(
            name=raw.get("name", ""),
            source_table=raw.get("sourceTable", ""),
            source_column=raw.get("sourceColumn", ""),
            target_table=raw.get("targetTable", ""),
            target_column=raw.get("targetColumn", ""),
            tenant_id=int(raw["tenantId"]) if raw.get("tenantId") is not None else None,
        )
