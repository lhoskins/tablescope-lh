# TS-ISO-014: Service Identity Scoping — Standalone Implementation Plan

**Status:** Open — broad service-key bypass remains; implementation required

**Severity:** Medium

**Owner:** Platform / Identity / Security / Data Plane / Operations

**Target branch:** `UX-design-03`

**Plan branch:** `codex/ts-iso-014-service-identity-scoping`

**Depends on:** TS-ISO-004 (PostgreSQL RLS foundation)
**Related findings:** TS-ISO-010 (file-proxy hardening), TS-ISO-012 (data-plane fallback completion), TS-ISO-013 (user session hardening)

## 1. Objective

Replace TableScope's shared, static, platform-administrator service API keys with explicit workload identities whose credentials, audience, tenant, project, method, route, and capabilities are narrowly scoped and independently revocable.

Human endpoints must reject workload principals by default. A workload may invoke only a reviewed machine endpoint and capability, for one documented purpose and resource scope. Tenant-data work must carry a concrete tenant identity and participate in the same database isolation boundary as the authorized job; a synthetic tenant or user `0` must never grant cross-tenant access.

## 2. Current-state finding

The repository distinguishes service requests from user requests, but the service path is a global bypass rather than an identity and authorization model:

| Area | Current behavior | Security gap |
|---|---|---|
| Credential configuration | `SERVICE_API_KEYS` is a comma-separated set of plaintext static secrets | A key has no name, owner, purpose, environment, audience, tenant, expiry, generation, or granular revocation record |
| Authentication | `X-API-Key` membership in that set synthesizes `sub=service:<prefix>` | The prefix is not a durable identity and key rotation cannot preserve attribution |
| Claims | Service claims use `tenant_id=0`, `user_id=0`, `role=admin`, and `permissions=["service:*"]` | Authentication creates authority that was not derived from a reviewed grant |
| Membership | `require_membership()` returns immediately for `context.is_service` | Services skip live tenant membership and MFA checks without an equivalent workload policy |
| Role and permission checks | `require_role()`, `require_permission()`, and `require_platform_admin()` accept every service | Most routes become service-accessible unless each author remembers to add a manual rejection |
| Route handling | Some routes reject service identities, others explicitly allow them, and many inherit the dependency bypass | The effective service API is implicit, difficult to inventory, and permissive by omission |
| PostgreSQL RLS | Service requests carry tenant `0`; the RLS design notes they have no valid tenant scope | Tenant-data service work cannot safely use the independent database boundary |
| Tests | The shared `service_headers` fixture creates tenants, users, and data through production routes | Test setup normalizes global service-administrator behavior and makes removal appear broadly incompatible |
| Internal AI | Platform/AI calls have a separate HMAC envelope and replay mechanism | Identity/capability rules are not unified; replay storage currently has fail-open behavior in part of the path |
| Teiid/data-plane clients | Global servlet credentials and tenant secret references coexist | A shared key plus broad network access weakens attribution and tenant containment |

### Root cause

The API key was introduced as an internal bootstrap mechanism, and `is_service` became an exception in the human RBAC dependencies. That makes every route's security depend on remembering a negative check. The system authenticates possession of a shared secret, but does not authorize a named workload for a bounded operation.

## 3. Scope and non-goals

This plan covers:

- machine principal and credential persistence;
- short-lived workload authentication and bounded legacy-key transition;
- route, HTTP method, audience, purpose, tenant, project, and capability authorization;
- request context, RBAC/membership dependencies, RLS propagation, and audit attribution;
- service-allowed route inventory and default-deny enforcement;
- internal AI, workers, schedulers, provisioning, deletion, data-plane, and Teiid workload integration;
- credential issuance, rotation, expiry, revocation, monitoring, and tests.

This plan does not turn service identities into user sessions or tenant memberships. It does not authorize arbitrary URL forwarding, shell execution, database bypass, or human administration. Network isolation and data-plane routing remain owned by TS-ISO-010 and TS-ISO-012, while this plan supplies the workload identity they consume.

## 4. Security invariants

