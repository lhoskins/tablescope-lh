"""Pydantic schemas for DB Admin data source assignments (issue 5)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AssignableSource(BaseModel):
    """A configured datasource an admin may assign to users."""

    database_data_source_id: int
    database_connection_id: int | None = None
    display_name: str
    db_type: str
    host: str
    database_name: str
    table_name: str


class AssignableUser(BaseModel):
    id: int
    email: str
    display_name: str | None = None
    role: str


class AssignmentCreate(BaseModel):
    database_data_source_id: int
    assigned_user_ids: list[int] = Field(default_factory=list, min_length=1)
    friendly_name: str = Field(min_length=1)
    read_only: bool = True


class AssignmentUpdate(BaseModel):
    friendly_name: str | None = None
    read_only: bool | None = None
    is_active: bool | None = None


class AssignmentRead(BaseModel):
    id: int
    database_data_source_id: int
    database_connection_id: int | None = None
    assigned_user_id: int
    assigned_user_email: str | None = None
    assigned_user_name: str | None = None
    friendly_name: str
    read_only: bool
    is_active: bool
    assigned_by: int | None = None
    assigned_by_name: str | None = None
    datasource_name: str | None = None
    db_type: str | None = None
    created_at: str | None = None


class ConnectedSource(BaseModel):
    """Unified "Connected Databases" item: owned connection or assigned source."""

    id: str
    source: str  # "owned" | "assigned"
    database_data_source_id: int | None = None
    database_connection_id: int | None = None
    display_name: str
    db_type: str
    host: str
    database: str
    read_only: bool = False
    assigned_by: str | None = None
    can_edit_connection: bool = True
    can_select: bool = True
