# TS-ISO-012: Data-Plane Fallback Completion — Standalone Implementation Plan

**Status:** Open — partial foundations exist; implementation required

**Severity:** High

**Owner:** Platform / Data Plane / Security / Operations

**Target branch:** `UX-design-03`

**Plan branch:** `codex/ts-iso-012-data-plane-fallback-completion`

**Depends on:** Isolated S3 tenant storage resolution (merged)
**Related findings:** TS-ISO-010 (file proxy hardening), TS-ISO-011 (cross-store deletion)

## 1. Objective

Complete the TableScope data-plane isolation boundary by eliminating implicit production fallback to the global Teiid service, requiring an explicit and healthy tenant-to-data-plane binding, replacing multi-homed shared control-plane containers with tenant-scoped execution gateways, and enforcing a distinct service identity and network policy for every isolated tenant.

An isolated tenant whose data plane is missing, unhealthy, unbound, stale, or misconfigured must fail closed. It must never be routed to shared Teiid, shared storage, or another tenant's network as a compatibility measure.

## 2. Current-state finding

The repository contains meaningful isolation work, but two architectural escape paths remain:

| Area | Current behavior | Remaining gap |
|---|---|---|
| S3 resolution | `TenantStorageResolver` fails closed when a bound data plane has incomplete or unvalidated private storage | This is the correct pattern and should be extended to compute/query connectivity |
| Teiid resolution | `TenantTeiidResolver.resolve()` and `resolve_for_org()` return the global Teiid endpoint when the tenant/binding is absent | A missing or incorrect binding silently changes the isolation boundary |
| Binding model | `TenantDataPlane.org_tenant_id` is indexed but not database-unique | Multiple plane rows can ambiguously bind the same organization |
| Readiness | Resolver does not require `status == active`, current health, ready storage, or an active binding generation | Provisioning, failed, or stale infrastructure may be selected |
| Control-plane networking | `tablescope-attach-control-plane.sh` attaches `platform-api` and `platform-api-worker` to every `tenant_*` Docker network | A compromise of either shared container gains a network path to every tenant Teiid/VPN boundary |
| VPN file work | The shared worker selects a source interface from the requested tenant network | Tenant choice is made inside a process that is simultaneously present on multiple tenant networks |
| Service identity | A tenant `teiid_api_key` secret reference is recorded but Teiid clients commonly use the global servlet key | Network reach plus a shared credential weakens tenant attribution and containment |
| PG identity | Several query paths still use common `test/test` Teiid credentials | The credential does not independently prove tenant or workload identity |
| Helper defaults | Query, dashboard, registration, scope, warming, and Google Sheets paths contain `or settings.teiid_*` defaults | A missed argument can silently return execution to global Teiid |
| Host firewall | Generated `DOCKER-USER` rules restrict tenant-originated traffic | They do not remove the shared control-plane's membership in every tenant network or prove request-to-tenant binding |

### Root cause

The initial implementation preserved the single-tenant deployment by treating the shared Teiid endpoint as a fallback and solved reachability by multi-homing shared services. That preserves availability, but it makes a missing binding an implicit authorization decision and expands the blast radius of a shared-service compromise.

## 3. Scope and non-goals

This plan covers:

- explicit shared-versus-isolated tenant policy;
- fail-closed Teiid/data-plane resolution;
- one-to-one active binding and lifecycle generation;
- tenant-scoped workload identity and credential resolution;
- replacement of shared multi-network attachment;
- query, VDB, upload, live-file, repository, and background-job connectivity;
- network and application-layer verification.

This plan does not close TS-ISO-010's file-proxy object authorization or TS-ISO-011's durable decommission workflow. It must integrate with those controls without claiming their closure.

## 4. Isolation invariants

1. Every application tenant has an explicit data-execution policy: `shared` or `isolated_required`.
2. Only a tenant explicitly marked `shared` may use the shared Teiid endpoint.
3. An `isolated_required` tenant must have exactly one active, healthy, generation-matched data-plane binding.
4. A missing, duplicate, provisioning, unhealthy, storage-failed, deleting, or stale binding fails closed.
5. No shared API, web, scheduler, or general worker container is attached to tenant VPN/Docker networks.
6. Tenant network work runs in a tenant-scoped gateway/worker that can reach only that tenant's approved resources.
7. Every call to a tenant gateway and Teiid carries a tenant-bound, purpose-bound workload identity.
8. Endpoints, prefixes, credentials, and network destinations are resolved from trusted binding records, never accepted from a user request.
9. Shared and isolated pools/caches are keyed by tenant, binding generation, endpoint, and credential version; they are never reused across boundaries.
10. Network controls remain default-deny after Docker, host, service, and firewall restarts.
11. Overlapping customer CIDRs cannot cause traffic to leave through the wrong tenant data plane.
12. No compatibility flag may enable production fallback for a tenant marked `isolated_required`.

