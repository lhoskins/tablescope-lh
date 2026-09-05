"""SaaS connector interface and shared value types.

A connector turns a SaaS app into something Tablescope can treat like a
database table: it can authenticate, enumerate objects and fields, preview
records, and fetch records for syncing into a Postgres staging table.

The staging table is created by ``saas_staging_service`` from the connector's
``base_columns()`` plus the user-selected fields, and is then registered in
Teiid by ``saas_source_service`` through the existing database-table pipeline.

The special key :data:`RAW_JSON_KEY` is reserved: each fetched record carries
the full source payload under this key so no data is lost even when only a few
fields are projected into typed columns.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

# Reserved staging column that stores the full source record as JSONB.
RAW_JSON_KEY = "raw_json"


class SaasConnectorError(Exception):
    """User-facing connector failure (safe message, never leaks secrets).

    ``requires_reauth`` marks a connection failure that the stored
    credential itself cannot recover from -- an expired/revoked OAuth token
    or rejected username/password -- as opposed to a transient/network
    error. A caller uses this to prompt the user to reconnect the
    connector instead of surfacing a dead-end error.
    """

    def __init__(self, message: str, *, requires_reauth: bool = False) -> None:
        super().__init__(message)
        self.requires_reauth = requires_reauth


@dataclass(frozen=True)
class ObjectInfo:
    """A selectable SaaS object (e.g. HubSpot ``contacts``)."""

    name: str
    label: str


@dataclass(frozen=True)
class FieldInfo:
    """A field/property of a SaaS object."""

    name: str
    label: str
    saas_type: str
    # Postgres column type to use for this field in the staging table.
    pg_type: str


@dataclass(frozen=True)
class StagingColumn:
    """A column in the local Postgres staging table."""

    name: str
    pg_type: str
    primary_key: bool = False


@dataclass(frozen=True)
class PreviewResult:
    columns: list[str]
    rows: list[dict]


class SaasConnector(ABC):
    """Base class for SaaS connectors.

    ``config`` is the decrypted credential bundle (a plain dict).  Implementations
    must never log secrets and should raise :class:`SaasConnectorError` with a
    safe message on failure.
    """

    connector_type: str = ""

    @abstractmethod
    async def test_connection(self, config: dict) -> dict:
        """Verify credentials.  Returns a small dict of account info."""

    @abstractmethod
    async def list_objects(self, config: dict) -> list[ObjectInfo]:
        """Return the objects the user may turn into data sources."""

    @abstractmethod
    async def list_fields(self, config: dict, object_type: str) -> list[FieldInfo]:
        """Return the available fields/properties for an object."""

    @abstractmethod
    def base_columns(self, object_type: str) -> list[StagingColumn]:
        """System columns every staging table for this object gets.

        Must include the primary-key id column.  ``RAW_JSON_KEY`` is appended by
        the staging service and should NOT be returned here.
        """

    @abstractmethod
    def id_column(self, object_type: str) -> str:
        """Name of the primary-key staging column for upserts."""

    @abstractmethod
    async def fetch_records(
        self,
        config: dict,
        object_type: str,
        selected_fields: list[str],
        *,
        limit: int | None = None,
    ) -> list[dict]:
        """Fetch records as staging-column-keyed dicts.

        Each dict is keyed by staging column name (id column, base columns and
        each selected field) and carries the full source payload under
        :data:`RAW_JSON_KEY`.  ``limit`` caps the total number of records.
        """

    async def preview(
        self,
        config: dict,
        object_type: str,
        selected_fields: list[str],
        *,
        limit: int = 20,
    ) -> PreviewResult:
        """Default preview: fetch a few records and project selected fields."""
        records = await self.fetch_records(
            config, object_type, selected_fields, limit=limit
        )
        columns = [self.id_column(object_type), *selected_fields]
        rows = [{c: rec.get(c) for c in columns} for rec in records]
        return PreviewResult(columns=columns, rows=rows)
