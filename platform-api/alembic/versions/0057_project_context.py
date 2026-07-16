"""Add project business context, goals, metrics, targets, risks, and audit for Sprint 07.

Revision ID: 0057
Revises: 0056
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0057"
down_revision: str | None = "0056"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    # ── Project business context ────────────────────────────────────────
    op.create_table(
        "project_business_contexts",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column(
            "business_owner_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("business_function", sa.String(255), nullable=True),
        sa.Column("industry", sa.String(255), nullable=True),
        sa.Column("purpose", sa.Text(), nullable=True),
        sa.Column("timezone", sa.String(100), nullable=False, server_default="UTC"),
        sa.Column("currency", sa.String(10), nullable=False, server_default="USD"),
        sa.Column("reporting_cadence", sa.String(50), nullable=True),
        sa.Column("fiscal_year_start_month", sa.Integer(), nullable=True),
        sa.Column("ai_context_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("ai_instructions", sa.Text(), nullable=True),
        sa.Column("interpretation_notes", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_project_business_context_tenant_project",
        "project_business_contexts",
        ["tenant_id", "project_id"],
    )

    # ── Goals ───────────────────────────────────────────────────────────
    op.create_table(
        "project_goals",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("priority", sa.String(20), nullable=False, server_default="medium"),
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("target_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_project_goals_tenant_project_active",
        "project_goals",
        ["tenant_id", "project_id", "active"],
    )
    op.create_index(
        "ix_project_goals_project_position",
        "project_goals",
        ["project_id", "position"],
    )

    # ── Metrics ─────────────────────────────────────────────────────────
    op.create_table(
        "project_metrics",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("business_definition", sa.Text(), nullable=True),
        sa.Column("unit", sa.String(50), nullable=True),
        sa.Column("format", sa.String(50), nullable=True),
        sa.Column(
            "directionality",
            sa.String(20),
            nullable=False,
            server_default="informational",
        ),
        sa.Column(
            "aggregation",
            sa.String(50),
            nullable=False,
            server_default="latest",
        ),
        sa.Column("source_type", sa.String(50), nullable=True),
        sa.Column(
            "source_query_id",
            sa.Integer(),
            sa.ForeignKey("saved_queries.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_mapping", _JSON, nullable=True),
        sa.Column("expression", sa.Text(), nullable=True),
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("cadence", sa.String(50), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_project_metrics_tenant_project_active",
        "project_metrics",
        ["tenant_id", "project_id", "active"],
    )
    op.create_index(
        "ix_project_metrics_project_position",
        "project_metrics",
        ["project_id", "position"],
    )

    # ── Targets ────────────────────────────────────────────────────────
    op.create_table(
        "project_metric_targets",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "metric_id",
            sa.Integer(),
            sa.ForeignKey("project_metrics.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column("target_value", sa.Numeric(19, 6), nullable=True),
        sa.Column("lower_bound", sa.Numeric(19, 6), nullable=True),
        sa.Column("upper_bound", sa.Numeric(19, 6), nullable=True),
        sa.Column("comparison_operator", sa.String(10), nullable=True),
        sa.Column("warning_threshold", sa.Numeric(19, 6), nullable=True),
        sa.Column("critical_threshold", sa.Numeric(19, 6), nullable=True),
        sa.Column("baseline", sa.Numeric(19, 6), nullable=True),
        sa.Column("effective_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period", sa.String(50), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_project_metric_targets_tenant_project",
        "project_metric_targets",
        ["tenant_id", "project_id"],
    )
    op.create_index(
        "ix_project_metric_targets_metric_active",
        "project_metric_targets",
        ["metric_id", "active"],
    )
    op.create_index(
        "ix_project_metric_targets_metric_position",
        "project_metric_targets",
        ["metric_id", "position"],
    )

    # ── Risks ───────────────────────────────────────────────────────────
    op.create_table(
        "project_risks",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("likelihood", sa.String(20), nullable=True),
        sa.Column("impact", sa.String(20), nullable=True),
        sa.Column("severity", sa.String(20), nullable=True),
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("mitigation", sa.Text(), nullable=True),
        sa.Column("contingency", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("review_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_project_risks_tenant_project_active",
        "project_risks",
        ["tenant_id", "project_id", "active"],
    )
    op.create_index(
        "ix_project_risks_project_position",
        "project_risks",
        ["project_id", "position"],
    )

    # ── Relationship tables ─────────────────────────────────────────────
    op.create_table(
        "project_goal_metric_links",
        sa.Column(
            "goal_id",
            sa.Integer(),
            sa.ForeignKey("project_goals.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "metric_id",
            sa.Integer(),
            sa.ForeignKey("project_metrics.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_table(
        "project_goal_risk_links",
        sa.Column(
            "goal_id",
            sa.Integer(),
            sa.ForeignKey("project_goals.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "risk_id",
            sa.Integer(),
            sa.ForeignKey("project_risks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_table(
        "project_risk_metric_links",
        sa.Column(
            "risk_id",
            sa.Integer(),
            sa.ForeignKey("project_risks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "metric_id",
            sa.Integer(),
            sa.ForeignKey("project_metrics.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    # ── Audit events ──────────────────────────────────────────────────────
    op.create_table(
        "project_context_audit_events",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_type", sa.String(50), nullable=False, server_default="user"),
        sa.Column("event_type", sa.String(100), nullable=False, index=True),
        sa.Column("entity_type", sa.String(50), nullable=False, index=True),
        sa.Column("entity_id", sa.Integer(), nullable=True, index=True),
        sa.Column("previous_value", _JSON, nullable=True),
        sa.Column("new_value", _JSON, nullable=True),
        sa.Column("version", sa.Integer(), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_project_context_audit_tenant_project",
        "project_context_audit_events",
        ["tenant_id", "project_id"],
    )
    op.create_index(
        "ix_project_context_audit_event_created",
        "project_context_audit_events",
        ["event_type", "created_at"],
    )

    # ── Conversational analytics context versioning ───────────────────────
    op.add_column(
        "analytics_conversation_turns",
        sa.Column("project_context_version", sa.Integer(), nullable=True),
    )

    # ── Repository intelligence context snapshot columns ───────────────────
    op.add_column(
        "repository_scans",
        sa.Column("project_context_summary", _JSON, nullable=True),
    )
    op.add_column(
        "repository_scans",
        sa.Column("project_context_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "repository_profiles",
        sa.Column("project_context_summary", _JSON, nullable=True),
    )
    op.add_column(
        "repository_profiles",
        sa.Column("project_context_version", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("repository_profiles", "project_context_version")
    op.drop_column("repository_profiles", "project_context_summary")
    op.drop_column("repository_scans", "project_context_version")
    op.drop_column("repository_scans", "project_context_summary")
    op.drop_column("analytics_conversation_turns", "project_context_version")
    op.drop_index(
        "ix_project_context_audit_event_created",
        table_name="project_context_audit_events",
    )
    op.drop_index(
        "ix_project_context_audit_tenant_project",
        table_name="project_context_audit_events",
    )
    op.drop_table("project_context_audit_events")
    op.drop_table("project_risk_metric_links")
    op.drop_table("project_goal_risk_links")
    op.drop_table("project_goal_metric_links")
    op.drop_index("ix_project_risks_project_position", table_name="project_risks")
    op.drop_index("ix_project_risks_tenant_project_active", table_name="project_risks")
    op.drop_table("project_risks")
    op.drop_index(
        "ix_project_metric_targets_metric_position",
        table_name="project_metric_targets",
    )
    op.drop_index(
        "ix_project_metric_targets_metric_active",
        table_name="project_metric_targets",
    )
    op.drop_index(
        "ix_project_metric_targets_tenant_project",
        table_name="project_metric_targets",
    )
    op.drop_table("project_metric_targets")
    op.drop_index("ix_project_metrics_project_position", table_name="project_metrics")
    op.drop_index(
        "ix_project_metrics_tenant_project_active", table_name="project_metrics"
    )
    op.drop_table("project_metrics")
    op.drop_index("ix_project_goals_project_position", table_name="project_goals")
    op.drop_index(
        "ix_project_goals_tenant_project_active", table_name="project_goals"
    )
    op.drop_table("project_goals")
    op.drop_index(
        "ix_project_business_context_tenant_project",
        table_name="project_business_contexts",
    )
    op.drop_table("project_business_contexts")