## 5. Target architecture

### 5.1 Explicit tenant execution policy

Add an authoritative field to `Tenant`, for example:

```text
data_plane_policy ENUM('shared', 'isolated_required') NOT NULL
data_plane_policy_version INTEGER NOT NULL DEFAULT 1
```

Migration rules:

- Tenants already bound to a `TenantDataPlane` become `isolated_required`.
- Known legacy shared tenants become `shared` through an reviewed migration manifest, not a blanket default.
- New production tenants must choose a policy explicitly during provisioning.
- Changing `isolated_required` to `shared` is a high-risk, MFA-protected, audited operation requiring a reason and security-admin approval. It must not occur automatically on failure.

Add a unique constraint on non-null `TenantDataPlane.org_tenant_id`. Add binding lifecycle fields:

```text
binding_generation INTEGER NOT NULL DEFAULT 1
activated_at TIMESTAMPTZ
health_verified_at TIMESTAMPTZ
credentials_version INTEGER NOT NULL DEFAULT 1
network_policy_version INTEGER NOT NULL DEFAULT 1
```

The active binding must be derived from an allowed lifecycle state, not merely the row's existence.

### 5.2 Fail-closed resolver contract

Replace fallback-oriented resolution with a typed binding service:

```text
resolve_execution_binding(org_tenant_id, purpose) -> ExecutionBinding
```

`ExecutionBinding` should contain:

- organization tenant ID and data-plane tenant slug;
- policy and binding generation;
- execution mode (`shared` or `isolated`);
- approved gateway identity and endpoint;
- Teiid logical target, credential reference/version, and TLS identity;
- storage binding identifier;
- health and policy timestamps;
- allowed purpose/capability set.

Resolution behavior:

- Load the active `Tenant` and its policy.
- For `shared`, return the explicitly configured shared binding.
- For `isolated_required`, require exactly one bound data plane with `status == active`, `storage_status == ready`, recent successful health verification, matching policy/generation, and all required secret references.
- Raise a stable `DataPlaneIsolationError` for absent, duplicate, stale, incomplete, or unhealthy bindings.
- Map errors to a safe `503 DATA_PLANE_UNAVAILABLE` or `423 DATA_PLANE_QUARANTINED`, never to shared execution.
- Emit a security event with the tenant, purpose, policy/generation, and redacted reason.

Remove or restrict slug-based `resolve()` from user-serving paths. Numeric application tenant ID from the authenticated context is the authoritative key.

### 5.3 Tenant-scoped execution gateway

Replace the host script that connects shared `platform-api` and `platform-api-worker` containers to every tenant network.

Recommended design:

- Provision one small `tenant-execution-gateway` (and, when required, a tenant-scoped job worker) per isolated data plane.
- The gateway is bound to exactly one tenant/data-plane ID and one binding generation.
- It reaches only its tenant Teiid, approved customer VPN CIDRs, and private S3 endpoint.
- The shared control plane reaches the gateway through a narrow control channel, not the tenant network.
- The gateway exposes purpose-specific operations—query, VDB management, source registration, health, and file acquisition—not an arbitrary TCP or URL proxy.
- Mutual TLS or equivalent workload authentication binds both sides; requests also include tenant, purpose, request ID, timestamp, and generation.
- The gateway rejects a tenant ID or target that differs from its provisioned identity.
- It runs non-root, read-only where practical, without Docker socket, `NET_ADMIN`, IP forwarding, host networking, or privileged mode.
- Network rules prevent forwarding between interfaces and deny gateway access to every other tenant subnet/VPN CIDR.

If tenant-scoped worker processes are used, queue routing must be tenant-bound and signed. The worker must reject a job whose tenant/generation differs from its own identity.

### 5.4 Workload credentials and transport

- Generate unique servlet, PG-wire, gateway, and file/repository workload credentials per isolated tenant.
- Store only managed-secret references in Postgres; resolve secret values at the tenant gateway/runtime boundary.
- Replace common `test/test` credentials on isolated Teiid instances.
- Use mTLS for the control-plane-to-gateway connection and TLS for Teiid where supported. Pin the expected service identity, not only a private IP.
- Include tenant ID, workload purpose, credential version, and binding generation in audit events.
- Rotate credentials without changing tenant policy; permit only a bounded current/next overlap.
- Revoke the old version and evict associated pools immediately after rotation.
- Do not fall back to global `TEIID_SERVLET_API_KEY` when a tenant secret cannot be resolved.

