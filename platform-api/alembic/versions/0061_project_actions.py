"""Add project_actions and project_action_subtasks tables.

Revision ID: 0061
Revises: 0060
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0061"
down_revision: str | None = "0060"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")


def _tables(conn: sa.engine.Connection) -> set[str]:
    return set(sa.inspect(conn).get_table_names())


def upgrade() -> None:
    conn = op.get_bind()
    tables = _tables(conn)

    if "project_actions" not in tables:
        op.create_table(
            "project_actions",
            sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=500), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=50), nullable=False, server_default="not_started"),
            sa.Column("priority", sa.String(length=50), nullable=False, server_default="medium"),
            sa.Column("owner_user_id", sa.Integer(), nullable=True),
            sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "percent_complete",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "source_type",
                sa.String(length=50),
                nullable=False,
                server_default="insight",
            ),
            sa.Column("source_insight_id", sa.String(length=255), nullable=True),
            sa.Column(
                "source_insight_fingerprint",
                sa.String(length=255),
                nullable=True,
            ),
            sa.Column("source_insight_type", sa.String(length=100), nullable=True),
            sa.Column("source_insight_title", sa.String(length=500), nullable=True),
            sa.Column("source_insight_snapshot", _JSON, nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("idempotency_key", sa.String(length=255), nullable=True),
            sa.ForeignKeyConstraint(
                ["tenant_id"],
                ["tenants.id"],
                name="fk_project_actions_tenant_id",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["project_id"],
                ["projects.id"],
                name="fk_project_actions_project_id",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["owner_user_id"],
                ["users.id"],
                name="fk_project_actions_owner_user_id",
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["created_by_user_id"],
                ["users.id"],
                name="fk_project_actions_created_by_user_id",
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["updated_by_user_id"],
                ["users.id"],
                name="fk_project_actions_updated_by_user_id",
                ondelete="SET NULL",
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "idempotency_key",
                name="uix_project_actions_tenant_idempotency_key",
            ),
        )
        op.create_index("ix_project_actions_tenant_id", "project_actions", ["tenant_id"])
        op.create_index("ix_project_actions_project_id", "project_actions", ["project_id"])
        op.create_index("ix_project_actions_owner_user_id", "project_actions", ["owner_user_id"])
        op.create_index(
            "ix_project_actions_source_insight_fingerprint",
            "project_actions",
            ["source_insight_fingerprint"],
        )
        op.create_index(
            "ix_project_actions_idempotency_key",
            "project_actions",
            ["idempotency_key"],
        )

    if "project_action_subtasks" not in tables:
        op.create_table(
            "project_action_subtasks",
            sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("action_id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=500), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "status",
                sa.String(length=50),
                nullable=False,
                server_default="not_started",
            ),
            sa.Column(
                "percent_complete",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("owner_user_id", sa.Integer(), nullable=True),
            sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "position",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "is_required",
                sa.Boolean(),
                nullable=False,
                server_default="true",
            ),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["tenant_id"],
                ["tenants.id"],
                name="fk_project_action_subtasks_tenant_id",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["project_id"],
                ["projects.id"],
                name="fk_project_action_subtasks_project_id",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["action_id"],
                ["project_actions.id"],
                name="fk_project_action_subtasks_action_id",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["owner_user_id"],
                ["users.id"],
                name="fk_project_action_subtasks_owner_user_id",
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["created_by_user_id"],
                ["users.id"],
                name="fk_project_action_subtasks_created_by_user_id",
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["updated_by_user_id"],
                ["users.id"],
                name="fk_project_action_subtasks_updated_by_user_id",
                ondelete="SET NULL",
            ),
        )
        op.create_index(
            "ix_project_action_subtasks_tenant_id",
            "project_action_subtasks",
            ["tenant_id"],
        )
        op.create_index(
            "ix_project_action_subtasks_project_id",
            "project_action_subtasks",
            ["project_id"],
        )
        op.create_index(
            "ix_project_action_subtasks_action_id",
            "project_action_subtasks",
            ["action_id"],
        )


def downgrade() -> None:
    conn = op.get_bind()
    tables = _tables(conn)
    if "project_action_subtasks" in tables:
        op.drop_table("project_action_subtasks")
    if "project_actions" in tables:
        op.drop_table("project_actions")
