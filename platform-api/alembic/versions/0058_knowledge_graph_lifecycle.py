"""Knowledge graph lifecycle, versions, builds, and health checks.

Revision ID: 0058
Revises: 0057
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0058"
down_revision: str | None = "0057"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")


def _tables(conn: sa.engine.Connection) -> set[str]:
    return set(sa.inspect(conn).get_table_names())


def upgrade() -> None:
    conn = op.get_bind()

    if "knowledge_graphs" not in _tables(conn):
        op.create_table(
            "knowledge_graphs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("active_version_id", sa.Integer(), nullable=True),
            sa.Column("last_healthy_version_id", sa.Integer(), nullable=True),
            sa.Column("lifecycle_status", sa.String(50), nullable=False, server_default="missing"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("current_source_fingerprint", sa.Text(), nullable=True),
            sa.Column("last_successful_build_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_health_check_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_knowledge_graphs_tenant_project", "knowledge_graphs", ["tenant_id", "project_id"])
        op.create_unique_constraint("uq_knowledge_graphs_project", "knowledge_graphs", ["project_id"])

    if "knowledge_graph_versions" not in _tables(conn):
        op.create_table(
            "knowledge_graph_versions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("graph_id", sa.Integer(), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("build_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(50), nullable=False, server_default="candidate"),
            sa.Column("build_type", sa.String(50), nullable=False, server_default="full"),
            sa.Column("source_fingerprint", sa.Text(), nullable=True),
            sa.Column("node_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("edge_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("disconnected_component_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("validation_summary", _JSON, nullable=True),
            sa.Column("storage_reference", sa.String(255), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index(
            "ix_knowledge_graph_versions_project_version",
            "knowledge_graph_versions",
            ["project_id", "version_number"],
            unique=True,
        )
        op.create_index(
            "ix_knowledge_graph_versions_status",
            "knowledge_graph_versions",
            ["tenant_id", "project_id", "status"],
        )

    if "knowledge_graph_builds" not in _tables(conn):
        op.create_table(
            "knowledge_graph_builds",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("graph_id", sa.Integer(), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("trigger_type", sa.String(50), nullable=False, server_default="manual"),
            sa.Column("build_type", sa.String(50), nullable=False, server_default="full"),
            sa.Column("requested_by", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(50), nullable=False, server_default="queued"),
            sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("source_checkpoint", _JSON, nullable=True),
            sa.Column("affected_entity_summary", _JSON, nullable=True),
            sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("stage", sa.String(100), nullable=False, server_default="initializing"),
            sa.Column("error_code", sa.String(100), nullable=True),
            sa.Column("safe_error_message", sa.Text(), nullable=True),
            sa.Column("retry_attempt", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("worker_id", sa.String(255), nullable=True),
            sa.Column("candidate_version_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index(
            "ix_knowledge_graph_builds_project_status",
            "knowledge_graph_builds",
            ["project_id", "status"],
        )
        op.create_index(
            "ix_knowledge_graph_builds_heartbeat",
            "knowledge_graph_builds",
            ["status", "heartbeat_at"],
        )

    if "knowledge_graph_health_checks" not in _tables(conn):
        op.create_table(
            "knowledge_graph_health_checks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("graph_id", sa.Integer(), nullable=True),
            sa.Column("version_id", sa.Integer(), nullable=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(50), nullable=False, server_default="unknown"),
            sa.Column("check_type", sa.String(50), nullable=False, server_default="on_demand"),
            sa.Column("structural_checks", _JSON, nullable=True),
            sa.Column("source_alignment", _JSON, nullable=True),
            sa.Column("dependency_checks", _JSON, nullable=True),
            sa.Column("node_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("edge_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("orphan_ratio", sa.Float(), nullable=True),
            sa.Column("disconnected_components", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("warnings", _JSON, nullable=True),
            sa.Column("errors", _JSON, nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index(
            "ix_knowledge_graph_health_checks_project",
            "knowledge_graph_health_checks",
            ["tenant_id", "project_id", "completed_at"],
        )

    if conn.dialect.name != "sqlite":
        _add_fks()


def _add_fks() -> None:
    op.create_foreign_key(
        "fk_knowledge_graphs_tenant",
        "knowledge_graphs",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_knowledge_graphs_project",
        "knowledge_graphs",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_knowledge_graph_versions_graph",
        "knowledge_graph_versions",
        "knowledge_graphs",
        ["graph_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_knowledge_graph_versions_tenant",
        "knowledge_graph_versions",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_knowledge_graph_versions_project",
        "knowledge_graph_versions",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_knowledge_graph_versions_created_by",
        "knowledge_graph_versions",
        "users",
        ["created_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_knowledge_graph_builds_graph",
        "knowledge_graph_builds",
        "knowledge_graphs",
        ["graph_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_knowledge_graph_builds_tenant",
        "knowledge_graph_builds",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_knowledge_graph_builds_project",
        "knowledge_graph_builds",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_knowledge_graph_builds_requested_by",
        "knowledge_graph_builds",
        "users",
        ["requested_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_knowledge_graph_health_checks_graph",
        "knowledge_graph_health_checks",
        "knowledge_graphs",
        ["graph_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_knowledge_graph_health_checks_version",
        "knowledge_graph_health_checks",
        "knowledge_graph_versions",
        ["version_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_knowledge_graph_health_checks_tenant",
        "knowledge_graph_health_checks",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_knowledge_graph_health_checks_project",
        "knowledge_graph_health_checks",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    conn = op.get_bind()
    tables = _tables(conn)
    for t in [
        "knowledge_graph_health_checks",
        "knowledge_graph_builds",
        "knowledge_graph_versions",
        "knowledge_graphs",
    ]:
        if t in tables:
            op.drop_table(t)
