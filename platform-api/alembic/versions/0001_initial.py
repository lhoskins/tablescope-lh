"""Initial schema: tenants, users, projects, VDBs.

Revision ID: 0001_initial
Revises:
Create Date: 2025-01-01 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"])
    op.create_index("ix_tenants_external_id", "tenants", ["external_id"])

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True, unique=True),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("role", sa.String(32), nullable=False, server_default="viewer"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_external_id", "users", ["external_id"])

    op.create_table(
        "projects",
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
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("type", sa.String(255), nullable=True),
        sa.Column("is_shared", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_projects_tenant_id", "projects", ["tenant_id"])
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"])
    op.create_index("ix_projects_is_shared", "projects", ["is_shared"])

    op.create_table(
        "project_members",
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role", sa.String(50), nullable=False, server_default="member"),
    )

    for vdb_table, scoped_unique in (
        ("user_vdbs", "user_id"),
        ("shared_vdbs", None),
        ("organization_vdbs", None),
    ):
        columns = [
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "tenant_id",
                sa.Integer(),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
        ]
        if vdb_table == "user_vdbs":
            columns.append(
                sa.Column(
                    "user_id",
                    sa.Integer(),
                    sa.ForeignKey("users.id", ondelete="CASCADE"),
                    nullable=False,
                    unique=True,
                )
            )
        if vdb_table == "organization_vdbs":
            columns.extend(
                [
                    sa.Column("vdb_name", sa.String(255), nullable=False),
                    sa.Column("template_vdb_name", sa.String(255), nullable=True),
                ]
            )
        else:
            columns.extend(
                [
                    sa.Column("vdb_id", sa.String(255), nullable=False, unique=True),
                    sa.Column("vdb_username", sa.String(255), nullable=False),
                    sa.Column("encrypted_password", sa.String(512), nullable=False),
                ]
            )
        columns.extend(
            [
                sa.Column("vdb_host", sa.String(255), nullable=False, server_default="127.0.0.1"),
                sa.Column("vdb_port", sa.Integer(), nullable=False, server_default="35442"),
                sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
                sa.Column("last_health_check", sa.DateTime(timezone=True), nullable=True),
                sa.Column("health_status", sa.String(50), nullable=False, server_default="unknown"),
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    nullable=False,
                    server_default=sa.func.now(),
                ),
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=True),
                    nullable=False,
                    server_default=sa.func.now(),
                ),
            ]
        )
        op.create_table(vdb_table, *columns)
        op.create_index(f"ix_{vdb_table}_tenant_id", vdb_table, ["tenant_id"])

    op.create_unique_constraint(
        "uq_shared_vdbs_tenant", "shared_vdbs", ["tenant_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_shared_vdbs_tenant", "shared_vdbs", type_="unique")
    for tbl in (
        "organization_vdbs",
        "shared_vdbs",
        "user_vdbs",
        "project_members",
        "projects",
        "users",
        "tenants",
    ):
        op.drop_table(tbl)
