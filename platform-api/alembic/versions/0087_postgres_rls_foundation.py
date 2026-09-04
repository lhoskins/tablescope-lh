"""Install the TS-ISO-004 PostgreSQL RLS foundation (disabled by default).

Revision ID: 0087
Revises: 0086

This migration deliberately creates tenant policies without enabling RLS.
Enabling every table during a normal application deploy could lock out login,
provisioning, and background workers before their runtime role/context rollout
is complete. Operators enable reviewed table waves with
``python -m scripts.manage_postgres_rls`` after the preflight passes.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0087"
down_revision: str | None = "0086"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

POLICY_NAME = "tablescope_tenant_isolation"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.tablescope_current_tenant_id()
        RETURNS bigint
        LANGUAGE sql
        STABLE
        PARALLEL SAFE
        AS $function$
          SELECT CASE
            WHEN current_setting('tablescope.tenant_id', true) ~ '^[1-9][0-9]*$'
            THEN current_setting('tablescope.tenant_id', true)::bigint
            ELSE NULL
          END
        $function$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.tablescope_current_user_id()
        RETURNS bigint
        LANGUAGE sql
        STABLE
        PARALLEL SAFE
        AS $function$
          SELECT CASE
            WHEN current_setting('tablescope.user_id', true) ~ '^[0-9]+$'
            THEN current_setting('tablescope.user_id', true)::bigint
            ELSE NULL
          END
        $function$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.tablescope_current_project_id()
        RETURNS bigint
        LANGUAGE sql
        STABLE
        PARALLEL SAFE
        AS $function$
          SELECT CASE
            WHEN current_setting('tablescope.project_id', true) ~ '^[1-9][0-9]*$'
            THEN current_setting('tablescope.project_id', true)::bigint
            ELSE NULL
          END
        $function$
        """
    )

    # Cover every ordinary/partitioned table whose tenant_id is an integer.
    # Text tenant identifiers (for example a deployment slug) require an
    # explicit mapping policy and are intentionally reported by the preflight
    # rather than coerced into the wrong security boundary.
    op.execute(
        sa.text(
            f"""
            DO $block$
            DECLARE target record;
            BEGIN
              FOR target IN
                SELECT n.nspname AS schema_name, c.relname AS table_name
                FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
                JOIN pg_catalog.pg_type t ON t.oid = a.atttypid
                WHERE n.nspname = current_schema()
                  AND c.relkind IN ('r', 'p')
                  AND a.attname = 'tenant_id'
                  AND NOT a.attisdropped
                  AND t.typname IN ('int2', 'int4', 'int8')
              LOOP
                EXECUTE format(
                  'DROP POLICY IF EXISTS %I ON %I.%I',
                  '{POLICY_NAME}', target.schema_name, target.table_name
                );
                EXECUTE format(
                  'CREATE POLICY %I ON %I.%I USING '
                  || '(tenant_id = public.tablescope_current_tenant_id()) '
                  || 'WITH CHECK (tenant_id = public.tablescope_current_tenant_id())',
                  '{POLICY_NAME}', target.schema_name, target.table_name
                );
              END LOOP;
            END
            $block$;
            """
        )
    )

    op.execute(
        "COMMENT ON FUNCTION public.tablescope_current_tenant_id() IS "
        "'TS-ISO-004 transaction-local tenant principal; NULL means deny tenant rows'"
    )


def downgrade() -> None:
    if not _is_postgres():
        return

    op.execute(
        sa.text(
            f"""
            DO $block$
            DECLARE target record;
            BEGIN
              FOR target IN
                SELECT schemaname, tablename
                FROM pg_catalog.pg_policies
                WHERE policyname = '{POLICY_NAME}'
              LOOP
                -- An operator may have enabled a reviewed wave after this
                -- migration. Disable those tables before dropping the only
                -- tenant policy; enabled RLS with no policy is a total lockout.
                EXECUTE format(
                  'ALTER TABLE %I.%I DISABLE ROW LEVEL SECURITY',
                  target.schemaname, target.tablename
                );
                EXECUTE format(
                  'DROP POLICY IF EXISTS %I ON %I.%I',
                  '{POLICY_NAME}', target.schemaname, target.tablename
                );
              END LOOP;
            END
            $block$;
            """
        )
    )
    op.execute("DROP FUNCTION IF EXISTS public.tablescope_current_project_id()")
    op.execute("DROP FUNCTION IF EXISTS public.tablescope_current_user_id()")
    op.execute("DROP FUNCTION IF EXISTS public.tablescope_current_tenant_id()")
