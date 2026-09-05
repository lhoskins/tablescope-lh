"""Add fail-closed private S3 bindings to tenant data planes.

Revision ID: 0089
Revises: 0088
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0089"
down_revision: str | None = "0088"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tenant_data_planes", sa.Column("storage_mode", sa.String(30), server_default="isolated_s3", nullable=False))
    op.add_column("tenant_data_planes", sa.Column("s3_bucket_name", sa.String(255), nullable=True))
    op.add_column("tenant_data_planes", sa.Column("s3_region", sa.String(50), nullable=True))
    op.add_column("tenant_data_planes", sa.Column("s3_prefix", sa.String(500), server_default="", nullable=False))
    op.add_column("tenant_data_planes", sa.Column("s3_access_point_arn", sa.String(500), nullable=True))
    op.add_column("tenant_data_planes", sa.Column("s3_vpc_endpoint_id", sa.String(100), nullable=True))
    op.add_column("tenant_data_planes", sa.Column("s3_endpoint_url", sa.String(500), nullable=True))
    op.add_column("tenant_data_planes", sa.Column("s3_kms_key_arn", sa.String(500), nullable=True))
    op.add_column("tenant_data_planes", sa.Column("s3_role_arn", sa.String(500), nullable=True))
    op.add_column("tenant_data_planes", sa.Column("s3_force_private", sa.Boolean(), server_default=sa.true(), nullable=False))
    op.add_column("tenant_data_planes", sa.Column("storage_status", sa.String(50), server_default="unconfigured", nullable=False))
    op.add_column("tenant_data_planes", sa.Column("storage_validated_at", sa.DateTime(timezone=True), nullable=True))
    for column in ("s3_bucket_name", "s3_access_point_arn", "s3_vpc_endpoint_id", "s3_kms_key_arn", "s3_role_arn"):
        op.create_index(f"uq_tenant_data_planes_{column}", "tenant_data_planes", [column], unique=True)


def downgrade() -> None:
    for column in reversed(("s3_bucket_name", "s3_access_point_arn", "s3_vpc_endpoint_id", "s3_kms_key_arn", "s3_role_arn")):
        op.drop_index(f"uq_tenant_data_planes_{column}", table_name="tenant_data_planes")
    for column in reversed(("storage_mode", "s3_bucket_name", "s3_region", "s3_prefix", "s3_access_point_arn", "s3_vpc_endpoint_id", "s3_endpoint_url", "s3_kms_key_arn", "s3_role_arn", "s3_force_private", "storage_status", "storage_validated_at")):
        op.drop_column("tenant_data_planes", column)
