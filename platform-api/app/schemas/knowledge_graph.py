"""Pydantic schemas for the knowledge graph lifecycle API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChangeSetItem(BaseModel):
    entity_type: str
    entity_id: int | None = None
    action: str = "updated"  # added | updated | removed | schema_change
    change_scope: str = "local"  # local | structural | schema
    details: dict[str, Any] | None = None


class IncrementalRebuildRequest(BaseModel):
    change_set: list[ChangeSetItem] = Field(default_factory=list)
    reason: str | None = None


class KnowledgeGraphBuildRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    graph_id: int
    tenant_id: int
    project_id: int
    trigger_type: str
    build_type: str
    requested_by: int | None
    status: str
    stage: str
    progress: int
    error_code: str | None
    safe_error_message: str | None
    retry_attempt: int
    worker_id: str | None
    candidate_version_id: int | None
    source_checkpoint: dict[str, Any] | None
    affected_entity_summary: dict[str, Any] | None
    # KG-48: per-stage duration breakdown (ms) + source counts, so an
    # operator can see which stage was slow or where a build failed without
    # reading raw logs.
    stage_metrics: dict[str, Any] | None = None
    queued_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class KnowledgeGraphVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    graph_id: int
    tenant_id: int
    project_id: int
    version_number: int
    build_id: int | None
    status: str
    build_type: str
    source_fingerprint: str | None
    node_count: int
    edge_count: int
    disconnected_component_count: int
    storage_reference: str | None
    created_by: int | None
    activated_at: datetime | None
    superseded_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # KG-11/KG-15: validation errors/warnings plus the per-source-type
    # coverage manifest (total/included/excluded/failed/pending), so a
    # "succeeded" build can never silently conceal truncated, failed, or
    # still-processing sources.
    validation_summary: dict[str, Any] | None = None


class KnowledgeGraphHealthCheckRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    graph_id: int | None
    version_id: int | None
    tenant_id: int
    project_id: int
    status: str
    check_type: str
    node_count: int
    edge_count: int
    orphan_ratio: float | None
    disconnected_components: int
    structural_checks: dict[str, Any] | None
    source_alignment: dict[str, Any] | None
    dependency_checks: dict[str, Any] | None
    source_coverage: dict[str, Any] | None
    warnings: list[str] | None
    errors: list[str] | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class KnowledgeGraphStatusRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: int
    graph_id: int | None
    lifecycle_status: str
    enabled: bool
    active_version_id: int | None
    active_version_number: int | None
    last_healthy_version_id: int | None
    last_healthy_version_number: int | None
    current_source_fingerprint: str | None
    active_source_fingerprint: str | None
    last_successful_build_at: datetime | None
    last_health_check_at: datetime | None
    active_node_count: int
    active_edge_count: int
    health_status: str
    has_active_version: bool
    builds: list[KnowledgeGraphBuildRead]
    versions: list[KnowledgeGraphVersionRead]


class KnowledgeGraphRebuildResponse(BaseModel):
    build: KnowledgeGraphBuildRead
    build_type: str
    enqueued: bool


class ExecutiveInsightDependencyRead(BaseModel):
    ready: bool
    mode: str  # full | limited | blocked
    graph_status: str
    graph_version_id: int | None
    graph_version_number: int | None
    active_node_count: int
    active_edge_count: int
    warnings: list[str]
    blocking_reasons: list[str]
    disclosure: str
