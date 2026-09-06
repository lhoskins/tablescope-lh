# TS-ISO-004 — PostgreSQL RLS design and lockout-safe rollout

**Base branch:** `lhoskins/tablescope-lh:UX-design-02`  
**Finding:** Application predicates are the only general PostgreSQL tenant barrier  
**Goal:** Add an independent, fail-closed tenant barrier without changing the current authorization decision or locking out users, workers, migrations, provisioning, and recovery operators.

## Executive decision

RLS must be introduced in waves. The Alembic migration in this change installs policies but deliberately leaves every table's RLS switch disabled. A separate guarded command enables only an explicitly named canary set after context propagation and the runtime-role split are proven.

This is not cosmetic staging. Enabling RLS globally today would break several valid flows:

- anonymous login and SSO do not know the tenant until a slug is resolved;
- the public provisioning-status capability does not have a logged-in tenant;
- service API keys currently synthesize tenant/user `0`;
- background workers frequently create `SessionLocal` directly;
- migrations and repair tools need controlled cross-tenant access;
- root support and deletion workflows may intentionally operate across tenants;
- several child tables have `project_id` or parent IDs but no `tenant_id`.

The deployment therefore remains behaviorally unchanged until an operator explicitly enables a reviewed table wave.

## Design changes

### 1. Separate database identities

Production should use at least these roles:

| Role | Purpose | Required attributes |
|---|---|---|
| `tablescope_migrator` | Alembic, schema ownership, break-glass repair | `NOLOGIN` where possible; table owner; tightly controlled assume-role path |
| `tablescope_app` | FastAPI requests | `LOGIN NOSUPERUSER NOBYPASSRLS`; never owns an RLS table |
| `tablescope_worker` | Tenant-scoped asynchronous jobs | `LOGIN NOSUPERUSER NOBYPASSRLS`; never owns an RLS table |
| `tablescope_auditor` | Read-only security verification | `LOGIN NOSUPERUSER NOBYPASSRLS`; no write grants |

Do not run the application as `postgres`, a superuser, a role with `BYPASSRLS`, or the table owner. PostgreSQL exempts those identities from ordinary RLS unless `FORCE ROW LEVEL SECURITY` is used. This change intentionally does not force RLS because doing so would also affect the owning migration/recovery path.

### 2. Transaction-local principal propagation

Authenticated requests bind `tenant_id` and `user_id` in a Python `ContextVar`. SQLAlchemy copies the values into the database transaction using:

```sql
set_config('tablescope.tenant_id', '<id>', true);
set_config('tablescope.user_id', '<id>', true);
set_config('tablescope.project_id', '<id-or-empty>', true);
```

The final argument is `true`, equivalent to `SET LOCAL`. Values disappear at transaction end, including when a pooled connection is reused. Missing values become `NULL`; they never default to tenant zero or a prior request.

The GUC values are not an authorization source. Authentication, active membership, role checks, MFA, and `ProjectAccessPolicy` remain authoritative at the application layer. RLS only rejects rows that do not match the already-authorized tenant.

### 3. Authentication bootstrap

JWT requests know the principal before any route query and are scoped by middleware. Login and SSO are different:

1. Query the global `tenants` table by an exact tenant slug.
2. Set transaction-local tenant context with bootstrap user `0`.
3. Resolve the tenant-scoped user/identity.
4. Replace user `0` with the canonical user ID.
5. Continue existing password, external-token, active-status, domain, and MFA checks.

When RLS context propagation is enabled, direct login requires an organization slug. This prevents both an RLS lockout and the TS-ISO-015 duplicate-email ambiguity. Before activation, existing optional-slug behavior remains unchanged.

### 4. Tenant policy

The migration adds `tablescope_tenant_isolation` to every ordinary or partitioned table with an integer `tenant_id`:

```sql
USING (tenant_id = public.tablescope_current_tenant_id())
WITH CHECK (tenant_id = public.tablescope_current_tenant_id())
```

`USING` protects reads, updates, and deletes. `WITH CHECK` prevents inserts or tenant-moving updates into another tenant. The policies contain no operator-controlled `bypass=true` GUC; any login role can set a custom GUC, so using one as a bypass would be a security bug.

Tables using a textual tenant slug are not coerced into this policy. They require a reviewed mapping to the canonical numeric tenant. The status/preflight output must track those exclusions.

### 5. Project isolation decision

This phase propagates `project_id` but does **not** add a universal `project_id = current_project_id()` policy. That policy would break valid operations that span multiple authorized projects, including Business Insights, Home intelligence, tenant dashboards, administration, project lists, and membership management.

Project RLS needs one of these later designs:

1. a transaction-local array of authorized project IDs populated from current active memberships;
2. policy joins to a session-principal/active-membership relation;
3. denormalized `tenant_id` plus route-specific project policy families.

The recommended next step is option 2 for interactive reads and explicit tenant-scoped worker claims for analytics. Until that design is implemented, centralized application project authorization remains mandatory.

## Authentication and lockout matrix

