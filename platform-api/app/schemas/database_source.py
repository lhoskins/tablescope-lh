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
