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


class LicenseApprovalSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    license_type: str | None
    license_url: str | None
    notes: str | None
    approved_at: datetime | None


class ModelArtifactSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    publisher: str
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
    license_approval: LicenseApprovalSummary | None


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


class CatalogFileResult(BaseModel):
    filename: str
    size: int | None
    lfs: bool


class CatalogSearchResult(BaseModel):
    repo_id: str
    publisher: str
    name: str
    tags: list[str]
    license: str | None
    description: str | None
    downloads: int | None
    likes: int | None
    last_modified: str | None
    gguf_files: list[CatalogFileResult]
    gguf_total_bytes: int | None


class CatalogDetail(CatalogSearchResult):
    commit_sha: str | None
    siblings: list[CatalogFileResult]
    license_url: str | None


class StageArtifactRequest(BaseModel):
    repo_url: str
    quantization: str | None = None
    name: str | None = None


class StageArtifactResponse(BaseModel):
    artifact_id: int
    job_id: str
    status: str


class PreflightResponse(BaseModel):
    artifact_id: int
    target_id: int
    target_reachable: bool
    disk_ok: bool
    slot_ok: bool
    detail: str | None


class InstallRequest(BaseModel):
    target_id: int


class InstallResponse(BaseModel):
    installation_id: int
    deployment_id: int
    status: str
    job_id: str | None = None


class DeploymentResponse(BaseModel):
    id: int
    installation_id: int
    requested_by_user_id: int | None
    approved_by_user_id: int | None
    status: str
    previous_deployment_id: int | None
    stabilized_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ApproveDeploymentResponse(BaseModel):
    deployment_id: int
    status: str


class ActivateRequest(BaseModel):
    capability: str
    target_id: int


class ActivateResponse(BaseModel):
    deployment_id: int
    status: str
    capability: str
    target_id: int


class RollbackResponse(BaseModel):
    deployment_id: int
    status: str


class RoutingProfileRequest(BaseModel):
    capability: str
    target_id: int
    installation_id: int
    priority: int = 1
    is_active: bool = True
    expected_version: int | None = None  # optimistic concurrency placeholder


class RoutingProfileResponse(RoutingProfileSummary):
    pass


class ReindexRequest(BaseModel):
    tenant_id: int
    embedding_model: str
    embedding_dim: int


class ReindexResponse(BaseModel):
    migration_id: int
    status: str
    job_id: str | None = None
    points_total: int | None = None
    points_indexed: int | None = None
    recall_score: float | None = None


class ConvertRequest(BaseModel):
    repo_url: str
    quantization: str | None = None
    converter_version: str | None = None


class ConvertResponse(BaseModel):
    source_artifact_id: int
    conversion_id: int
    status: str
    job_id: str | None = None


class EmbeddingMigrationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    artifact_id: int
    source_collection: str
    target_collection: str
    embedding_model: str
    embedding_dim: int
    status: str
    recall_score: float | None
    points_total: int | None
    points_indexed: int | None
    created_at: datetime
    updated_at: datetime


class ModelConversionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_artifact_id: int
    output_artifact_id: int | None
    quantization: str | None
    status: str
    converter_version: str | None
    output_size_bytes: int | None
    created_at: datetime
    updated_at: datetime
