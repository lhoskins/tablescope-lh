"""Pydantic schemas for the database data-source wizard."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ConnectionBase(BaseModel):
    db_type: str = Field(..., examples=["postgresql"])
    host: str
    port: int | None = None
    database_name: str
    username: str
    password: str
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
