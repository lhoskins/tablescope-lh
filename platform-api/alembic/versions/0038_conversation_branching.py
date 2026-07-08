"""AI conversation branching: parent + branched-from-message references.

Adds ``ai_conversations.parent_conversation_id`` (the source thread a branch was
forked from) and ``ai_conversations.branched_from_message_id`` (the message the
branch diverged from). Both are nullable self/cross references.

Revision ID: 0038
Revises: 0037
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    cols = {c["name"] for c in sa.inspect(conn).get_columns("ai_conversations")}
    if "parent_conversation_id" not in cols:
        op.add_column(
            "ai_conversations",
            sa.Column("parent_conversation_id", sa.Integer(), nullable=True),
        )
        op.create_index(
            "ix_ai_conversations_parent_conversation_id",
            "ai_conversations",
            ["parent_conversation_id"],
        )
        op.create_foreign_key(
            "fk_ai_conversations_parent",
            "ai_conversations",
            "ai_conversations",
            ["parent_conversation_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if "branched_from_message_id" not in cols:
        op.add_column(
            "ai_conversations",
            sa.Column("branched_from_message_id", sa.Integer(), nullable=True),
        )
        op.create_foreign_key(
            "fk_ai_conversations_branched_from_message",
            "ai_conversations",
            "ai_conversation_messages",
            ["branched_from_message_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    op.drop_constraint(
        "fk_ai_conversations_branched_from_message",
        "ai_conversations",
        type_="foreignkey",
    )
    op.drop_column("ai_conversations", "branched_from_message_id")
    op.drop_constraint(
        "fk_ai_conversations_parent", "ai_conversations", type_="foreignkey"
    )
    op.drop_index(
        "ix_ai_conversations_parent_conversation_id",
        table_name="ai_conversations",
    )
    op.drop_column("ai_conversations", "parent_conversation_id")
