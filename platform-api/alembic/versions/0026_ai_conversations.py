"""Saved AI conversations for the Home AI Assistant.

Adds ``ai_conversations`` (a chat thread owned by a user, scoped to a tenant and
optionally a project) and ``ai_conversation_messages`` (ordered user/assistant
messages).

Revision ID: 0026
Revises: 0025
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def _tables(conn: sa.engine.Connection) -> set[str]:
    return set(sa.inspect(conn).get_table_names())


def upgrade() -> None:
    conn = op.get_bind()
    existing = _tables(conn)

    if "ai_conversations" not in existing:
        op.create_table(
            "ai_conversations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "tenant_id",
                sa.Integer(),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "project_id",
                sa.Integer(),
                sa.ForeignKey("projects.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "title",
                sa.String(length=255),
                nullable=False,
                server_default="New conversation",
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
            "ix_ai_conversations_tenant_id", "ai_conversations", ["tenant_id"]
        )
        op.create_index(
            "ix_ai_conversations_user_id", "ai_conversations", ["user_id"]
        )

    if "ai_conversation_messages" not in existing:
        op.create_table(
            "ai_conversation_messages",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "conversation_id",
                sa.Integer(),
                sa.ForeignKey("ai_conversations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("role", sa.String(length=20), nullable=False),
            sa.Column("content", sa.Text(), nullable=False, server_default=""),
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
            "ix_ai_conversation_messages_conversation_id",
            "ai_conversation_messages",
            ["conversation_id"],
        )


def downgrade() -> None:
    op.drop_table("ai_conversation_messages")
    op.drop_table("ai_conversations")
