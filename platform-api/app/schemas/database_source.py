"""Pydantic schemas for the database data-source wizard."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ConnectionBase(BaseModel):
    """Connection parameters for a database wizard step.

    Either supply the inline fields (db_type/host/.../password) OR a
    ``connection_id`` referencing a previously saved connection profile, in
    which case the stored (encrypted) credentials are used and the inline
    fields may be omitted.
    """

    connection_id: int | None = None
    db_type: str | None = Field(default=None, examples=["postgresql"])
    host: str | None = None
    port: int | None = None
    database_name: str | None = None
    username: str | None = None
    password: str | None = None
    ssl_mode: str | None = None


class SchemaRequest(ConnectionBase):
    pass


class TableRequest(ConnectionBase):
    schema_name: str | None = None


class ColumnRequest(ConnectionBase):
    schema_name: str | None = None
    table_name: str


class PreviewRequest(ConnectionBase):
    schema_name: str | None = None
    table_name: str
    limit: int = 20


class PreviewResponse(BaseModel):
    columns: list[str]
    rows: list[list[object]]


class CreateDatabaseSourceRequest(ConnectionBase):
    display_name: str
    schema_name: str | None = None
    table_name: str
    project_id: int | None = None
    # When set, persist the (encrypted) credentials as a reusable connection
    # profile so the user can add more tables without re-authenticating.
    save_connection: bool = False
    connection_name: str | None = None


class SaveConnectionRequest(ConnectionBase):
    name: str


class UpdateConnectionRequest(ConnectionBase):
    """Edit a saved connection profile.

    ``name`` and any connection field may be updated. When a new password is
    supplied it replaces the stored one; otherwise the existing password is
    retained. The connection is re-tested before the changes are persisted.
    """

    name: str | None = None


class SavedConnectionRead(BaseModel):
    id: int
    name: str
    db_type: str
    host: str
    port: int
    database_name: str
    username: str
    has_password: bool
    ssl_mode: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    last_tested_at: str | None = None


class TestConnectionResponse(BaseModel):
    success: bool
    message: str


class SchemasResponse(BaseModel):
    schemas: list[str]


class TableInfo(BaseModel):
    schema_name: str | None = None
    table_name: str
    type: str


class TablesResponse(BaseModel):
    tables: list[TableInfo]


class ColumnInfo(BaseModel):
    name: str
    type: str | None = None
    nullable: bool | None = None
    primary_key: bool = False
    ordinal_position: int | None = None


class ColumnsResponse(BaseModel):
    columns: list[ColumnInfo]
