"""Add data source AI file analysis tables.

Creates 4 tables for AI-assisted file upload analysis:
- data_source_ai_profiles: top-level AI analysis profile
- data_source_field_profiles: per-field profiling metadata
- data_source_tags: AI/user tags
- data_source_ai_recommendations: AI recommendations (accept/reject)

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-13
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_source_ai_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("data_source_id", sa.Integer(), nullable=False, index=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("file_name", sa.String(500), nullable=True),
        sa.Column("file_type", sa.String(50), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("column_count", sa.Integer(), nullable=True),
        sa.Column("sheet_name", sa.String(255), nullable=True),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("ai_usage_summary", sa.Text(), nullable=True),
        sa.Column("ai_quality_summary", sa.Text(), nullable=True),
        sa.Column("user_notes", sa.Text(), nullable=True),
        sa.Column("user_nuances", sa.Text(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
        sa.Column("analysis_version", sa.String(50), nullable=False, server_default="v1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "data_source_field_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("data_source_id", sa.Integer(), nullable=False, index=True),
        sa.Column("profile_id", sa.Integer(), sa.ForeignKey("data_source_ai_profiles.id", ondelete="CASCADE"), nullable=True),
        sa.Column("field_name", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("detected_type", sa.String(100), nullable=True),
        sa.Column("recommended_type", sa.String(100), nullable=True),
        sa.Column("max_length", sa.Integer(), nullable=True),
        sa.Column("min_length", sa.Integer(), nullable=True),
        sa.Column("nullable", sa.Boolean(), nullable=True),
        sa.Column("null_count", sa.Integer(), nullable=True),
        sa.Column("null_percent", sa.Numeric(8, 4), nullable=True),
        sa.Column("distinct_count", sa.Integer(), nullable=True),
        sa.Column("sample_values", sa.JSON(), nullable=True),
        sa.Column("min_value", sa.Text(), nullable=True),
        sa.Column("max_value", sa.Text(), nullable=True),
        sa.Column("ai_description", sa.Text(), nullable=True),
        sa.Column("ai_quality_notes", sa.Text(), nullable=True),
        sa.Column("user_notes", sa.Text(), nullable=True),
        sa.Column("include_in_ai", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "data_source_tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("data_source_id", sa.Integer(), nullable=False, index=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("tag", sa.String(100), nullable=False),
        sa.Column("tag_type", sa.String(50), nullable=False, server_default="user"),
        sa.Column("source", sa.String(50), nullable=False, server_default="user"),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("accepted", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "data_source_ai_recommendations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("data_source_id", sa.Integer(), nullable=False, index=True),
        sa.Column("profile_id", sa.Integer(), sa.ForeignKey("data_source_ai_profiles.id", ondelete="CASCADE"), nullable=True),
        sa.Column("recommendation_type", sa.String(100), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(50), nullable=False, server_default="info"),
        sa.Column("suggested_action", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("data_source_ai_recommendations")
    op.drop_table("data_source_tags")
    op.drop_table("data_source_field_profiles")
    op.drop_table("data_source_ai_profiles")
