"""canonical insight conversations

Revision ID: 9ef39057749a
Revises: 0080
Create Date: 2026-08-06 05:53:57.971904

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9ef39057749a'
down_revision: Union[str, None] = '0080'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "analytics_conversations",
        sa.Column("canonical_key", sa.String(128), nullable=True),
    )
    op.add_column(
        "analytics_conversations",
        sa.Column(
            "merged_into_conversation_id",
            sa.Integer(),
            sa.ForeignKey("analytics_conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_analytics_conversations_canonical_key",
        "analytics_conversations",
        ["canonical_key"],
    )
    with op.batch_alter_table("analytics_conversations") as batch_op:
        batch_op.create_unique_constraint(
            "uq_analytics_conversations_canonical_key",
            ["tenant_id", "user_id", "canonical_key"],
        )


def downgrade() -> None:
    with op.batch_alter_table("analytics_conversations") as batch_op:
        batch_op.drop_constraint(
            "uq_analytics_conversations_canonical_key", type_="unique"
        )
    op.drop_index("ix_analytics_conversations_canonical_key", "analytics_conversations")
    op.drop_column("analytics_conversations", "merged_into_conversation_id")
    op.drop_column("analytics_conversations", "canonical_key")
