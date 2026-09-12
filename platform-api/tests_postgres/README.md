# PostgreSQL RLS readiness checks

These opt-in tests exercise the real API, SQLAlchemy transaction hook, workers,
and PostgreSQL policies with two synthetic tenants. Each case gets a new database
cloned from a **schema-only local template**; the clone is dropped on completion.
No production data is required. Docker and the platform API development
dependencies are prerequisites.

The matrix runs the same operations with:

| Stage | Context flag | Table enforcement |
| --- | --- | --- |
| `baseline` | false | disabled |
| `context-only` | true | disabled |
| `enforced` | true | enabled |

The application and worker roles are separate from the schema owner, have
`NOSUPERUSER NOBYPASSRLS`, and own no tables. Test roles receive table CRUD and
sequence privileges so failures isolate policy/context behavior.

The explicit diagnostic table set includes users, projects, VDB bindings,
project context, knowledge graph records, and provisioning requests. **It is not
a production canary recommendation.** Identity and provisioning are included to
detect lockouts before any production rollout.

## Run locally

From `platform-api`, start a disposable PostgreSQL instance:

```bash
docker run -d --name tablescope-rls-validation \
  -e POSTGRES_PASSWORD=local-rls-test-only \
  -e POSTGRES_DB=tablescope_rls_validation \
  -p 127.0.0.1:55432:5432 postgres:16.14-alpine

docker exec tablescope-rls-validation pg_isready -U postgres
```

Wait for `pg_isready` to succeed, then create the test roles and migrate the
empty template:

```bash
docker exec -i tablescope-rls-validation psql -U postgres -d postgres \
  -v ON_ERROR_STOP=1 <<'SQL'
CREATE ROLE tablescope_app LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD 'local-rls-test-only';
CREATE ROLE tablescope_worker LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD 'local-rls-test-only';
SQL

DATABASE_URL='postgresql+psycopg2://postgres:local-rls-test-only@127.0.0.1:55432/tablescope_rls_validation' \
  .venv/bin/alembic upgrade head

RLS_TEST_TEMPLATE_URL='postgresql+psycopg2://postgres:local-rls-test-only@127.0.0.1:55432/tablescope_rls_validation' \
  .venv/bin/python -m pytest -q tests_postgres --tb=short
```

All credentials above are exclusively for this local disposable database.
The fixture refuses a non-`127.0.0.1` host, a missing explicit port, a database
name other than `tablescope_rls_validation`, or a template with tenants/users.
It does not connect to the application's normal `DATABASE_URL`.
The template login needs permission to create/drop its test databases and grant
privileges. Never point it at a real application database.

To reproduce the deployed schema rather than a fresh migration history, restore
a reviewed `pg_dump --schema-only --no-owner --no-privileges` into the empty
template instead of running migrations. Do not restore customer rows.

```bash
docker stop tablescope-rls-validation
docker rm -v tablescope-rls-validation
```

## Interpreting results

The default SQLite suite does not collect this directory. An explicit run
without `RLS_TEST_TEMPLATE_URL` skips the checks. There are no `xfail` markers:
a broken operation is a failing readiness gate, even if other RLS checks pass.

SQL probes deliberately omit application tenant predicates. They cover
same-tenant CRUD, cross-tenant reads/writes and tenant-moving updates, missing
context, concurrent tenants, and reuse of the same PostgreSQL backend after
commit, rollback, and a database exception. Rollback uses
`scripts.manage_postgres_rls` and verifies policies remain installed.

API probes use HTTPX's ASGI transport with the real application and restricted
database sessions. They cover organization-aware password login, the deliberate
organization requirement when context is enabled, authenticated identity and
project access, refresh, membership revocation, project creation/update after
commit, service-key user listing, and public provisioning status. The Stripe
checkout lookup is stubbed locally; no payment provider is contacted. Worker
probes exercise VDB resolution and the tenant-scoped knowledge graph health check.

### Known readiness failures on `UX-design-05` at `d5ecd030`

These are product findings, not reasons to relax the assertions:

- Service-key user listing returns an empty list when `users` RLS is enabled:
  the service principal does not set a tenant context.
- Upload-worker VDB resolution returns `None` when VDB-binding RLS is enabled:
  `_resolve_vdb_id` uses an unscoped `SessionLocal`.
- Public provisioning status cannot find the checkout row when provisioning
  request RLS is enabled, including through the Stripe reference fallback:
  no authenticated tenant exists at this bootstrap point.

A successful run is necessary but insufficient for a full rollout. This suite
does not validate browser login/SSO/MFA/logout, actual uploads, Teiid execution,
dashboard rendering, AI inference, live payment processing, VPN provisioning,
PgBouncer transaction pooling, backup/restore recovery of customer data, tenant
deletion, or root-support workflows. Those require a representative staging
environment and a reviewed table/role inventory.
