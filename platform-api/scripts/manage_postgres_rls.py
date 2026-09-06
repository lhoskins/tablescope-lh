"""Inspect and safely enable TS-ISO-004 tenant RLS table waves.

Examples (from ``platform-api``)::

    python -m scripts.manage_postgres_rls status
    python -m scripts.manage_postgres_rls enable --runtime-role tablescope_app \
        --tables users projects --apply
    python -m scripts.manage_postgres_rls disable --tables users projects --apply

The command refuses an enable when the runtime role is superuser, has
``BYPASSRLS``, owns a selected table, or when the policy is missing. It never
uses ``FORCE ROW LEVEL SECURITY`` and never enables every table implicitly.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

import sqlalchemy as sa

POLICY_NAME = "tablescope_tenant_isolation"


@dataclass(frozen=True)
class TableState:
    schema: str
    table: str
    owner: str
    rls_enabled: bool
    rls_forced: bool

    @property
    def qualified(self) -> str:
        return f'{self.schema}."{self.table}"'


def _sync_database_url() -> str:
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        raise SystemExit("DATABASE_URL is required")
    return raw.replace("+asyncpg", "+psycopg2")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    for name in ("enable", "disable"):
        command = sub.add_parser(name)
        command.add_argument("--tables", nargs="+", required=True)
        command.add_argument("--apply", action="store_true")
        if name == "enable":
            command.add_argument("--runtime-role", required=True)
    return parser


def _states(connection: sa.Connection) -> dict[str, TableState]:
    rows = connection.execute(
        sa.text(
            """
            SELECT p.schemaname, p.tablename,
                   pg_get_userbyid(c.relowner) AS owner,
                   c.relrowsecurity, c.relforcerowsecurity
            FROM pg_catalog.pg_policies p
            JOIN pg_catalog.pg_namespace n ON n.nspname = p.schemaname
            JOIN pg_catalog.pg_class c
              ON c.relnamespace = n.oid AND c.relname = p.tablename
            WHERE p.policyname = :policy
            ORDER BY p.schemaname, p.tablename
            """
        ),
        {"policy": POLICY_NAME},
    )
    return {
        row.tablename: TableState(
            schema=row.schemaname,
            table=row.tablename,
            owner=row.owner,
            rls_enabled=row.relrowsecurity,
            rls_forced=row.relforcerowsecurity,
        )
        for row in rows
    }


def _role(connection: sa.Connection, name: str) -> sa.Row:
    row = connection.execute(
        sa.text(
            "SELECT rolname, rolsuper, rolbypassrls FROM pg_catalog.pg_roles "
            "WHERE rolname = :name"
        ),
        {"name": name},
    ).one_or_none()
    if row is None:
        raise SystemExit(f"Runtime role {name!r} does not exist")
    return row


def _selected(states: dict[str, TableState], names: list[str]) -> list[TableState]:
    unknown = sorted(set(names) - states.keys())
    if unknown:
        raise SystemExit("No TS-ISO-004 policy exists for: " + ", ".join(unknown))
    return [states[name] for name in names]


def _policy_exclusions(connection: sa.Connection) -> tuple[list[str], list[str]]:
    """Return non-integer tenant columns and project-only child tables."""

    non_integer = connection.execute(
        sa.text(
            """
            SELECT n.nspname || '.' || c.relname
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
            JOIN pg_catalog.pg_type t ON t.oid = a.atttypid
            WHERE n.nspname = current_schema()
              AND c.relkind IN ('r', 'p')
              AND a.attname = 'tenant_id'
              AND NOT a.attisdropped
              AND t.typname NOT IN ('int2', 'int4', 'int8')
            ORDER BY 1
            """
        )
    ).scalars()
    project_only = connection.execute(
        sa.text(
            """
            SELECT n.nspname || '.' || c.relname
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = current_schema()
              AND c.relkind IN ('r', 'p')
              AND EXISTS (
                SELECT 1 FROM pg_catalog.pg_attribute a
                WHERE a.attrelid = c.oid AND a.attname = 'project_id'
                  AND NOT a.attisdropped
              )
              AND NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_attribute a
                WHERE a.attrelid = c.oid AND a.attname = 'tenant_id'
                  AND NOT a.attisdropped
              )
            ORDER BY 1
            """
        )
    ).scalars()
    return list(non_integer), list(project_only)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    engine = sa.create_engine(_sync_database_url(), future=True)
    with engine.begin() as connection:
        if connection.dialect.name != "postgresql":
            raise SystemExit("TS-ISO-004 RLS requires PostgreSQL")
        states = _states(connection)
        if args.command == "status":
            if not states:
                print("No TS-ISO-004 policies found; run Alembic upgrade first.")
                return 1
            print("table\towner\tenabled\tforced")
            for state in states.values():
                print(
                    f"{state.qualified}\t{state.owner}\t"
                    f"{state.rls_enabled}\t{state.rls_forced}"
                )
            non_integer, project_only = _policy_exclusions(connection)
            if non_integer:
                print("\nEXCLUDED non-integer tenant_id tables (explicit mapping required):")
                print("\n".join(non_integer))
            if project_only:
                print("\nPROJECT-ONLY child tables (tenant linkage required):")
                print("\n".join(project_only))
            return 0

        selected = _selected(states, args.tables)
        if args.command == "enable":
            runtime = _role(connection, args.runtime_role)
            if runtime.rolsuper or runtime.rolbypassrls:
                raise SystemExit(
                    "Refusing enable: runtime role must be NOSUPERUSER NOBYPASSRLS"
                )
            owned = [state.table for state in selected if state.owner == runtime.rolname]
            if owned:
                raise SystemExit(
                    "Refusing enable: runtime role owns RLS tables and would bypass "
                    "policies: " + ", ".join(owned)
                )

        action = "ENABLE" if args.command == "enable" else "DISABLE"
        quote = connection.dialect.identifier_preparer.quote_identifier
        statements = [
            f"ALTER TABLE {quote(state.schema)}.{quote(state.table)} "
            f"{action} ROW LEVEL SECURITY"
            for state in selected
        ]
        for statement in statements:
            print(statement + ";")
        if not args.apply:
            print("Dry run only. Re-run with --apply after canary validation.")
            return 0
        for statement in statements:
            connection.execute(sa.text(statement))
    return 0


if __name__ == "__main__":
    sys.exit(main())
