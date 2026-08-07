"""Enterprise authentication: tenant LDAP/SSO settings, identity linking, and directory sync schema.

Revision ID: 0083
Revises: 0082
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0083"
down_revision: str | None = "0082"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_JSONB = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "ldap_connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("protocol", sa.String(length=20), nullable=False, server_default="ldaps"),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False, server_default="636"),
        sa.Column("base_dn", sa.String(length=1024), nullable=False),
        sa.Column("user_search_base", sa.String(length=1024), nullable=True),
        sa.Column("user_filter", sa.String(length=1024), nullable=True),
        sa.Column("group_search_base", sa.String(length=1024), nullable=True),
        sa.Column("group_filter", sa.String(length=1024), nullable=True),
        sa.Column("bind_dn", sa.String(length=512), nullable=True),
        sa.Column("bind_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("ca_certificate", sa.Text(), nullable=True),
        sa.Column("use_starttls", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("require_cert_validation", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("connect_timeout", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("page_size", sa.Integer(), nullable=False, server_default="1000"),
        sa.Column("nested_group_resolution", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("max_nested_depth", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("sync_interval_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("disabled_user_handling", sa.String(length=32), nullable=False, server_default="suspend"),
        sa.Column("removed_group_handling", sa.String(length=32), nullable=False, server_default="revoke"),
        sa.Column("tenant_data_plane_id", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_test_status", sa.String(length=50), nullable=True),
        sa.Column("last_test_message_safe", sa.String(length=512), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_data_plane_id"], ["tenant_data_planes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ldap_connections_tenant_id", "ldap_connections", ["tenant_id"])

    op.create_table(
        "external_directory_users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("directory_object_guid", sa.String(length=64), nullable=False),
        sa.Column("directory_object_sid", sa.String(length=128), nullable=True),
        sa.Column("upn", sa.String(length=320), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("raw_attributes", _JSONB, nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["ldap_connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "connection_id", "directory_object_guid", name="uq_ext_dir_user_tenant_conn_guid"),
    )
    op.create_index("ix_external_directory_users_tenant_id", "external_directory_users", ["tenant_id"])
    op.create_index("ix_external_directory_users_connection_id", "external_directory_users", ["connection_id"])

    op.create_table(
        "external_directory_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("directory_object_guid", sa.String(length=64), nullable=False),
        sa.Column("directory_object_sid", sa.String(length=128), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("raw_attributes", _JSONB, nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["ldap_connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "connection_id", "directory_object_guid", name="uq_ext_dir_group_tenant_conn_guid"),
    )
    op.create_index("ix_external_directory_groups_tenant_id", "external_directory_groups", ["tenant_id"])
    op.create_index("ix_external_directory_groups_connection_id", "external_directory_groups", ["connection_id"])

    op.create_table(
        "external_directory_memberships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("is_nested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["ldap_connections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["external_directory_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["external_directory_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "connection_id", "user_id", "group_id", name="uq_ext_dir_membership"),
    )
    op.create_index("ix_external_directory_memberships_tenant_id", "external_directory_memberships", ["tenant_id"])

    op.create_table(
        "directory_group_role_mappings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("directory_group_guid", sa.String(length=64), nullable=False),
        sa.Column("group_display_name", sa.String(length=255), nullable=True),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_project_id", sa.Integer(), nullable=True),
        sa.Column("mapped_role", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["ldap_connections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "directory_group_guid",
            "target_type",
            "target_project_id",
            "mapped_role",
            name="uq_dir_group_role_mapping",
        ),
    )
    op.create_index("ix_directory_group_role_mappings_tenant_id", "directory_group_role_mappings", ["tenant_id"])

    op.create_table(
        "directory_sync_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("configuration_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("phase", sa.String(length=64), nullable=True),
        sa.Column("discovered_count", sa.Integer(), nullable=True),
        sa.Column("created_count", sa.Integer(), nullable=True),
        sa.Column("updated_count", sa.Integer(), nullable=True),
        sa.Column("suspended_count", sa.Integer(), nullable=True),
        sa.Column("granted_count", sa.Integer(), nullable=True),
        sa.Column("revoked_count", sa.Integer(), nullable=True),
        sa.Column("skipped_count", sa.Integer(), nullable=True),
        sa.Column("failed_count", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message_safe", sa.String(length=1024), nullable=True),
        sa.Column("initiated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["ldap_connections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["initiated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_directory_sync_runs_tenant_id", "directory_sync_runs", ["tenant_id"])
    op.create_index("ix_directory_sync_runs_connection_id", "directory_sync_runs", ["connection_id"])

    op.create_table(
        "directory_derived_grants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("mapping_id", sa.Integer(), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("directory_group_guid", sa.String(length=64), nullable=False),
        sa.Column("sync_run_id", sa.Integer(), nullable=True),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["mapping_id"], ["directory_group_role_mappings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["ldap_connections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sync_run_id"], ["directory_sync_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_directory_derived_grants_tenant_id", "directory_derived_grants", ["tenant_id"])
    op.create_index("ix_directory_derived_grants_user_id", "directory_derived_grants", ["user_id"])

    op.create_table(
        "user_auth_identities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider_type", sa.String(length=64), nullable=False),
        sa.Column("external_subject", sa.String(length=255), nullable=False),
        sa.Column("sso_provider_uuid", sa.String(length=255), nullable=True),
        sa.Column("directory_connection_id", sa.Integer(), nullable=True),
        sa.Column("verification_state", sa.String(length=32), nullable=False, server_default="confirmed"),
        sa.Column("linked_by", sa.Integer(), nullable=True),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_authenticated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synchronized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suspended", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["directory_connection_id"], ["ldap_connections.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["linked_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "provider_type", "external_subject", name="uq_user_auth_identity_subject"),
    )
    op.create_index("ix_user_auth_identities_tenant_id", "user_auth_identities", ["tenant_id"])
    op.create_index("ix_user_auth_identities_user_id", "user_auth_identities", ["user_id"])
    op.create_index("ix_user_auth_identities_external_subject", "user_auth_identities", ["external_subject"])

    op.create_table(
        "tenant_enterprise_auth_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("ldap_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sso_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sso_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("local_login_allowed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sso_provider_id_encrypted", sa.Text(), nullable=True),
        sa.Column("sso_provider_display_name", sa.String(length=255), nullable=True),
        sa.Column("sso_provider_entity_id_hash", sa.String(length=64), nullable=True),
        sa.Column("sso_status", sa.String(length=50), nullable=True),
        sa.Column("sso_last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sso_last_test_result", sa.String(length=512), nullable=True),
        sa.Column("ldap_connection_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ldap_connection_id"], ["ldap_connections.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", name="uq_tenant_enterprise_auth_settings_tenant_id"),
    )
    op.create_index("ix_tenant_enterprise_auth_settings_tenant_id", "tenant_enterprise_auth_settings", ["tenant_id"])

    op.execute(
        sa.text(
            """
            INSERT INTO user_auth_identities (
                tenant_id, user_id, provider_type, external_subject, verification_state, linked_at
            )
            SELECT
                tenant_id,
                id,
                'supabase_local',
                COALESCE(external_id, supabase_user_id),
                'confirmed',
                NOW()
            FROM users
            WHERE (external_id IS NOT NULL OR supabase_user_id IS NOT NULL)
            ON CONFLICT DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_table("tenant_enterprise_auth_settings")
    op.drop_table("user_auth_identities")
    op.drop_table("directory_derived_grants")
    op.drop_table("directory_sync_runs")
    op.drop_table("directory_group_role_mappings")
    op.drop_table("external_directory_memberships")
    op.drop_table("external_directory_groups")
    op.drop_table("external_directory_users")
    op.drop_table("ldap_connections")
