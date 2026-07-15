"""Add tenant AI governance policy and audit tables.

Revision ID: 0055
Revises: 0054
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0055"
down_revision: str | None = "0054"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "tenant_ai_governance_policies",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_tenant_ai_governance_policies_tenant_id",
        "tenant_ai_governance_policies",
        ["tenant_id"],
        unique=False,
    )

    op.create_table(
        "tenant_ai_method_policies",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "policy_id",
            sa.Integer(),
            sa.ForeignKey("tenant_ai_governance_policies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("method_key", sa.String(150), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "updated_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_tenant_ai_method_policy_tenant_method",
        "tenant_ai_method_policies",
        ["tenant_id", "method_key"],
        unique=True,
    )
    op.create_index(
        "ix_tenant_ai_method_policies_policy_id",
        "tenant_ai_method_policies",
        ["policy_id"],
        unique=False,
    )

    op.create_table(
        "ai_governance_audit_events",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_type", sa.String(50), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("method_key", sa.String(150), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("turn_id", sa.Integer(), nullable=True),
        sa.Column("insight_id", sa.String(255), nullable=True),
        sa.Column("policy_version", sa.Integer(), nullable=True),
        sa.Column("previous_value", _JSON, nullable=True),
        sa.Column("new_value", _JSON, nullable=True),
        sa.Column("decision", sa.String(50), nullable=True),
        sa.Column("reason_code", sa.String(100), nullable=True),
        sa.Column("details", _JSON, nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_ai_governance_audit_events_tenant_id",
        "ai_governance_audit_events",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_ai_governance_audit_events_event_type",
        "ai_governance_audit_events",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        "ix_ai_governance_audit_events_method_key",
        "ai_governance_audit_events",
        ["method_key"],
        unique=False,
    )
    op.create_index(
        "ix_ai_governance_audit_events_decision",
        "ai_governance_audit_events",
        ["decision"],
        unique=False,
    )
    op.create_index(
        "ix_ai_governance_audit_events_project_id",
        "ai_governance_audit_events",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_ai_governance_audit_tenant_created",
        "ai_governance_audit_events",
        ["tenant_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("ai_governance_audit_events")
    op.drop_table("tenant_ai_method_policies")
    op.drop_table("tenant_ai_governance_policies")
