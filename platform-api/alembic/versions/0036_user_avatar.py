"""User avatar: profile picture URL + stored file reference.

Adds ``users.avatar_url`` (safe served URL) and ``users.avatar_file_id`` (the
stored object key used to locate the image on disk / in S3).

Revision ID: 0036
Revises: 0035
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    cols = {c["name"] for c in sa.inspect(conn).get_columns("users")}
    if "avatar_url" not in cols:
        op.add_column(
            "users", sa.Column("avatar_url", sa.String(length=512), nullable=True)
        )
    if "avatar_file_id" not in cols:
        op.add_column(
            "users",
            sa.Column("avatar_file_id", sa.String(length=255), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("users", "avatar_file_id")
    op.drop_column("users", "avatar_url")
