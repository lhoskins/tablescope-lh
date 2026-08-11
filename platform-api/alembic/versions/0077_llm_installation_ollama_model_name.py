"""Add ollama_model_name to llm_installations

Revision ID: 652d027cf396
Revises: a3f7c9d21b04
Create Date: 2026-08-11 21:03:42.971393

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '652d027cf396'
down_revision: str | None = 'a3f7c9d21b04'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "llm_installations",
        sa.Column("ollama_model_name", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("llm_installations", "ollama_model_name")