TS-ISO-010 may define stronger request signing for the internal file proxy. Reuse its workload identity and replay-protection primitives instead of inventing a second incompatible scheme.

### 5.5 Network policy

For each isolated data plane:

- Permit control traffic only between the shared control plane and the tenant gateway on the exact gateway port and authenticated protocol.
- Permit gateway/tenant worker traffic only to that tenant's Teiid, approved on-prem CIDRs, DNS/NTP endpoints, and private S3 endpoint as required.
- Deny other tenant Docker subnets, other customer CIDRs, instance metadata, host management ports, Docker socket, control-plane databases, and public internet by default.
- Apply rules before starting/activating the data plane and reapply them after Docker/firewall restart.
- Use explicit source identities/security groups where available, not only CIDRs.
- Validate reverse-path routing and policy routing for overlapping customer CIDRs.
- Record an applied policy hash and compare it during health checks.

Remove `deploy/tablescope-attach-control-plane.sh` and its systemd unit after gateway migration. During transition, an isolated tenant must use either the new path or be unavailable; it must not retain both paths indefinitely.

### 5.6 Call-site completion

Inventory every Teiid and tenant-network caller. The known list includes:

- query and query helpers;
- dashboard widgets, home pins, ITSM metrics, scopes, and AI ask/run;
- VDB creation, deployment, deletion, and warming;
- upload, replace, version, file finalization, and data-source lifecycle;
- SaaS/Google Sheets registration;
- repository/SMB acquisition and background import jobs;
- health, reconciliation, and deletion orchestration.

Refactor these paths to require an `ExecutionBinding` or tenant gateway client. Remove optional `teiid_host`, `teiid_port`, and `servlet_url` defaults from tenant-serving helpers. Constructors such as `VDBManagementService`, `TeiidRegistrationService`, `ScopeProxy`, query helpers, dashboard helpers, and `warm_vdb` must not silently read global Teiid settings in production code paths.

Add a static/CI check that rejects new direct uses of `settings.teiid_pg_host`, `settings.teiid_pg_port`, or `settings.teiid_servlet_url` outside the explicit shared-binding provider, development harness, and approved infrastructure checks.

### 5.7 Pool, cache, and job isolation

- Key connection pools by `(org_tenant_id, binding_generation, endpoint_identity, credential_version, VDB)`.
- Validate those fields again before returning a cached pool.
- Evict all tenant pools on quarantine, health failure, binding change, credential rotation, or deletion.
- Include tenant and generation in background-job payloads and result/cache keys.
- Re-resolve and verify the binding immediately before network execution; do not trust a binding captured when a long-running job was queued.
- Prevent retries from switching from an isolated binding to shared execution.

## 6. Implementation work breakdown

### Phase A — Policy, schema, and resolver

1. Add tenant execution policy, unique organization binding, generation, health-freshness, credential-version, and policy-version fields.
2. Build and review an explicit migration manifest classifying every existing tenant as shared or isolated.
3. Implement `ExecutionBinding`, purpose capabilities, and `DataPlaneIsolationError`.
4. Port `TenantStorageResolver`'s fail-closed pattern into the execution resolver.
5. Add startup validation that forbids an isolated tenant fallback flag in production.

### Phase B — Tenant gateway and identity

1. Add the tenant gateway service/container and narrow operation contract.
2. Provision per-tenant CA/client/server identity or equivalent managed workload credentials.
3. Replace common Teiid servlet and PG credentials for isolated instances.
4. Bind gateway configuration to tenant ID and binding generation; validate on startup and every request.
5. Add request replay protection for destructive/management operations.

### Phase C — Network topology migration

1. Generate default-deny gateway and tenant-network rules before activation.
2. Route a canary tenant's query, VDB, upload, and VPN file work through its gateway.
3. Disconnect the shared API and shared worker from the canary tenant network.
4. Prove the shared containers have no route to tenant Teiid/VPN addresses.
5. Repeat tenant by tenant, then remove the all-network attachment script/unit.

### Phase D — Application call-site enforcement

1. Refactor known resolver call sites to pass authenticated organization tenant ID and purpose.
2. Remove endpoint defaulting from query, dashboard, scope, VDB, warming, upload, and registration helpers.
3. Correct Google Sheets registration and any background tasks that still use global Teiid settings.
4. Partition/evict connection pools and caches by binding generation and credential version.
5. Add CI scanning and a reviewed allowlist for remaining global endpoint references.

### Phase E — Health, operations, and enforcement

