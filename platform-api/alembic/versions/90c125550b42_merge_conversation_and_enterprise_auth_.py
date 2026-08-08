"""Merge conversation and enterprise auth heads

Revision ID: 90c125550b42
Revises: 0083, 9ef39057749a
Create Date: 2026-08-08 00:12:13.585454

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '90c125550b42'
down_revision: Union[str, None] = ('0083', '9ef39057749a')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
