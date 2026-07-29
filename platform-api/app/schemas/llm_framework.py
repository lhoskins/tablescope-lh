"""LLM Framework request/response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RuntimeTargetSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    runtime_type: str
    host: str
    version: str | None
    status: str
    is_reachable: bool
    last_seen_at: datetime | None
    max_loaded_models: int | None
    keep_alive_minutes: int | None
    labels: dict
    created_at: datetime
    updated_at: datetime


class ArtifactFileSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    size_bytes: int | None
    hash_algorithm: str
    hash_value: str


class ModelArtifactSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    publisher: str | None
    repo_url: str | None
    commit_sha: str | None
    quantization: str | None
    format: str
    size_bytes: int | None
    status: str
    manifest_public_key_fingerprint: str | None
    quarantine_reason: str | None
    verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ModelArtifactDetail(ModelArtifactSummary):
    files: list[ArtifactFileSummary]


class InstallationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    artifact_id: int
    target_id: int
    status: str
    installed_path: str | None
    installed_at: datetime | None
    activated_at: datetime | None
    rolled_back_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RoutingProfileSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    capability: str
    target_id: int
    installation_id: int | None
    is_active: bool
    priority: int
    config: dict
    created_at: datetime
    updated_at: datetime


class InventoryResponse(BaseModel):
    """Read-only LLM framework inventory."""

    targets: list[RuntimeTargetSummary]
    artifacts: list[ModelArtifactSummary]
    installations: list[InstallationSummary]
    routing_profiles: list[RoutingProfileSummary]


class CapabilitiesResponse(BaseModel):
    """Capabilities that may be routed by the framework."""

    capabilities: list[str]
    gguf_only: bool
    deployment_enabled: bool


class QuarantineReleaseResponse(BaseModel):
    """Result of releasing a quarantined artifact for re-verification."""

    artifact_id: int
    previous_status: str
    status: str