1. Every machine request maps to one durable, named workload identity and one active credential generation.
2. A workload principal has no human role, user ID, tenant membership, or implicit platform-admin status.
3. Human routes reject workload principals unless the route is explicitly declared machine-callable.
4. Machine authorization is an allowlist of exact capabilities bound to HTTP method, canonical route, audience, and purpose.
5. Tenant-data capabilities require a concrete canonical tenant; project-data capabilities also require a concrete authorized project.
6. A workload can never select its tenant, project, destination, or capability merely by adding an untrusted request field.
7. Workload database transactions use a non-owner, `NOBYPASSRLS` runtime role and set the verified tenant context.
8. Unknown identity, capability, route, audience, purpose, tenant, credential version, or policy version fails closed.
9. Credentials expire, rotate, and revoke independently; plaintext secrets never reside in database rows, logs, URLs, traces, or analytics.
10. Replayed, expired, future-dated, wrong-audience, and body/path-substituted requests are rejected before route execution.
11. A service-store or replay-store outage cannot grant a mutation or broaden tenant scope.
12. Authorization decisions remain attributable to the workload, credential generation, tenant, project, request ID, and capability without recording secret or customer payload data.

## 5. Target design

### 5.1 Workload identity model

Add persistent `service_identities`, `service_identity_permissions`, and `service_identity_credentials` models. Use UUIDs for externally referenced identity and credential IDs.

Recommended `service_identities` fields:

```text
id UUID PRIMARY KEY
name VARCHAR NOT NULL UNIQUE
workload_type VARCHAR NOT NULL
environment VARCHAR NOT NULL
status ENUM(active, disabled, revoked) NOT NULL
audience VARCHAR NOT NULL
tenant_scope_type ENUM(none, single_tenant, delegated_tenant) NOT NULL
tenant_id BIGINT NULL
purpose VARCHAR NOT NULL
policy_version INTEGER NOT NULL DEFAULT 1
owner_team VARCHAR NOT NULL
created_by / approved_by BIGINT
created_at / updated_at / disabled_at / revoked_at TIMESTAMPTZ
last_used_at TIMESTAMPTZ
```

Recommended permission fields:

```text
service_identity_id UUID NOT NULL
capability VARCHAR NOT NULL
http_method VARCHAR NOT NULL
route_template VARCHAR NOT NULL
project_scope_type ENUM(none, bound, delegated) NOT NULL
resource_constraints JSONB NOT NULL DEFAULT '{}'
not_before / expires_at TIMESTAMPTZ
```

Recommended credential fields:

```text
id UUID PRIMARY KEY                         # public key ID, never the secret
service_identity_id UUID NOT NULL
credential_type ENUM(mtls, oidc, hmac) NOT NULL
secret_hash_or_reference VARCHAR NULL
public_key_or_certificate_reference VARCHAR NULL
generation INTEGER NOT NULL
status ENUM(pending, active, retiring, revoked) NOT NULL
not_before / expires_at / last_used_at TIMESTAMPTZ
revoked_at TIMESTAMPTZ
```

Keep immutable lifecycle and authorization-change events in a separate audit relation. Store only a keyed hash or managed-secret reference for symmetric material. Do not persist a recoverable API key.

Use separate identities for at least the AI service, general job scheduler, tenant-scoped worker/gateway, provisioning agent, deletion orchestrator, Teiid/VDB manager, and inbound webhook verifier. Do not share one credential across services, environments, tenants, or purposes.

### 5.2 Principal and request context

Replace the boolean exception model with an explicit principal union:

```text
principal_type = user | workload
principal_id
tenant_id? / project_id?
audience
capabilities
credential_id / credential_generation
policy_version
```

For user principals, retain the canonical user, membership, role, MFA, and permission flow. For workload principals:

- do not synthesize `role=admin`, `permissions=service:*`, `user_id=0`, or `tenant_id=0`;
- expose no `.role` or `.user_id` value that downstream code can mistake for human authority;
- bind tenant/project only after trusted identity policy and request resource resolution agree;
- include the workload principal in RLS and audit context separately from an optional initiating human actor.

Where a background job was initiated by a user, preserve two identities: `actor_user_id` for provenance and `workload_principal_id` for the process executing it. The actor is not a reusable bearer delegation and must not silently grant more than the queued, signed job capability.

### 5.3 Authentication mechanism

Preferred production order:

1. cloud workload identity or SPIFFE/SPIRE-style identity exchanged for a short-lived TableScope workload token;
2. mutually authenticated TLS with certificate identity and short-lived authorization token;
3. versioned HMAC credentials only where the first two are not operationally available.

A TableScope workload token must be short-lived, signed with a versioned key, and contain issuer, audience, subject identity, credential/policy generation, tenant/project constraints, capability set, `iat`, `nbf`, `exp`, and unique `jti`. Mint it only after validating the external workload identity against a configured trust policy.

