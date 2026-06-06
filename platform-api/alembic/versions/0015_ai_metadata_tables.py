"""Add AI metadata tables for tenant-isolated AI.

Creates 7 tables for the Tablescope AI system:
- ai_documents: tracked documents for vector indexing
- ai_document_chunks: individual chunks with vector references
- ai_project_graph_nodes: project knowledge graph nodes
- ai_project_graph_edges: relationships between graph nodes
- ai_memories: user private AI memory (scoped by tenant/project/user)
- ai_query_history: AI query history for learning
- ai_audit_logs: comprehensive audit trail for all AI access

Every table includes tenant_id for strict tenant isolation.

Revision ID: 0015_ai_metadata
Revises: 0014_dashboards
Create Date: 2026-07-13
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0015_ai_metadata"
down_revision: str | None = "0014_dashboards"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- ai_documents ---
    op.create_table(
        "ai_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("organization.id"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id"), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("visibility", sa.String(50), nullable=False, server_default="shared_project"),
        sa.Column("access_group_id", sa.Integer(), nullable=True),
        sa.Column("source_type", sa.String(100), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=True),
        sa.Column("content_type", sa.String(255), nullable=True),
        sa.Column("file_hash", sa.Text(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), server_default="0"),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_ai_docs_tenant_project", "ai_documents", ["tenant_id", "project_id"])

    # --- ai_document_chunks ---
    op.create_table(
        "ai_document_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("ai_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("vector_id", sa.Text(), nullable=True),
        sa.Column("embedding_model", sa.String(255), nullable=True),
        sa.Column("visibility", sa.String(50), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("allowed_user_ids", postgresql.JSONB(), server_default="[]"),
        sa.Column("allowed_group_ids", postgresql.JSONB(), server_default="[]"),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_ai_chunks_tenant_project", "ai_document_chunks", ["tenant_id", "project_id"])
    op.create_index("idx_ai_chunks_document", "ai_document_chunks", ["document_id"])

    # --- ai_project_graph_nodes ---
    op.create_table(
        "ai_project_graph_nodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("node_type", sa.String(100), nullable=False),
        sa.Column("source_type", sa.String(100), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("properties", postgresql.JSONB(), server_default="{}"),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("visibility", sa.String(50), nullable=False, server_default="shared_project"),
        sa.Column("access_group_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_ai_graph_nodes_tenant_project", "ai_project_graph_nodes", ["tenant_id", "project_id"])

    # --- ai_project_graph_edges ---
    op.create_table(
        "ai_project_graph_edges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("from_node_id", sa.Integer(), sa.ForeignKey("ai_project_graph_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("to_node_id", sa.Integer(), sa.ForeignKey("ai_project_graph_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relationship_type", sa.String(100), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("evidence", postgresql.JSONB(), server_default="{}"),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("visibility", sa.String(50), nullable=False, server_default="shared_project"),
        sa.Column("access_group_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_ai_graph_edges_tenant_project", "ai_project_graph_edges", ["tenant_id", "project_id"])

    # --- ai_memories ---
    op.create_table(
        "ai_memories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("scope_type", sa.String(50), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("vector_id", sa.Text(), nullable=True),
        sa.Column("visibility", sa.String(50), nullable=False, server_default="personal"),
        sa.Column("source_type", sa.String(100), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_ai_memories_tenant_user", "ai_memories", ["tenant_id", "user_id"])

    # --- ai_query_history ---
    op.create_table(
        "ai_query_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("generated_sql", sa.Text(), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("allowed_context", postgresql.JSONB(), nullable=True),
        sa.Column("model_name", sa.String(255), nullable=True),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_ai_query_history_tenant_project", "ai_query_history", ["tenant_id", "project_id"])

    # --- ai_audit_logs ---
    op.create_table(
        "ai_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False, unique=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("scope_type", sa.String(50), nullable=True),
        sa.Column("source_type", sa.String(100), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("vector_ids", postgresql.JSONB(), server_default="[]"),
        sa.Column("document_ids", postgresql.JSONB(), server_default="[]"),
        sa.Column("chunk_ids", postgresql.JSONB(), server_default="[]"),
        sa.Column("allowed_context_summary", postgresql.JSONB(), nullable=True),
        sa.Column("denied_context_summary", postgresql.JSONB(), nullable=True),
        sa.Column("model_name", sa.String(255), nullable=True),
        sa.Column("tokens_input", sa.Integer(), nullable=True),
        sa.Column("tokens_output", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_ai_audit_tenant", "ai_audit_logs", ["tenant_id"])
    op.create_index("idx_ai_audit_request", "ai_audit_logs", ["request_id"])


def downgrade() -> None:
    op.drop_table("ai_audit_logs")
    op.drop_table("ai_query_history")
    op.drop_table("ai_memories")
    op.drop_table("ai_project_graph_edges")
    op.drop_table("ai_project_graph_nodes")
    op.drop_table("ai_document_chunks")
    op.drop_table("ai_documents")
