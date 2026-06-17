"""Home AI Intelligence: audit events, user preferences, live reports.

Adds:
- ``audit_events`` — immutable log of AI / home-intelligence actions.
- ``users.preferences`` — per-user JSON preferences (intelligence settings).
- ``reports`` — Live Report Builder definitions (query defs, not data).

Revision ID: 0027
Revises: 0026
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")


def _tables(conn: sa.engine.Connection) -> set[str]:
    return set(sa.inspect(conn).get_table_names())


def _columns(conn: sa.engine.Connection, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(conn).get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()
    existing = _tables(conn)

    if "users" in existing and "preferences" not in _columns(conn, "users"):
        op.add_column(
            "users",
            sa.Column(
                "preferences",
                _JSON,
                nullable=False,
                server_default="{}",
            ),
        )

    if "audit_events" not in existing:
        op.create_table(
            "audit_events",
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
                nullable=True,
            ),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("event_type", sa.String(length=100), nullable=False),
            sa.Column("prompt_type", sa.String(length=100), nullable=True),
            sa.Column("scope", sa.String(length=100), nullable=True),
            sa.Column("title", sa.Text(), nullable=True),
            sa.Column("tables_queried", _JSON, nullable=False, server_default="[]"),
            sa.Column("documents_read", _JSON, nullable=False, server_default="[]"),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
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
        op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"])
        op.create_index("ix_audit_events_project_id", "audit_events", ["project_id"])
        op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])

    if "reports" not in existing:
        op.create_table(
            "reports",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "tenant_id",
                sa.Integer(),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "owner_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("share_token", sa.String(length=64), nullable=False),
            sa.Column(
                "title",
                sa.Text(),
                nullable=False,
                server_default="Untitled report",
            ),
            sa.Column("sections", _JSON, nullable=False, server_default="[]"),
            sa.Column("share_settings", _JSON, nullable=False, server_default="{}"),
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
        op.create_index("ix_reports_tenant_id", "reports", ["tenant_id"])
        op.create_index(
            "ix_reports_share_token", "reports", ["share_token"], unique=True
        )


def downgrade() -> None:
    op.drop_table("reports")
    op.drop_table("audit_events")
    op.drop_column("users", "preferences")