1. Make activation conditional on current identity, network-policy hash, Teiid, storage, VDB path, and VPN checks.
2. Quarantine a plane when health freshness expires or the applied network policy differs.
3. Add security events, alerts, and dashboards for resolver denial, route attempts, stale bindings, and cross-tenant packets.
4. Exercise credential rotation, Docker/firewall restart, gateway replacement, and fail-closed rollback runbooks.
5. Remove transition flags after all isolated tenants use the new path.

## 7. Expected file changes

| Area | Files |
|---|---|
| Tenant/binding model | `platform-api/app/models/tenant.py`, `tenant_data_plane.py`, model exports, new Alembic revision |
| Binding resolver | replace/refactor `platform-api/app/services/tenant_teiid_resolver.py`; align `tenant_storage_resolver.py` |
| Gateway client | new tenant execution binding/client/auth modules in `platform-api/app/services/` |
| Provisioning | `tenant_provisioning_service.py`, `tenant_compose_service.py`, tenant layout and schemas/routes |
| Network policy | `tenant_firewall_service.py`, infrastructure templates, security groups, gateway policy artifacts |
| Legacy topology | remove `deploy/tablescope-attach-control-plane.sh` and companion systemd unit after migration |
| Teiid clients | `vdb_management.py`, `teiid_registration_service`, `scope_proxy.py`, `vdb_warming.py`, connection-pool code |
| Serving paths | query, dashboard, AI proxy, home, scope, upload, data-source, SaaS, Google Sheets, and ITSM modules |
| File/VPN jobs | repository/SMB acquisition, tenant job routing, and worker deployment |
| Tests/docs | resolver, topology, credential, packet matrix, operations, provisioning, and rollback documentation |

Paths and the Alembic revision must be confirmed against the repository head when implementation begins.

## 8. Test plan

### Resolver and policy tests

- An explicit shared tenant resolves only the named shared binding.
- An isolated tenant with no plane, no organization binding, duplicate binding, wrong status, failed storage, stale health, missing credential, or generation mismatch fails closed.
- `None`, unknown IDs, slugs, and cross-tenant IDs cannot select a global endpoint from a serving path.
- Downgrading isolated to shared requires the protected approval workflow and creates an audit event.
- No production code path retries an isolated failure against shared Teiid.

### Identity and pool tests

- Tenant A credentials fail against Tenant B's gateway and Teiid.
- Requests with the wrong tenant, purpose, generation, timestamp, or replay ID are rejected.
- Credential rotation evicts old pools and rejects the previous credential after the overlap.
- Cached pools cannot cross tenant, binding generation, credential version, or endpoint identity.
- Errors and logs contain no secret values.

### Network and packet matrix

For two isolated tenants, with overlapping customer CIDRs where feasible, prove:

| Source | Allowed destination | Required denied destinations |
|---|---|---|
| Shared platform API | Tenant gateway control port | Tenant Teiid, VPN CIDRs, other tenant networks |
| Shared general worker | Queue/control services | All tenant Teiid and VPN networks |
| Tenant A gateway/worker | Tenant A Teiid, approved A CIDRs, A private S3 endpoint | Tenant B, metadata, management plane, public internet |
| Tenant B gateway/worker | Tenant B Teiid, approved B CIDRs, B private S3 endpoint | Tenant A, metadata, management plane, public internet |

Repeat after Docker daemon restart, host reboot, firewall reload, gateway replacement, and data-plane scale/reconciliation. Capture connection tests and packet/firewall counters as release evidence.

### End-to-end tests

- Query, dashboard, AI ask/run, upload, file replacement, Google Sheets, VDB lifecycle, warming, and scope paths use the correct isolated gateway.
- A queued job cannot execute after the plane is quarantined or rebound.
- A tenant gateway outage returns a stable unavailable response and never uses shared Teiid.
- S3 and Teiid binding generations agree during VDB creation and file finalization.
- TS-ISO-010 file proxy calls use the same tenant workload identity and cannot traverse through another gateway.

## 9. Deployment sequence

1. Inventory every production tenant, current data-plane binding, endpoint caller, control-plane network attachment, and credential.
2. Deploy schema and policy fields with resolution in report-only mode; explicitly classify every existing tenant.
3. Deploy the gateway, identity, and network policy for one non-production isolated tenant.
4. Run the full packet and application matrix, then disconnect shared API/worker from that tenant network.
5. Canary one production isolated tenant; monitor resolver denials, latency, pool cardinality, job routing, and firewall counters.
6. Migrate remaining isolated tenants individually. Do not mass-enable fallback on a canary failure.
7. Enable strict resolver enforcement and the CI global-endpoint check.
8. Remove the shared all-tenant network attachment script/unit and verify shared containers have no tenant interfaces.
9. Rotate any previously shared Teiid credentials and remove legacy global credentials from isolated instances.
10. Attach packet/connection, restart, credential-rotation, and fail-closed results to TS-ISO-012.

