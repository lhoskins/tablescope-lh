"""LLM Framework inventory and deployment models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

_JSON = JSONB().with_variant(JSON(), "sqlite")


class LLMRoutingCapability(StrEnum):
    """Routable capability labels for LLM routing profiles.

    ``embedding`` is deliberately excluded: ``EMBEDDING_DIM`` is a per-collection
    constant in Qdrant, so swapping an embedding model silently degrades retrieval
    without raising an error. It is handled as a separate re-index migration.
    """

    GENERAL_REASONING = "general_reasoning"
    SQL_GENERATION = "sql_generation"
    INSIGHT_INTERPRETATION = "insight_interpretation"
    DASHBOARD_PLANNING = "dashboard_planning"


ROUTING_CAPABILITIES: list[str] = [c.value for c in LLMRoutingCapability]

_CAPABILITY_IN_SQL = ", ".join(f"'{c.value}'" for c in LLMRoutingCapability)


class LLMRuntimeTarget(TimestampMixin, Base):
    __tablename__ = "llm_runtime_targets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    runtime_type: Mapped[str] = mapped_column(String(32), nullable=False, default="ollama")
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    is_reachable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_loaded_models: Mapped[int | None] = mapped_column(Integer, nullable=True)
    keep_alive_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    labels: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)

    installations: Mapped[list[LLMInstallation]] = relationship(back_populates="target")
    routing_profiles: Mapped[list[LLMRoutingProfile]] = relationship(back_populates="target")


class LLMModelArtifact(TimestampMixin, Base):
    __tablename__ = "llm_model_artifacts"

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'downloading', 'verifying', 'staged', 'verified', 'quarantined', 'failed')",
            name="ck_llm_model_artifacts_status",
        ),
        CheckConstraint(
            "format = 'gguf'",
            name="ck_llm_model_artifacts_format_gguf",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    publisher: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    repo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    quantization: Mapped[str | None] = mapped_column(String(32), nullable=True)
    format: Mapped[str] = mapped_column(String(32), nullable=False, default="gguf")
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    manifest: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
    manifest_signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    manifest_public_key_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    quarantine_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    staged_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    verified_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    files: Mapped[list[LLMArtifactFile]] = relationship(
        back_populates="artifact",
        cascade="all, delete-orphan",
    )
    installations: Mapped[list[LLMInstallation]] = relationship(back_populates="artifact")
    license_approval: Mapped[LLMLicenseApproval | None] = relationship(
        back_populates="artifact",
        uselist=False,
    )


class LLMArtifactFile(TimestampMixin, Base):
    __tablename__ = "llm_artifact_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    artifact_id: Mapped[int] = mapped_column(
        ForeignKey("llm_model_artifacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    hash_algorithm: Mapped[str] = mapped_column(String(32), nullable=False, default="sha256")
    hash_value: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    artifact: Mapped[LLMModelArtifact] = relationship(back_populates="files")


class LLMLicenseApproval(TimestampMixin, Base):
    __tablename__ = "llm_license_approvals"

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'review_required', 'approved', 'rejected')",
            name="ck_llm_license_approvals_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    artifact_id: Mapped[int] = mapped_column(
        ForeignKey("llm_model_artifacts.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    license_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    license_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    license_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    approved_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    artifact: Mapped[LLMModelArtifact] = relationship(back_populates="license_approval")


class LLMInstallation(TimestampMixin, Base):
    __tablename__ = "llm_installations"

    id: Mapped[int] = mapped_column(primary_key=True)
    artifact_id: Mapped[int] = mapped_column(
        ForeignKey("llm_model_artifacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_id: Mapped[int] = mapped_column(
        ForeignKey("llm_runtime_targets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="staged")
    installed_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    modelfile_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    installed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    previous_installation_id: Mapped[int | None] = mapped_column(
        ForeignKey("llm_installations.id", ondelete="SET NULL"), nullable=True
    )

    artifact: Mapped[LLMModelArtifact] = relationship(back_populates="installations")
    target: Mapped[LLMRuntimeTarget] = relationship(back_populates="installations")
    deployments: Mapped[list[LLMDeployment]] = relationship(back_populates="installation")
    routing_profiles: Mapped[list[LLMRoutingProfile]] = relationship(back_populates="installation")


class LLMRoutingProfile(TimestampMixin, Base):
    __tablename__ = "llm_routing_profiles"

    __table_args__ = (
        CheckConstraint(
            f"capability IN ({_CAPABILITY_IN_SQL})",
            name="ck_llm_routing_profiles_capability",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    capability: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_id: Mapped[int] = mapped_column(
        ForeignKey("llm_runtime_targets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    installation_id: Mapped[int | None] = mapped_column(
        ForeignKey("llm_installations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    config: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)

    target: Mapped[LLMRuntimeTarget] = relationship(back_populates="routing_profiles")
    installation: Mapped[LLMInstallation | None] = relationship(back_populates="routing_profiles")


class LLMDeployment(TimestampMixin, Base):
    __tablename__ = "llm_deployments"

    id: Mapped[int] = mapped_column(primary_key=True)
    installation_id: Mapped[int] = mapped_column(
        ForeignKey("llm_installations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    previous_deployment_id: Mapped[int | None] = mapped_column(
        ForeignKey("llm_deployments.id", ondelete="SET NULL"), nullable=True
    )
    stabilization_window_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stabilized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    installation: Mapped[LLMInstallation] = relationship(back_populates="deployments")
    attempts: Mapped[list[LLMDeploymentAttempt]] = relationship(
        back_populates="deployment",
        cascade="all, delete-orphan",
    )


class LLMDeploymentAttempt(TimestampMixin, Base):
    __tablename__ = "llm_deployment_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    deployment_id: Mapped[int] = mapped_column(
        ForeignKey("llm_deployments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    deployment: Mapped[LLMDeployment] = relationship(back_populates="attempts")


class LLMAuditEvent(Base):
    __tablename__ = "llm_audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="now()",
        nullable=False,
    )
