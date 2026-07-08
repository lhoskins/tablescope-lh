"""Schemas for scope sets and the Scope Relationship Builder map."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ScopeSetCreate(BaseModel):
    name: str
    description: str | None = None
    type: str = "manual"


class ScopeSetUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    enabled: bool | None = None


class ScopeSetRead(BaseModel):
    id: int
    tenant_id: int
    project_id: int
    name: str
    description: str | None = None
    type: str
    enabled: bool
    created_by: int | None = None
    creator_name: str | None = None
    creator_email: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    can_delete: bool = False
    scope_count: int = 0


class ScopeCanvasTable(BaseModel):
    """A table card placed on the builder canvas."""

    table_key: str
    table_name: str | None = None
    query_id: int | None = None
    datasource_id: int | None = None
    x_position: float = 0.0
    y_position: float = 0.0
    width: float | None = None
    height: float | None = None


class ScopeRelationship(BaseModel):
    """One field-to-field drill-down line on the canvas."""

    id: int | None = None
    query_id: int
    source_field: str
    source_table: str | None = None
    target_query_id: int
    target_field: str
    target_table: str | None = None
    direction: str = "source_to_target"
    match_group_id: str | None = None
    match_mode: str = "all"
    enabled: bool = True
    confidence_score: float | None = None
    created_by_ai: bool = False


class ScopeMapRead(BaseModel):
    """Everything the builder needs to render an existing scope set."""

    scope_set: ScopeSetRead
    tables: list[ScopeCanvasTable]
    relationships: list[ScopeRelationship]


class ScopeMapSave(BaseModel):
    """Full save payload for the builder (PUT /scope_sets/:id/map)."""

    name: str | None = None
    description: str | None = None
    enabled: bool | None = None
    tables: list[ScopeCanvasTable] = Field(default_factory=list)
    relationships: list[ScopeRelationship] = Field(default_factory=list)


class ScopeBuilderField(BaseModel):
    name: str


class ScopeBuilderTable(BaseModel):
    """A draggable table/query in the builder's left sidebar."""

    table_key: str
    table_name: str
    query_id: int | None = None
    datasource_id: int | None = None
    fields: list[str] = Field(default_factory=list)


class ScopeAISuggestRequest(BaseModel):
    """Tables currently on the canvas to run AI suggestion against."""

    query_ids: list[int] = Field(default_factory=list)


class ScopeAISuggestion(BaseModel):
    query_id: int
    source_field: str
    source_table: str | None = None
    target_query_id: int
    target_field: str
    target_table: str | None = None
    match_group_id: str | None = None
    match_mode: str = "all"
    confidence_score: float | None = None
    rationale: str | None = None


class ScopeAISuggestResponse(BaseModel):
    suggestions: list[ScopeAISuggestion]
