"""add chat attachments and feature flag

Revision ID: 0085
Revises: 0084
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0085"
down_revision: Union[str, None] = "0084"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    _JSON = postgresql.JSONB(sa.Text()).with_variant(sa.JSON(), "sqlite")

    # Tenant-level feature flag for ChatGPT-style file/image attachments.
    op.add_column(
        "tenants",
        sa.Column(
            "chat_attachments_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.create_table(
        "chat_attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
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
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("analytics_conversations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "message_id",
            sa.Integer(),
            sa.ForeignKey("analytics_conversation_turns.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "uploaded_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("safe_filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="uploading",
        ),
        sa.Column("status_message", sa.Text(), nullable=True),
        sa.Column("extraction_result", _JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Index("ix_chat_attachments_tenant_message", "tenant_id", "message_id"),
        sa.Index("ix_chat_attachments_conversation_status", "conversation_id", "status"),
    )


def downgrade() -> None:
    op.drop_table("chat_attachments")
    op.drop_column("tenants", "chat_attachments_enabled")