If HMAC request signing is retained for an integration, require:

```text
credential_id
timestamp
request_id / nonce
HTTP method
canonical route template and canonical path
canonical query
body digest
audience
tenant/project binding where applicable
signature
```

Use a narrow clock window and atomic replay registration. Mutations fail closed if replay protection is unavailable. Verification must use constant-time comparison and must occur before body-driven resource lookup causes a side effect.

### 5.4 Default-deny authorization dependencies

Human dependencies must reject workload principals by default:

- `require_membership`, `require_role`, `require_permission`, and `require_platform_admin` accept only a user principal;
- retain or rename `require_human_platform_admin` as the explicit human privileged guard;
- remove every `if context.is_service` grant or rejection branch after callers migrate.

Add a separate dependency such as:

```text
require_workload_capability(
    "vdb.deploy",
    methods={"POST"},
    audience="platform-api",
    tenant_source="trusted_binding",
)
```

The dependency must verify the exact matched route template and HTTP method, not a caller-controlled path string. It must compare path tenant/project identifiers with the authorized resource resolved from the identity, job, or binding. Platform-wide identities may receive only reviewed non-tenant control-plane capabilities; they must not inherit user, billing, governance, support, or root-administration APIs.

Maintain a code-owned route/capability registry and generate its review artifact in CI. Startup and CI must fail when:

- a machine-callable route lacks an exact registry entry;
- a registry entry no longer maps to a real route and method;
- a human dependency accepts a workload;
- production code uses `service:*`, synthetic tenant/user zero, or `context.is_service` bypass logic;
- a workload capability uses wildcard route or method matching.

### 5.5 Tenant, project, and RLS scoping

Tenant-scoped workload identities use one of two modes:

- `single_tenant`: the identity is permanently bound to one canonical tenant;
- `delegated_tenant`: a control-plane scheduler submits a signed job whose tenant, project, purpose, and generation are validated against authoritative records before minting a one-job token.

Do not accept a generic multi-tenant bearer token. A scheduler that can mint tenant jobs is a control-plane capability, not direct tenant-data access.

Before any tenant query, bind the verified tenant and optional project through the TS-ISO-004 RLS scope. The runtime database identity remains `NOSUPERUSER NOBYPASSRLS` and owns no protected table. A missing scope returns no tenant rows and cannot insert or mutate one. No workload is assigned the migration, owner, support, or deletion-purge database role through the API authentication path.

Long-running and retried jobs must revalidate the identity, credential generation, job generation, tenant status, and binding immediately before execution. Cached clients and pools must be keyed by workload identity, tenant, binding generation, and credential version.

### 5.6 Service-specific integration

- **AI service:** align the existing signed platform/AI envelope with the central identity, audience, capability, and replay policy. Permission callbacks remain live and fail closed; a cached HMAC secret is not a platform-admin credential.
- **Tenant gateway and workers:** use a single-tenant identity bound to data-plane generation and allowed gateway operations from TS-ISO-012.
- **File proxy:** reuse TS-ISO-010's canonical request signing and one-time capability for object operations; do not expose an arbitrary fetch capability.
- **Provisioning:** allow exact lifecycle operations against the provisioned tenant/data-plane record. Separate create, activate, rotate, quarantine, and destroy capabilities.
- **Deletion:** use a deletion-job identity bound to one quarantined tenant and deletion generation. Cross-store purge authority must not exist outside the TS-ISO-011 workflow.
- **Teiid/VDB:** resolve a tenant-specific credential/reference and exact management capability. Remove fallback to a global servlet key for isolated tenants.
- **Webhooks:** authenticate the external provider under a provider-specific verifier and enqueue a constrained internal job; never translate an inbound signature into the global internal service role.

### 5.7 Credential lifecycle and administration

Create human-administrator APIs or commands for identity inventory, creation, approval, permission review, rotation, disablement, and revocation. Secret material is shown exactly once at issuance only when a managed identity/certificate cannot be used.

- Require current human platform-admin MFA/step-up for creation, scope expansion, rotation approval, or revocation.
- Require a reason, owner team, expiry, environment, audience, and purpose.
- Support a bounded current/next credential overlap; permission expansion requires a new policy version.
- Revocation invalidates token caches, client pools, queued-job authorization, and active gateway sessions promptly.
- Alert on use after retirement, denied capability, tenant mismatch, wrong audience, replay, unusual volume, dormant identity use, and near-expiry credentials.
- Run an owner-attestation review and automatically disable expired or orphaned identities.

