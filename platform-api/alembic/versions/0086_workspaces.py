"""Workspaces: named multi-card canvases inside a project.

Adds:
- ``workspaces`` — a named, owned, publishable canvas per project.
- ``workspace_cards`` — the ordered resources pinned into a workspace.

Revision ID: 0086
Revises: 6aeba63f3092
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0086"
down_revision: str | None = "6aeba63f3092"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def _table_exists(conn: sa.engine.Connection, name: str) -> bool:
    return sa.inspect(conn).has_table(name)


def upgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, "workspaces"):
        op.create_table(
            "workspaces",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("owner_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("name", sa.Text, nullable=False),
            sa.Column("visibility", sa.String(50), nullable=False, server_default="private"),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("idx_workspaces_tenant_project", "workspaces", ["tenant_id", "project_id"])
        op.create_index("idx_workspaces_owner", "workspaces", ["owner_user_id"])

    if not _table_exists(conn, "workspace_cards"):
        op.create_table(
            "workspace_cards",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column(
                "workspace_id", sa.Integer, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False,
            ),
            sa.Column("resource_type", sa.String(50), nullable=False),
            sa.Column("resource_id", sa.String, nullable=False),
            sa.Column("view_mode", sa.String(20), nullable=False, server_default="card"),
            sa.Column("position", sa.Integer, nullable=False, server_default="0"),
            sa.Column("added_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("idx_workspace_cards_workspace", "workspace_cards", ["workspace_id"])


def downgrade() -> None:
    op.drop_table("workspace_cards")
    op.drop_table("workspaces")
