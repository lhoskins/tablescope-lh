"""add matched_insight to analytics_conversation_turns

Revision ID: a3f7c9d21b04
Revises: ee7ac16904ce
Create Date: 2026-08-08 22:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a3f7c9d21b04'
down_revision: Union[str, None] = 'ee7ac16904ce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "analytics_conversation_turns",
        sa.Column(
            "matched_insight",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("analytics_conversation_turns", "matched_insight")