Audit events contain identity/credential IDs, generation, capability, tenant/project, route template, method, decision, safe reason code, request ID, and timing. Never log secret material, authorization headers, request bodies, S3 keys, query text, or customer data.

## 6. Implementation work breakdown

### Phase A — Inventory and schema

1. Generate a complete route matrix showing which routes currently accept `is_service`, whether by explicit condition or inherited dependency bypass.
2. Inventory every configured service key, caller, environment, owner, purpose, tenant reach, and rotation path.
3. Add workload identity, permission, credential, and immutable event models/migration.
4. Add typed principal/context models without changing existing user authorization behavior.
5. Define the reviewed capability vocabulary and exact route/method registry.

### Phase B — Authentication and authorization core

1. Implement managed-identity/mTLS exchange and the bounded HMAC adapter required during migration.
2. Implement workload token validation, generation checks, audience validation, replay protection, and safe audit decisions.
3. Make all human membership/RBAC dependencies reject workloads.
4. Add `require_workload_capability` with exact route, method, tenant, project, purpose, and policy checks.
5. Bind verified workload tenant/project to the RLS and audit context.

### Phase C — Caller migration

1. Issue distinct identities to AI, scheduler, workers/gateways, provisioning, deletion, Teiid/VDB, and webhook workloads.
2. Add dedicated machine endpoints where a current human route is being used for automation; do not annotate broad CRUD/admin routes for convenience.
3. Migrate signed job payloads and client libraries to request short-lived capability tokens.
4. Replace global servlet/internal keys with secret references scoped to tenant and purpose.
5. Replace broad integration tests with direct data factories or narrowly scoped identities.

### Phase D — Default-deny enforcement

1. Deploy route-registry CI and startup verification in report-only mode.
2. Enable exact authorization for canary workloads and compare denial/audit results with expected traffic.
3. Disable the canary's old `SERVICE_API_KEYS` entry and verify all positive and negative route cases.
4. Repeat per workload, then remove global service-key configuration and synthetic service claims.
5. Make replay, identity-policy, revocation-cache, and RLS uncertainty fail closed for protected operations.

### Phase E — Operations and cleanup

1. Add identity inventory, attestation, rotation, revocation, and compromise-response runbooks.
2. Add alerting and dashboards for workload denials, replays, tenant/audience mismatches, stale identities, and credential expiry.
3. Remove `context.is_service`, `service:*`, tenant/user zero, and shared `service_headers` fixtures.
4. Run credential compromise, rotation overlap, RLS, failover, and rollback drills.
5. Require security review for every new capability and machine-callable route.

## 7. Expected file changes

| Area | Expected files |
|---|---|
| Principal/context | `platform-api/app/auth/context.py`, `middleware.py`, `membership.py`, `rbac.py` |
| Models/migration | new service-identity models, model exports, and a new Alembic revision |
| Authentication | new workload token/exchange, HMAC verification, replay, and credential lifecycle services |
| Authorization | new capability registry/dependency and route-introspection/static-check tooling |
| Configuration | `platform-api/app/config.py`, `.env.example`, `platform-api/.env.example`, deployment secret references |
| Routes | current service-aware tenant, security-policy, scope, storage, billing, data-plane, and administration routes; new machine-specific routes |
| Workloads | AI signing clients, workers/scheduler, provisioning, deletion, tenant gateway, Teiid/VDB clients, webhook consumers |
| RLS/audit | TS-ISO-004 context propagation, request audit/security-event modules, pool/cache invalidation |
| Tests | auth context/RBAC, complete route matrix, replay, rotation, tenant/project isolation, workload-specific integrations |
| Operations | identity inventory, issuance, rotation, revocation, attestation, compromise, deployment, and rollback runbooks |

Exact paths and the Alembic revision must be confirmed against the repository head when implementation begins.

## 8. API and capability contract

Prefer dedicated internal route groups such as `/api/internal/v1/...` whose handlers cannot also be reached through human CRUD endpoints. Example capabilities are illustrative and must be derived from the route inventory:

```text
ai.permissions.read
ai.grounding.request
jobs.tenant.execute
data_plane.health.report
data_plane.vdb.deploy
data_plane.file.acquire
provisioning.tenant.advance
deletion.tenant.advance
```

Capability names describe one action; they are not role names and do not imply descendants. `data_plane.vdb.deploy` does not grant `data_plane.*`, read access, deletion, or another method. Route handlers must authorize again at the object boundary before side effects.

