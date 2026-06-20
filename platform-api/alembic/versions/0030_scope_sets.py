"""Scope sets + canvas layouts for the Scope Relationship Builder.

Adds:
- ``scope_sets`` — named, toggleable parent group of query scopes.
- ``scope_canvas_layouts`` — per-set table-card positions on the builder canvas.
- New columns on ``query_scopes`` (scope_set_id, source_table, target_table,
  direction, match_group_id, match_mode, enabled, confidence_score,
  created_by_ai).

Backfills every existing scope into a default manual "Imported Scopes" set so
the new Scope Navigation page lists them out of the box.

Revision ID: 0030
Revises: 0029
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def _tables(conn: sa.engine.Connection) -> set[str]:
    return set(sa.inspect(conn).get_table_names())


def _columns(conn: sa.engine.Connection, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(conn).get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()
    existing = _tables(conn)

    if "scope_sets" not in existing:
        op.create_table(
            "scope_sets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "tenant_id",
                sa.Integer(),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "project_id",
                sa.Integer(),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "type",
                sa.String(length=20),
                nullable=False,
                server_default="manual",
            ),
            sa.Column(
                "enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column(
                "created_by",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
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
            "ix_scope_sets_tenant_id", "scope_sets", ["tenant_id"]
        )
        op.create_index(
            "ix_scope_sets_project_id", "scope_sets", ["project_id"]
        )

    if "scope_canvas_layouts" not in existing:
        op.create_table(
            "scope_canvas_layouts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "scope_set_id",
                sa.Integer(),
                sa.ForeignKey("scope_sets.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("table_key", sa.String(length=255), nullable=False),
            sa.Column("table_name", sa.String(length=512), nullable=True),
            sa.Column(
                "query_id",
                sa.Integer(),
                sa.ForeignKey("saved_queries.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("datasource_id", sa.Integer(), nullable=True),
            sa.Column(
                "x_position", sa.Float(), nullable=False, server_default="0"
            ),
            sa.Column(
                "y_position", sa.Float(), nullable=False, server_default="0"
            ),
            sa.Column("width", sa.Float(), nullable=True),
            sa.Column("height", sa.Float(), nullable=True),
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
            "ix_scope_canvas_layouts_scope_set_id",
            "scope_canvas_layouts",
            ["scope_set_id"],
        )

    scope_cols = _columns(conn, "query_scopes")
    new_columns = [
        sa.Column(
            "scope_set_id",
            sa.Integer(),
            sa.ForeignKey("scope_sets.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("source_table", sa.String(length=512), nullable=True),
        sa.Column("target_table", sa.String(length=512), nullable=True),
        sa.Column(
            "direction",
            sa.String(length=20),
            nullable=False,
            server_default="source_to_target",
        ),
        sa.Column("match_group_id", sa.String(length=64), nullable=True),
        sa.Column(
            "match_mode", sa.String(length=8), nullable=False, server_default="all"
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column(
            "created_by_ai",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    ]
    for col in new_columns:
        if col.name not in scope_cols:
            op.add_column("query_scopes", col)

    if "scope_set_id" not in scope_cols:
        op.create_index(
            "ix_query_scopes_scope_set_id", "query_scopes", ["scope_set_id"]
        )

    # Backfill: group orphaned scopes into one "Imported Scopes" set per project.
    rows = conn.execute(
        sa.text(
            "SELECT DISTINCT tenant_id, project_id FROM query_scopes "
            "WHERE scope_set_id IS NULL"
        )
    ).fetchall()
    for tenant_id, project_id in rows:
        result = conn.execute(
            sa.text(
                "INSERT INTO scope_sets "
                "(tenant_id, project_id, name, description, type, enabled) "
                "VALUES (:t, :p, :n, :d, 'manual', true) RETURNING id"
            ),
            {
                "t": tenant_id,
                "p": project_id,
                "n": "Imported Scopes",
                "d": "Existing drill-down scopes migrated into a scope set.",
            },
        )
        set_id = result.scalar()
        conn.execute(
            sa.text(
                "UPDATE query_scopes SET scope_set_id = :sid "
                "WHERE tenant_id = :t AND project_id = :p "
                "AND scope_set_id IS NULL"
            ),
            {"sid": set_id, "t": tenant_id, "p": project_id},
        )


def downgrade() -> None:
    conn = op.get_bind()
    scope_cols = _columns(conn, "query_scopes")
    for name in (
        "created_by_ai",
        "confidence_score",
        "enabled",
        "match_mode",
        "match_group_id",
        "direction",
        "target_table",
        "source_table",
        "scope_set_id",
    ):
        if name in scope_cols:
            op.drop_column("query_scopes", name)

    existing = _tables(conn)
    if "scope_canvas_layouts" in existing:
        op.drop_table("scope_canvas_layouts")
    if "scope_sets" in existing:
        op.drop_table("scope_sets")