## 10. Rollback

- Roll back a canary by disabling its data access and restoring the previous tenant gateway version; do not reconnect the shared control plane to the tenant network.
- If the resolver or gateway is unhealthy, return `DATA_PLANE_UNAVAILABLE` and preserve the isolated policy.
- Never change `isolated_required` to `shared` as an automatic rollback.
- Keep old credentials only for a bounded rotation overlap, then revoke them.
- If network policy cannot be proven after restart, quarantine the data plane until it is reapplied and verified.

## 11. Acceptance criteria

- [ ] Every tenant is explicitly classified as `shared` or `isolated_required`.
- [ ] `TenantDataPlane.org_tenant_id` is unique when non-null and the active binding is generation/version controlled.
- [ ] An unavailable or invalid isolated binding fails closed in every query, upload, VDB, dashboard, AI, scope, and worker path.
- [ ] Shared API and general worker containers are connected to no tenant Docker/VPN networks.
- [ ] Tenant network operations run only through a tenant-bound gateway/worker with a narrow operation contract.
- [ ] Isolated Teiid instances use per-tenant workload and PG credentials; common/global credentials do not authorize them.
- [ ] Direct global Teiid setting use is restricted by CI to the explicit shared-binding provider and approved test/development code.
- [ ] Pools, caches, and jobs are tenant/generation/credential-version scoped and evicted on binding change.
- [ ] Two-tenant packet tests prove no lateral path, including with overlapping customer CIDRs and after restarts.
- [ ] A gateway or dependency outage never causes shared fallback.
- [ ] Deployment and rollback procedures preserve isolation and have been exercised.

TS-ISO-012 must remain open until every isolated production mode—including container-only and VPN—uses the fail-closed binding/gateway path, the shared control plane has no tenant-network interfaces, and packet-level evidence proves there is no lateral tenant route.

## 13. Validation addendum

All ten current-state findings in Section 2 (S3 resolution, Teiid resolution, binding uniqueness, resolver readiness checks, control-plane networking, VPN file work, service identity, PG identity, helper defaults, host firewall) were independently re-verified line-by-line against `platform-api` and `deploy` on `UX-design-03` and confirmed **accurate**, with one finding understated:

- **`teiid_api_key` is not "commonly" bypassed — it is never used.** `TenantEndpoint.api_key_secret_ref` (`tenant_teiid_resolver.py`) has zero downstream readers anywhere in `app/`. Every Teiid client (`vdb_management.py`, `teiid_registration_service`, `scope_proxy.py`) authenticates with `settings.teiid_servlet_api_key` unconditionally. Phase B's "replace common Teiid servlet credentials" work item has no existing partial implementation for the servlet key to build on.

The following call sites were confirmed during validation and are missing from Section 7's file table; add them:

- **`platform-api/app/services/google_drive/registration.py`** — Google Sheets registration calls `TeiidRegistrationService()` with no arguments and never imports `TenantTeiidResolver` at all. This is not a fallback default (Section 2 wording implies an overridable parameter); there is no tenant-scoping parameter threaded through this path at all.
- **`platform-api/app/services/saas_source_service.py`** — both SaaS-connector registration call sites (`TeiidRegistrationService()`, two locations) are likewise fully unscoped; the file has no `TenantTeiidResolver`/`resolve_for_org` reference.
- **`platform-api/app/services/teiid_registration_service/reconcile.py`** (`reconcile_database_sources`) — the highest-blast-radius call site found: it queries `DatabaseDataSource` across **all tenants** in one pass (no tenant filter unless `only_id` is given) and reuses a single global `TeiidRegistrationService()` instance for the entire batch. Not named in Section 6's phase list or Section 7's file table.
- **`platform-api/app/routes/health.py`** — `VDBManagementService()` instantiated with no tenant/endpoint argument for health checks. Reasonable for a global probe today, but if reused for a future per-tenant health check it would silently probe the global Teiid instead; Section 6E's "health, reconciliation, and deletion orchestration" phase should explicitly account for this call site so it isn't repurposed without a tenant argument later.

These four call sites should be added to the Phase D (call-site completion) inventory and to Section 7's "Serving paths" / "Teiid clients" rows before implementation begins, since they represent unscoped Teiid access the plan's own Section 5.6 inventory (query, dashboard, VDB, upload, SaaS/Google Sheets, repository/background jobs) intends to cover but does not yet name at the function level.
