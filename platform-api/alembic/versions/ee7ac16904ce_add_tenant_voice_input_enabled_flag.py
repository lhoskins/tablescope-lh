"""add tenant voice_input_enabled flag

Revision ID: ee7ac16904ce
Revises: 28cc3f8248e6
Create Date: 2026-08-08 07:27:53.791189

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ee7ac16904ce'
down_revision: Union[str, None] = '28cc3f8248e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "voice_input_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tenants", "voice_input_enabled")