| Flow | Context source | Before table enablement | Requirement before its tables are enabled |
|---|---|---|---|
| JWT user request | Verified first-party token, then DB membership revalidation | No behavior change | Tenant context hook on; active-member tests pass |
| Password login | Exact tenant slug | No behavior change while flag is off | Tenant slug required; bootstrap tests pass |
| Supabase/Clerk exchange | Exact tenant slug | No behavior change | Bootstrap tenant context before identity lookup |
| SSO policy/start | URL/payload tenant slug | No behavior change | Bootstrap tenant context before enterprise settings lookup |
| Service API key | No global tenant permitted | No behavior change | Route must bind a concrete canonical tenant or use a separately reviewed control-plane role |
| Worker job | Signed/canonical job payload | No behavior change | Wrap every DB transaction in `rls_scope`; reload and verify canonical tenant/project first |
| Provisioning status | Checkout session capability | No behavior change | Dedicated narrowly scoped SECURITY DEFINER lookup or separate control-plane role |
| Alembic | Migrator identity | Policies installed disabled | Migrator owns schema; app/worker do not |
| Root support | Explicit tenant switch | No behavior change | Every action binds one selected tenant and is audited; no invisible all-tenant bypass |
| Tenant deletion | Canonical deletion job | No behavior change | Explicit tenant scope plus separately controlled purge role for cross-store orchestration |

## What is included in this branch

- Request/task-local `RlsPrincipal` with concurrency-safe nesting.
- Automatic `SET LOCAL` injection at SQLAlchemy transaction start.
- Explicit login/SSO bootstrap after tenant-slug resolution.
- Default-off `POSTGRES_RLS_CONTEXT_ENABLED` switch.
- Alembic `0087` helper functions and disabled tenant policies.
- `manage_postgres_rls` status, dry-run, enable, and disable operations.
- Refusal to enable when the runtime role is superuser, `BYPASSRLS`, or table owner.
- Unit tests for nesting, async isolation, invalid identifiers, bootstrap SQL, and default-off behavior.

## Intentional blockers before production enforcement

The following must be completed before any broad enablement:

1. Inventory all tables without numeric `tenant_id`; add canonical tenant linkage to tenant-owned child tables.
2. Convert every worker and scheduled task that touches tenant data to an explicit `rls_scope`.
3. Replace service tenant `0` behavior with a concrete tenant claim or narrow control-plane role.
4. Redesign the public provisioning-status lookup so it does not require unrestricted table access.
5. Decide and test root-support tenant switching and break-glass logging.
6. Run two-tenant integration tests against a disposable PostgreSQL instance using the real non-owner runtime role.
7. Confirm connection poolers use transaction pooling safely; session pooling must still rely on `SET LOCAL`.
8. Verify backup, restore, migration, tenant deletion, and rollback under the split roles.

## Deployment sequence

### Phase 0 — backup and evidence

1. Record the application commit, database schema revision, database role/grant dump, and current RLS state.
2. Take and verify a restorable database snapshot.
3. Seed canary tenants A and B, two projects each, active and removed users, private documents, dashboards, queries, conversations, and worker jobs.

### Phase 1 — deploy inert foundation

1. Deploy application code with `POSTGRES_RLS_CONTEXT_ENABLED=false`.
2. Run `alembic upgrade head`; revision `0087` creates policies but does not enable RLS.
3. Run `python -m scripts.manage_postgres_rls status` and retain the output.
4. Execute the existing authentication, project, billing, provisioning, and worker regression suites. Behavior must remain unchanged.

### Phase 2 — split roles and propagate context

1. Create `tablescope_app` and `tablescope_worker` as non-owner, `NOBYPASSRLS` roles.
2. Grant only required schema/table/sequence/function privileges.
3. Update request and worker database URLs separately.
4. Set `POSTGRES_RLS_CONTEXT_ENABLED=true` on app and worker canaries.
5. Keep policies disabled and verify login, SSO, MFA, role changes, project removal, jobs, and connection-pool reuse.

### Phase 3 — canary table wave

Dry-run first:

```bash
cd platform-api
python -m scripts.manage_postgres_rls enable \
  --runtime-role tablescope_app \
  --tables <explicit-reviewed-table-list>
```

Apply only after the output and tests are approved:

```bash
python -m scripts.manage_postgres_rls enable \
  --runtime-role tablescope_app \
  --tables <same-explicit-list> \
  --apply
```

Start with low-blast-radius tenant data that has no public/service/worker path. Do not begin with `users`, identity, billing, provisioning, job, or audit tables.

### Phase 4 — expand in monitored waves

For every wave, run:

- missing-predicate direct SQL probes;
- tenant A/B read, insert, update, and delete denial tests;
- login/SSO/MFA/logout and role-change tests;
- active-to-removed-member revocation tests;
- worker retry/idempotency tests;
- pool reuse tests proving tenant A context cannot reach tenant B;
- latency and PostgreSQL query-plan comparison;
- an immediate rollback drill.

## Rollback

RLS can be disabled without dropping policies or reverting application code:

```bash
python -m scripts.manage_postgres_rls disable \
  --tables <last-enabled-wave> \
  --apply
```

Then set `POSTGRES_RLS_CONTEXT_ENABLED=false` only after the affected application instances are drained. Do not fix a lockout by granting `SUPERUSER`, `BYPASSRLS`, table ownership, or a user-settable bypass GUC to the runtime role.

## Acceptance criteria

- Target runtime roles are `NOSUPERUSER NOBYPASSRLS` and own no protected tables.
- An authenticated tenant A transaction missing an application tenant predicate cannot read or mutate tenant B.
- A transaction with no tenant context returns no tenant rows and cannot insert one.
- Login, exchange, SSO, MFA, refresh, logout, provisioning, workers, and root-support flows pass their matrix.
- Removing a member terminates project access on the next operation.
- No request/task context survives transaction completion or pooled-connection reuse.
- RLS overhead and query plans meet the production SLO.
- Rollback is tested and does not require privilege escalation.

