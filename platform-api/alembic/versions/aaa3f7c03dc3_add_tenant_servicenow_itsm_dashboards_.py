"""add tenant servicenow_itsm_dashboards_v2_enabled flag

Revision ID: aaa3f7c03dc3
Revises: 0085
Create Date: 2026-08-14 18:59:19.123004

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aaa3f7c03dc3'
down_revision: Union[str, None] = '0085'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "servicenow_itsm_dashboards_v2_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tenants", "servicenow_itsm_dashboards_v2_enabled")