Identity administration responses are always redacted. APIs never return a stored secret, secret reference value, token signature, or full certificate private material. List and audit endpoints expose only metadata required for review.

## 9. Test plan

### Authentication and cryptography

- Valid managed/mTLS/HMAC identity maps to the expected durable principal and current generation.
- Unknown, disabled, revoked, expired, future-dated, wrong-environment, and wrong-audience credentials fail before route execution.
- Method, canonical path, query, body, tenant, and audience substitution invalidates a signed request.
- Duplicate nonce/request ID is rejected; replay-store failure cannot authorize a mutation.
- Rotation accepts only the documented bounded overlap and rejects the retired generation immediately afterward.
- Secret values and signed payloads never appear in logs, errors, traces, metrics, or audit records.

### Route and capability matrix

- Enumerate every FastAPI route and test user, unauthenticated, each workload type, allowed/denied method, and capability.
- A workload cannot pass `require_membership`, `require_role`, `require_permission`, or human platform-admin/MFA guards.
- Each workload reaches only its declared machine routes and exact methods.
- Capability names, route registry, OpenAPI/internal annotations, and implementation cannot drift in CI.
- A new unannotated route is workload-denied by default.

### Tenant, project, and RLS isolation

- A single-tenant identity for Tenant A cannot read, mutate, queue, resolve, or report for Tenant B.
- A delegated token cannot change its tenant/project/path/body after minting.
- Missing tenant context returns no protected rows and cannot insert or mutate one.
- Workload runtime roles remain non-owner and `NOBYPASSRLS`.
- Pools, caches, retries, and concurrent jobs cannot reuse Tenant A identity or binding for Tenant B.
- A removed project binding, quarantined tenant, stale data-plane generation, or revoked job fails closed on revalidation.

### Workload integrations

- AI permission and grounding flows accept only the AI audience/capability and current live user/project authorization.
- File-proxy signatures cannot fetch arbitrary URLs, buckets, tenants, or objects.
- Provisioning and deletion identities cannot invoke each other's operations or ordinary user administration.
- A tenant gateway identity cannot address another gateway, Teiid, VPN, or storage boundary.
- Webhook verification can enqueue only the documented constrained event and cannot obtain an internal administrator token.

### Lifecycle and operations

- Disablement/revocation propagates to all API replicas, gateways, workers, token caches, and pools within the approved SLO.
- Owner attestation, expiry, dormant identity disablement, and orphan detection work without revealing credentials.
- A compromised identity can be revoked and replaced without restoring the global service key.
- Audit evidence identifies the actual workload, capability, tenant/project, generation, and decision.

## 10. Deployment sequence

1. Record the current service-key callers, route matrix, environment configuration, and baseline internal traffic.
2. Deploy identity tables, typed principal support, route registry, audit events, and credential/token validation while existing keys remain accepted only through a compatibility adapter.
3. Create narrowly scoped identities and permissions for one canary workload; issue its managed identity/certificate or versioned credential.
4. Migrate the canary to short-lived tokens, exact audience/capability, concrete tenant/project context, and RLS propagation.
5. Run the complete route matrix and observe report-only denials; remove the canary's old key after expected traffic is clean.
6. Migrate AI, schedulers/workers, provisioning, deletion, data-plane/Teiid, file proxy, and webhooks separately.
7. Enable CI/startup default-deny checks and make human dependencies reject workload principals everywhere.
8. Remove `SERVICE_API_KEYS`, shared key deployment variables, `service:*`, synthetic tenant/user zero, and broad test fixtures.
9. Rotate every workload credential once and perform revocation, replay, cross-tenant, dependency-outage, and compromise drills.

Deploy coordinated client/server changes in bounded waves. Do not keep an automatic fallback from a scoped identity to the old global key. A migrated workload is unavailable if its identity is invalid; it must not silently regain platform-admin access.

## 11. Rollback

- Roll back one workload by disabling its new traffic and restoring the immediately previous scoped credential/policy generation only if that generation remains valid and equally constrained.
- Retain identity, permission, credential, and event rows during application rollback so revocation and audit evidence are not lost.
- Never restore `service:*`, synthetic `role=admin`, tenant/user `0`, a shared cross-workload API key, wildcard route grants, or an RLS-bypass database role.
- If token exchange, replay storage, or policy lookup is degraded, stop the affected protected workload and recover the dependency; do not authorize from cached or request-supplied claims beyond their safe validity window.
- A revoked or compromised credential remains revoked through rollback.

