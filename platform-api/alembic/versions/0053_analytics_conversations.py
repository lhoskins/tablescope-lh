"""Add analytics_conversations and analytics_conversation_turns tables.

Revision ID: 0053
Revises: 0052
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0053"
down_revision: str | None = "0052"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "analytics_conversations",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("active_datasource_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("last_successful_turn_id", sa.Integer(), nullable=True),
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
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_analytics_conversations_tenant_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_analytics_conversations_user_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_analytics_conversations_project_id", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["active_datasource_id"],
            ["file_source_meta.id"],
            name="fk_analytics_conversations_active_datasource_id",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_analytics_conversations_tenant_id", "analytics_conversations", ["tenant_id"])
    op.create_index("ix_analytics_conversations_user_id", "analytics_conversations", ["user_id"])
    op.create_index("ix_analytics_conversations_project_id", "analytics_conversations", ["project_id"])
    op.create_index("ix_analytics_conversations_tenant_user", "analytics_conversations", ["tenant_id", "user_id"])

    op.create_table(
        "analytics_conversation_turns",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("client_request_id", sa.String(length=64), nullable=True),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("intent_type", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("analytical_plan", _JSON, nullable=True),
        sa.Column("datasource_context", _JSON, nullable=True),
        sa.Column("sql", sa.Text(), nullable=True),
        sa.Column("sql_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("result_metadata", _JSON, nullable=True),
        sa.Column("result_cache", _JSON, nullable=True),
        sa.Column("chart_config", _JSON, nullable=True),
        sa.Column("explanation", _JSON, nullable=True),
        sa.Column("assistant_message", sa.Text(), nullable=True),
        sa.Column("parent_turn_id", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
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
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["analytics_conversations.id"],
            name="fk_analytics_turns_conversation_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_turn_id"],
            ["analytics_conversation_turns.id"],
            name="fk_analytics_turns_parent_turn_id",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "conversation_id", "sequence", name="uq_analytics_turn_sequence"
        ),
        sa.UniqueConstraint(
            "conversation_id", "client_request_id",
            name="uq_analytics_turn_client_request_id",
        ),
    )
    op.create_index("ix_analytics_turns_conversation_id", "analytics_conversation_turns", ["conversation_id"])
    op.create_index("ix_analytics_turns_status", "analytics_conversation_turns", ["status"])

    # The self-referential last_successful_turn_id FK is added after the turn table exists.
    op.create_foreign_key(
        "fk_analytics_conversations_last_successful_turn_id",
        "analytics_conversations",
        "analytics_conversation_turns",
        ["last_successful_turn_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_table("analytics_conversation_turns")
    op.drop_table("analytics_conversations")
