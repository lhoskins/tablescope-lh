"""KG-07: Knowledge Graph evidence access audit log.

Adds ``knowledge_graph_evidence_access`` -- one row per KG context
collection, recording which node/document/query ids (and the active KG
version) informed a given AI-generated answer for a given user/surface, so
an administrator can reconstruct exactly what evidence grounded it.

Revision ID: 0087
Revises: 0086
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0087"
down_revision: str | None = "0086"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")


def _table_exists(conn: sa.engine.Connection, name: str) -> bool:
    return sa.inspect(conn).has_table(name)


def upgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "knowledge_graph_evidence_access"):
        return

    op.create_table(
        "knowledge_graph_evidence_access",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("surface", sa.String(50), nullable=False),
        sa.Column("kg_version_id", sa.Integer, nullable=True),
        sa.Column("node_ids", _JSON, nullable=False, server_default="[]"),
        sa.Column("document_ids", _JSON, nullable=False, server_default="[]"),
        sa.Column("query_ids", _JSON, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "idx_kg_evidence_access_tenant_project", "knowledge_graph_evidence_access",
        ["tenant_id", "project_id"],
    )
    op.create_index(
        "idx_kg_evidence_access_user", "knowledge_graph_evidence_access", ["user_id"],
    )
    op.create_index(
        "idx_kg_evidence_access_kg_version", "knowledge_graph_evidence_access", ["kg_version_id"],
    )
    op.create_index(
        "idx_kg_evidence_access_surface", "knowledge_graph_evidence_access", ["surface"],
    )


def downgrade() -> None:
    op.drop_table("knowledge_graph_evidence_access")
