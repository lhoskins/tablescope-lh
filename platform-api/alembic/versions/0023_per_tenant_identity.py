"""Per-tenant identity: allow one Supabase email across multiple tenants.

Previously ``users.external_id`` was globally unique and login resolved a user
purely by that identity, so a single Supabase email could belong to only one
tenant. This relaxes identity to be unique *per tenant* so the same person can
be, e.g., ``root_admin`` in the ``root`` tenant and ``tenant_admin`` in a
customer tenant, logging in via each tenant's ``/{slug}/login``.

Revision ID: 0023
Revises: 0022
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def _constraints(conn: sa.engine.Connection, table: str) -> set[str]:
    insp = sa.inspect(conn)
    names: set[str] = set()
    for uc in insp.get_unique_constraints(table):
        if uc.get("name"):
            names.add(uc["name"])
    pk = insp.get_pk_constraint(table)
    if pk.get("name"):
        names.add(pk["name"])
    return names


def upgrade() -> None:
    conn = op.get_bind()

    # users: global unique(external_id) -> unique(tenant_id, external_id)
    users_cons = _constraints(conn, "users")
    if "users_external_id_key" in users_cons:
        op.drop_constraint("users_external_id_key", "users", type_="unique")
    if "uq_users_tenant_external_id" not in users_cons:
        op.create_unique_constraint(
            "uq_users_tenant_external_id", "users", ["tenant_id", "external_id"]
        )
    if "uq_users_tenant_supabase" not in users_cons:
        op.create_unique_constraint(
            "uq_users_tenant_supabase", "users", ["tenant_id", "supabase_user_id"]
        )

    # tenant_auth_bindings: global unique(provider, supabase_user_id)
    #   -> unique(tenant_id, provider, supabase_user_id)
    binding_cons = _constraints(conn, "tenant_auth_bindings")
    if "uq_auth_binding_provider_subject" in binding_cons:
        op.drop_constraint(
            "uq_auth_binding_provider_subject",
            "tenant_auth_bindings",
            type_="unique",
        )
    if "uq_auth_binding_tenant_provider_subject" not in binding_cons:
        op.create_unique_constraint(
            "uq_auth_binding_tenant_provider_subject",
            "tenant_auth_bindings",
            ["tenant_id", "provider", "supabase_user_id"],
        )


def downgrade() -> None:
    conn = op.get_bind()

    binding_cons = _constraints(conn, "tenant_auth_bindings")
    if "uq_auth_binding_tenant_provider_subject" in binding_cons:
        op.drop_constraint(
            "uq_auth_binding_tenant_provider_subject",
            "tenant_auth_bindings",
            type_="unique",
        )
    if "uq_auth_binding_provider_subject" not in binding_cons:
        op.create_unique_constraint(
            "uq_auth_binding_provider_subject",
            "tenant_auth_bindings",
            ["provider", "supabase_user_id"],
        )

    users_cons = _constraints(conn, "users")
    if "uq_users_tenant_supabase" in users_cons:
        op.drop_constraint("uq_users_tenant_supabase", "users", type_="unique")
    if "uq_users_tenant_external_id" in users_cons:
        op.drop_constraint("uq_users_tenant_external_id", "users", type_="unique")
    if "users_external_id_key" not in users_cons:
        op.create_unique_constraint("users_external_id_key", "users", ["external_id"])