## 12. Acceptance criteria

- [ ] Every machine request is attributed to a durable workload identity, credential generation, audience, purpose, and exact capability.
- [ ] No workload principal has a human role, user ID, tenant membership, `service:*`, or implicit platform-admin authority.
- [ ] Human authorization dependencies reject workloads by default, and every machine route/method is present in a reviewed allowlist.
- [ ] Tenant/project service work carries a concrete verified scope and passes through non-owner `NOBYPASSRLS` database enforcement.
- [ ] Cross-tenant, cross-project, wrong-method, wrong-route, wrong-audience, replay, expiry, and revocation tests fail closed.
- [ ] AI, worker, provisioning, deletion, gateway, Teiid/VDB, file-proxy, and webhook identities are separate and purpose-bound.
- [ ] Credentials are short-lived where possible, stored as hashes/references, rotated, independently revoked, and absent from logs and audit payloads.
- [ ] CI inventories the complete workload-accessible route surface and rejects new bypass logic or wildcard grants.
- [ ] The global `SERVICE_API_KEYS` path, synthetic tenant/user zero, `context.is_service` exceptions, and broad service test fixture are removed.
- [ ] Rotation, dependency-failure, compromise, revocation-propagation, and two-tenant production-like drills pass.

TS-ISO-014 must remain open until all broad service keys and synthetic service-administrator paths are removed, every workload has a reviewed least-privilege route matrix, and the cross-tenant/RLS/revocation test suite passes in a production-like environment.

## 13. Validation addendum

All nine current-state findings in Section 2 (`SERVICE_API_KEYS` shape, `X-API-Key` synthesis of `sub=service:<prefix>`, the literal `tenant_id=0/user_id=0/role=admin/permissions=["service:*"]` claim values, `require_membership`'s immediate `is_service` return, the `is_service` bypass in `require_role`/`require_permission`/`require_platform_admin`, inconsistent route-level handling, tenant-0 propagation into RLS, the `service_headers` test fixture, and the AI/platform HMAC envelope's fail-open replay-store leg) were independently re-verified line-by-line against `platform-api/app/auth/middleware.py`, `app/auth/rbac.py`, `app/auth/membership.py`, `app/services/internal_ai_auth.py`, and `tests/conftest.py`, and confirmed **accurate**. One clarification and one important correction:

- **Clarification:** `require_platform_admin`'s `is_service` bypass coexists with `require_human_platform_admin` (`app/auth/rbac.py`), which already explicitly *rejects* `is_service` and wraps the human-only check. Section 5.4's instruction to "retain or rename `require_human_platform_admin` as the explicit human privileged guard" is correct as written — this guard already exists today and is the right foundation to build the default-deny change around, not something to invent from scratch.
- **Correction — the TS-ISO-004 dependency is sound, verify against the current branch tip, not a stale local checkout:** an earlier pass of this validation checked out a stale local `UX-design-03` ref (106 commits behind `origin/UX-design-03`) and incorrectly concluded that `docs/security/ts-iso-004-postgres-rls-design.md` and `platform-api/app/security/rls.py` don't exist. They do exist on the actual current `origin/UX-design-03` tip. More importantly, **TS-ISO-004's own design doc already names the exact gap this plan closes**: its "Intentional blockers before production enforcement" list (item 3) states *"Replace service tenant `0` behavior with a concrete tenant claim or narrow control-plane role"* as a documented prerequisite for broader RLS table enablement, and its authentication/lockout matrix has a row for "Service API key" reading *"No global tenant permitted... Route must bind a concrete canonical tenant or use a separately reviewed control-plane role."* TS-ISO-014 should cite this explicitly in Section 1/3 as the concrete deliverable that unblocks TS-ISO-004's stated blocker #3, and Section 5.5's "Tenant, project, and RLS scoping" design should build directly on the `RlsPrincipal`/`set_config`-based context propagation and the `tablescope_app`/`tablescope_worker` non-owner `NOBYPASSRLS` role split that `app/security/rls.py` and the TS-ISO-004 design doc already define — this plan does not need to invent that role-separation model, only to stop feeding it tenant `0`.

No correction is needed to the `service_headers` fixture description beyond a precision note: the fixture itself (`tests/conftest.py`) is a two-line header dict; the "creates tenants, users, and data" behavior described in Section 2 comes from the 20+ test files that pass it into real route calls, not from the fixture's own code. The underlying concern (test setup normalizes global service-administrator behavior against production routes) is accurate as stated.
