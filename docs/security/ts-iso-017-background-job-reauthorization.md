# TS-ISO-017: Background Job Reauthorization — Standalone Implementation Plan

**Status:** Open — partial record validation exists; a common authorization contract is required

**Severity:** Medium

**Owner:** Platform / Workers / Identity / Data Plane / Security

**Target branch:** `UX-design-03`

**Plan branch:** `codex/ts-iso-017-background-job-reauthorization`

**Depends on:** TS-ISO-004 (PostgreSQL RLS foundation), TS-ISO-014 (service identity scoping)
**Related findings:** TS-ISO-011 (cross-store deletion), TS-ISO-012 (data-plane fallback completion), TS-ISO-013 (session-token hardening), TS-ISO-016 (asset-metadata visibility)

## 1. Objective

Make every TableScope background operation a durable, authenticated, tenant-bound job that is authorized when requested, revalidated when claimed, and reauthorized immediately before each material side effect or publication.

Queue messages must not be treated as authorization. A worker must reload the canonical job, actor/workload, tenant, project, resource, policy generation, and current lifecycle state from trusted stores; prove that every identifier belongs to the same boundary; then execute under the exact tenant/project RLS and workload scope. Forged, stale, replayed, cross-tenant, cancelled, revoked, or superseded jobs must fail closed.

## 2. Current-state finding

The repository contains useful per-task checks, deterministic job IDs, and some canonical record reloads, but there is no shared job identity or reauthorization layer:

| Area | Current behavior | Remaining gap |
|---|---|---|
| Queue transport | `arq` jobs receive ordinary keyword arguments from Redis | The worker trusts the queue payload without a signed/versioned envelope or durable authorization record |
| Worker database context | Most tasks create `SessionLocal()` directly | Worker transactions do not consistently enter the verified TS-ISO-004 tenant/project RLS scope |
| Worker identity | `_worker_context(tenant_id, user_id)` synthesizes a user with `role="admin"` | A queued numeric user ID becomes administrator authority without current membership, role, MFA, session, or workload-policy validation |
| Upload processing | `process_upload` accepts `tenant_id`, `user_id`, absolute `path`, and `is_shared`; it resolves a VDB from the tuple | There is no persisted job/resource generation, path is queue-controlled, and no current user or file authorization is checked before redeploy/index side effects |
| Repository scanning | Queue carries tenant, connection, and scan IDs | Scanner-specific checks exist, but no common proof binds the scan, connection, tenant, requester, credential generation, and current permission at execution |
| Knowledge Graph rebuild | The queue often carries only `build_id` and the worker reloads the build | This is a good foundation, but downstream jobs again pass separate tenant/project/build values and do not uniformly prove they still match or remain authorized |
| KG health checks | Worker accepts only a globally addressable `project_id` | No tenant, actor, job generation, or current project authorization is re-established in the task contract |
| Project reprocessing | Worker accepts tenant/project/user independently and queries by the supplied pair | The user is not reauthorized; per-asset reload checks existence but not that the asset still belongs to the job's canonical tenant/project/generation |
| Insight refresh | Several jobs reload the project and compare tenant; Home analysis also checks project access | These are valuable partial controls, but other refresh paths impersonate an owner/admin or iterate snapshot user IDs without consistent current membership revalidation |
| SaaS sync | Worker accepts a global SaaS source ID and calls `run_sync()` | The source, backing data source, credential, project, tenant, archive state, and requester authorization are not bound through one job policy |
| KPI matching | Worker verifies metric tenant/project but uses the queued requester only for logging | Candidate `SavedQuery` lookup filters project but not tenant explicitly, and the actor/workload is not reauthorized |
| LLM administration | Artifact/deployment/conversion jobs accept record IDs plus `requested_by_user_id` | High-impact model download, installation, activation, reindex, and conversion can outlive the privilege/session that authorized them unless policy is checked again |
| VPN provisioning | Queue carries tenant slug, public gateway IP, CIDRs, and routing mode; worker sends those values to AWS | Infrastructure side effects use mutable queue fields instead of a persisted, approved provisioning request and generation |
| FastAPI background tasks | Asset and reference-document processing run through in-process `BackgroundTasks` with record IDs | They are non-durable and bypass the common queue identity, cancellation, lease, RLS, and reauthorization contract |
| Scheduled jobs | Cron tasks enumerate stale projects or connector credentials and enqueue work | There is no explicit scheduler identity/capability or per-item authorization checkpoint before downstream side effects |

### Root cause

Background functions were built as trusted continuations of an already-authorized HTTP request. Tenant/project/user values were copied into a queue call so the worker could reconstruct context later. That preserves functionality but separates the authorization decision from execution and treats identifiers, rather than a current policy decision, as authority.

## 3. Scope and non-goals

This plan covers:

- durable job identity, state, authorization policy, and lifecycle evidence;
- signed/versioned queue envelopes and replay/tamper detection;
- canonical resource rebinding, current actor/workload checks, RLS propagation, and side-effect checkpoints;
- user-initiated, system-scheduled, event-driven, chained, retrying, and in-process background work;
- cancellation, revocation, supersession, idempotency, leases, failure behavior, monitoring, and tests;
- upload, repository, SaaS, Knowledge Graph, insights, LLM administration, VPN provisioning, and deletion integration.

This plan does not make Redis an authorization database, keep a browser session alive for the life of a job, or grant workers broad administrator authority. TS-ISO-014 defines workload credentials, TS-ISO-011 defines deletion manifests, TS-ISO-012 defines isolated tenant execution gateways, and TS-ISO-016 defines asset visibility; this plan rechecks and carries those decisions through asynchronous execution.

## 4. Authorization invariants

1. Every queued execution maps to exactly one durable job UUID and immutable operation type.
2. The queue envelope authenticates delivery metadata but never replaces live authorization.
3. Tenant, project, user, resource, path, destination, credential, and generation values are derived from canonical records, not trusted because they appear in the message.
4. A worker proves the full parent chain: job to tenant, project, resource, requester/workload, credential, and requested operation.
5. User-initiated jobs require the current account, tenant membership, project membership, role/capability, and resource authorization defined by the operation policy.
6. System jobs run as a named TS-ISO-014 workload identity with one exact capability and concrete tenant/project scope; they never impersonate an owner or synthetic administrator.
7. Protected database work runs as a non-owner, `NOBYPASSRLS` worker role under the verified tenant/project RLS context.
8. Authorization is checked at claim and immediately before every external mutation, destructive action, permission-sensitive publication, or final commit.
9. Long-running jobs recheck at phase/checkpoint boundaries; revocation, membership removal, tenant quarantine, deletion, or policy-generation change stops later side effects.
10. A retry can resume only the same job, operation, resource, tenant/project, policy generation, and idempotency key.
11. Missing, malformed, expired, unsigned, replayed, cancelled, superseded, revoked, mismatched, or unprovable jobs fail closed.
12. Denied jobs expose safe reason codes and identifiers only; queue payloads, logs, traces, and errors contain no secrets or customer data.

## 5. Target design

### 5.1 Durable job model

Add a `background_jobs` model and immutable `background_job_events`. Reuse an existing domain job table, such as `FileImportJob` or `KnowledgeGraphBuild`, as the resource record, but bind it to the common job row.

Recommended `background_jobs` fields:

```text
id UUID PRIMARY KEY
operation VARCHAR NOT NULL
status ENUM(pending, queued, claimed, running, retry_wait, succeeded,
            failed, denied, cancelled, superseded, expired) NOT NULL
tenant_id BIGINT NULL
project_id BIGINT NULL
resource_type VARCHAR NOT NULL
resource_id VARCHAR NOT NULL
resource_generation INTEGER NOT NULL
principal_type ENUM(user, workload) NOT NULL
actor_user_id BIGINT NULL
workload_identity_id UUID NULL
required_capability VARCHAR NOT NULL
authorization_mode VARCHAR NOT NULL
authorization_version INTEGER NOT NULL
tenant_policy_version INTEGER NOT NULL
project_policy_version INTEGER NULL
requested_at / not_before / expires_at TIMESTAMPTZ
claimed_at / heartbeat_at / completed_at TIMESTAMPTZ
attempt INTEGER NOT NULL DEFAULT 0
max_attempts INTEGER NOT NULL
idempotency_key VARCHAR NOT NULL
lease_owner / lease_expires_at
cancelled_at / cancellation_reason
parent_job_id UUID NULL
trace_id VARCHAR NULL
```

Store operation-specific inputs in a typed domain record or validated, encrypted payload reference. Do not place raw file paths, secrets, OAuth tokens, SQL, object contents, customer URLs, VPN pre-shared keys, or unrestricted network destinations in the common job row.

Use unique constraints for operation/idempotency scope and optimistic generation checks. Job events record requested, queued, claimed, authorized, checkpointed, retried, denied, cancelled, superseded, failed, and completed transitions with safe reason codes.

### 5.2 Transactional enqueue and outbox

An authorized request creates the domain change, `background_jobs` row, and outbox event in the same database transaction. A dispatcher publishes only committed outbox rows to Redis and marks delivery using an idempotent event ID.

The enqueue API accepts a typed request such as:

```text
create_job(
  operation,
  canonical_resource,
  authorized_principal,
  required_capability,
  resource_generation,
  idempotency_key,
) -> BackgroundJob
```

It must not accept an arbitrary tenant/project/user tuple from a route. The caller passes a loaded, authorized resource or a service that loads it. The job derives tenant/project/owner and policy versions from that resource and the current authenticated context.

The transactional outbox prevents a worker from running before the authorization/resource record commits and prevents a successful request from losing its job after a Redis outage. Reconciliation republishes undispatched events without creating a second logical job.

### 5.3 Signed queue envelope

Redis should carry a minimal versioned envelope:

```text
envelope_version
job_id
delivery_id
operation
issued_at / expires_at
attempt
nonce
issuer workload identity
audience / queue name
signature / MAC
```

Sign the canonical encoding using TS-ISO-014's queue-producer identity and a versioned key. The consumer validates signature, issuer, audience, clock window, delivery/job ID, operation, and replay state before claiming the database job.

The message normally carries only the `job_id`; mutable operation inputs are loaded from the committed domain record. A valid signature proves that an approved dispatcher sent the envelope, not that the underlying action is still authorized.

Replay registration for a new delivery must be atomic. Duplicate delivery of an already-running or completed idempotent job returns the stored state and performs no second side effect. A replay-store or authorization-store outage fails closed for mutations.

### 5.4 Canonical rebinding

Implement a registry of typed `JobAuthorizationPolicy` handlers. Each policy loads the job and canonical resource graph in one scoped unit of work and verifies:

- job operation, status, expiry, generation, attempt, lease, and cancellation state;
- active tenant and permitted lifecycle state;
- project belongs to that tenant and is active;
- child resource belongs to the canonical project/tenant and matches `resource_type/id/generation`;
- actor belongs to the tenant and has the current project role/capability required by the operation;
- workload identity is active and has the exact tenant/project/operation capability;
- credentials, data-plane binding, asset visibility, or deletion generation required by the operation remain current;
- no supplied or stored ID resolves to a conflicting parent.

Load a globally keyed child by ID only long enough to prove its parent chain; all subsequent queries include canonical tenant/project predicates and RLS. Return a typed `AuthorizedJobContext`, not separate integers:

```text
job_id / operation / attempt
tenant / project / resource
principal (user or workload)
required capability
policy and resource generations
rls principal
idempotency and trace identifiers
```

### 5.5 User and workload authorization modes

Define an explicit mode for each operation:

- `user_current_access`: requester must remain active and retain the current tenant/project/resource permission. Ordinary analysis and reprocessing do not require the browser session to remain open after a normal logout.
- `user_step_up_bound`: destructive, infrastructure, model-deployment, credential, or other high-risk work also requires the authorizing TS-ISO-013 session/step-up assertion to remain valid for the approved execution window. Revocation or compromise cancels execution.
- `workload_current_capability`: scheduled and event-driven tasks use a named TS-ISO-014 identity and exact tenant/project operation capability.
- `deletion_manifest`: TS-ISO-011 jobs require the tenant quarantine and current deletion-manifest generation rather than ordinary interactive membership.

Never select a representative project owner merely to manufacture user authority. If a system refresh is legitimate, authorize the workload for `insights.refresh` under the active tenant/project policy and record the initiating event separately. If the output is user-private, reauthorize each target user and apply their current visibility policy before generating or publishing it.

### 5.6 RLS and worker database identity

Run workers with the dedicated `tablescope_worker` database role described by TS-ISO-004. It must be `NOSUPERUSER NOBYPASSRLS` and own no protected tables.

The initial job lookup uses a narrowly scoped queue-control relation that exposes only the minimum routing/authorization metadata by job ID. After verifying the signed envelope and job row, enter:

```text
rls_scope(
  tenant_id=authorized_job.tenant_id,
  user_id=authorized human actor or 0 for an explicitly typed workload,
  project_id=authorized_job.project_id,
  source="background_job:<operation>",
)
```

The RLS audit context must separately carry the workload principal and optional initiating actor so user `0` is never interpreted as administrator authority. If TS-ISO-014 removes zero-valued user placeholders, use a nullable workload-aware database principal rather than preserving a fake user.

Every new `SessionLocal()` in a worker phase must occur inside or explicitly receive the authorized scope. CI must reject tenant-owned worker queries that open an unscoped session.

### 5.7 Side-effect checkpoints and time-of-check/time-of-use

Wrap material operations in a checkpoint API:

```text
await job_guard.authorize_checkpoint(
  job_id,
  checkpoint="before_vdb_redeploy",
  expected_resource_generation=...,
)
```

Required checkpoints include:

- before reading customer content into memory;
- before AI/vector/Knowledge Graph publication;
- before VDB redeploy, data-source registration, or query execution;
- before object-store write/delete or local-file move/delete;
- before connector API calls or token use;
- before AWS/Terraform/VPN changes;
- before model download, install, conversion, activation, or reindex;
- before sending notifications or publishing user-visible results;
- before final database state transition.

For multi-step external work, persist provider request/idempotency IDs and verify current authorization between phases. If authorization changes after an unavoidable external call, stop follow-on work, quarantine the result, and enqueue an authorized compensating action. Do not label an authorization denial as a retryable operational error.

### 5.8 Job-specific migration requirements

- **File upload/import:** enqueue the persisted `FileImportJob` ID and generation. Resolve the storage object/path from its trusted tenant/user/job record; reject arbitrary absolute paths. Revalidate VDB ownership, asset status, project access/visibility, malware state, and storage binding before redeploy/index.
- **Project assets/reference documents:** replace in-process `BackgroundTasks` with durable jobs. Reload source tenant/project/tier/owner and generation before extraction, AI processing, graph writes, and publication.
- **Repository scans:** bind job to scan, connection, credential version, tenant, approved roots/hosts, and requesting administrator. Reauthorize before network access and each import publication.
- **SaaS/Google/QuickBooks sync:** load source, backing data source, project, tenant, credential, scopes, archive state, and sync generation. Scheduled refresh uses a connector-refresh workload capability, not a copied user ID.
- **Knowledge Graph:** keep the strong build-ID reload pattern, then verify build tenant/project/generation/status and workload/user policy. Downstream jobs enqueue the canonical build/event ID rather than a separate tenant/project tuple.
- **Insights:** replace synthetic admin/owner contexts with workload or current-user policies. Revalidate each snapshot user and TS-ISO-016 asset visibility before private output publication.
- **KPI matching:** bind metric, success criterion, tenant/project, requester/workload, and candidate query. Candidate queries must match tenant and project and remain active.
- **LLM framework:** persist an approved operation record with artifact/target/migration/conversion IDs, approver separation, authorization generation, target environment, and step-up expiry. Reauthorize before download, install, activate, convert, and vector migration.
- **VPN/data-plane provisioning:** persist validated gateway endpoint, CIDRs, routing type, tenant/data-plane binding, approval, and generation in the provisioning record. Enqueue only its ID/generation. The worker must never take network parameters from the queue as authoritative.
- **Deletion:** use the TS-ISO-011 manifest ID, tenant quarantine state, deletion generation, and store-specific idempotency tokens at every phase.

### 5.9 Cancellation, retries, leases, and chaining

- Claim with an atomic state transition and bounded lease; heartbeat long-running work.
- Cancellation/revocation invalidates the lease and is checked at every checkpoint.
- Retry only errors declared retryable by the operation policy. Authorization denial, resource mismatch, deletion, invalid signature, and stale generation are terminal.
- Backoff and maximum attempts are policy-controlled and cannot be increased by a queue payload.
- A retry reloads all canonical records and never reuses an in-memory authorization decision.
- Child jobs are created through the same outbox service with `parent_job_id`; they derive scope from the parent's canonical result and their own operation policy.
- Deterministic job IDs remain useful for coalescing, but the idempotency key includes operation, canonical resource, resource generation, and policy version.
- A superseding job marks the older generation unavailable before new results publish.

### 5.10 Audit and observability

Record job ID, operation, tenant/project, resource type and safe ID, actor/workload identity, required capability, policy/resource generations, attempt, checkpoint, decision, safe reason, duration, and external provider request ID.

Alert on invalid signatures, replay, tenant/project mismatch, synthetic-admin context use, unscoped worker sessions, stale generation, cancelled-job side-effect attempts, repeated authorization denial, unknown operations, and cross-tenant cache/pool use.

Do not log raw paths, filenames, document titles/content, SQL, prompts, connector payloads, OAuth tokens, VPN secrets, public customer endpoints, S3 keys, model credentials, or queue signatures. Current error responses that include `str(exc)` must be mapped to safe codes before user/job-status exposure.

## 6. Implementation work breakdown

### Phase A — Inventory and common model

1. Inventory every `arq`, cron, `BackgroundTasks`, chained task, startup reconciliation, and external side-effect path.
2. Classify each operation by resource graph, principal type, capability, authorization mode, checkpoints, expiry, retries, and idempotency behavior.
3. Add `background_jobs`, events, leases, cancellation, generation, and transactional outbox models/migration.
4. Implement typed job creation so routes pass authorized resources rather than independent tenant/project/user fields.
5. Add the signed envelope schema, key version, issuer/audience registry, and replay controls.

### Phase B — Authorization and RLS core

1. Implement `JobAuthorizationPolicy`, `AuthorizedJobContext`, canonical parent-chain validation, and safe denial codes.
2. Integrate TS-ISO-014 user/workload principal checks and TS-ISO-013 high-risk session/step-up policy.
3. Add worker RLS scope propagation and split the worker database role from migrator/application ownership.
4. Implement claim, heartbeat, checkpoint reauthorization, cancellation, supersession, and finalization services.
5. Add CI checks for unregistered worker functions, direct unscoped `SessionLocal()`, and raw queue argument contracts.

### Phase C — High-risk and boundary migrations

1. Migrate VPN/data-plane provisioning to persisted approved parameters and generation-bound jobs.
2. Migrate file upload/import, repository acquisition, VDB/Teiid, and connector sync before other jobs.
3. Integrate TS-ISO-011 deletion manifests and TS-ISO-012 tenant gateway binding checkpoints.
4. Migrate LLM artifact/deployment/conversion/reindex jobs with step-up and separation-of-duty checks.
5. Verify all external calls use provider idempotency and authorized compensating actions.

### Phase D — AI, graph, insights, and scheduled work

1. Migrate Knowledge Graph builds, health checks, downstream notifications, and source-drift rebuilds.
2. Migrate project reprocessing, AI indexing, vector publication, KPI matching, and reference processing.
3. Replace synthetic worker-admin/representative-owner contexts in Business/Project/Home insights.
4. Give cron/scheduled jobs explicit workload identities and per-item authorization policies.
5. Replace remaining `BackgroundTasks` with durable jobs or document a reviewed non-sensitive exception.

### Phase E — Enforcement and operations

1. Run envelope/policy verification in audit mode while legacy calls continue for a bounded migration window.
2. Enable fail-closed claim/checkpoint enforcement per operation and remove its legacy argument path.
3. Add job inventory, cancellation, denial, retry, replay, stale-generation, and authorization-latency dashboards.
4. Exercise queue compromise, user/workload revocation, Redis/database outage, worker crash, lease expiry, and rollback runbooks.
5. Remove the synthetic `_worker_context`, unsigned payload contracts, and compatibility adapter after all registered functions migrate.

## 7. Expected file changes

| Area | Expected files |
|---|---|
| Models/migration | new background job/event/outbox models, model exports, and a new Alembic revision |
| Job core | new job creation, dispatcher, envelope signing, claim/lease, authorization registry, checkpoint, cancellation, and audit services |
| Identity/RLS | `platform-api/app/auth/context.py`, TS-ISO-014 workload integration, `app/security/rls.py`, worker database/session setup |
| Worker registration | `platform-api/app/tasks/workflows.py`, `kpi_source_matching.py`, `llm_framework.py`, connector refresh tasks, `WorkerSettings` |
| File/document work | `file_ingestion/jobs.py`, staging/finalization, project asset and reference-library processing/routes |
| Data/connector work | repository scanner/routes, SaaS/Google/QuickBooks services, VDB/Teiid clients, data-source lifecycle |
| AI/KG/insights | Knowledge Graph lifecycle, document processing, AI/vector indexing, Home/Business/Project Insight workers and caches |
| Infrastructure/deletion | provisioning route/service, AWS VPN service, TS-ISO-011 manifest workers, TS-ISO-012 gateway client |
| Configuration/deploy | queue signing/rotation settings, separate worker DB identity, Redis ACL/TLS, environment and runbooks |
| Tests/CI | complete job registry matrix, forged/stale payloads, RLS, checkpoint races, retries, revocation, cross-tenant and failure-injection tests |

Exact paths and the Alembic revision must be confirmed against the repository head when implementation begins.

## 8. Job policy registry

Maintain a code-owned registry that maps every worker function to:

```text
operation name
accepted envelope version and queue audience
resource loader and canonical parent chain
principal/authorization mode
required capability
RLS scope rule
resource/policy generations
checkpoint list
expiry and maximum runtime
retryable error classes and maximum attempts
idempotency/compensation handler
result data classification and retention
```

Startup and CI fail when a registered `arq` function lacks a policy, an enqueue helper bypasses the common creation service, a policy refers to a missing function, or a raw task accepts tenant/project/user/network/path fields outside the bounded compatibility adapter.

## 9. Test plan

### Envelope and queue tests

- Reject unsigned, incorrectly signed, wrong-key-version, wrong-issuer, wrong-audience, expired, future-dated, malformed, replayed, and operation-substituted envelopes.
- A valid envelope whose job row is absent, cancelled, completed, expired, or operation-mismatched performs no work.
- Redis write/replay-store/database uncertainty cannot authorize a mutation or create uncontrolled duplicate work.
- Queue ACLs prevent unapproved producers from publishing to worker queues; producer identities cannot consume or alter job state directly.

### Canonical identity and isolation tests

- Independently forge tenant, project, user, resource, path, destination, credential, and generation values and verify fail-closed behavior.
- Use colliding/global IDs across two tenants and prove the full parent chain and RLS prevent cross-tenant reads or writes.
- Missing tenant/project scope returns no protected rows and cannot mutate one.
- Worker, application, and migration database roles have the documented ownership/BYPASSRLS separation.
- A queued user ID cannot become admin; a workload without the exact capability cannot run the job.

### Revocation and time-of-check tests

- Remove project membership, disable the user, revoke/compromise the session where relevant, change the role, quarantine the tenant, archive/delete the resource, revoke the workload, or increment policy generation between enqueue, claim, and side effect.
- Verify routine long jobs do not depend on a browser remaining open but do require current account/membership/resource permission.
- Verify high-risk step-up-bound jobs stop when the approval/session window is revoked or expires.
- Change visibility, ownership, credential, data-plane binding, deletion, or source generation during processing and prove obsolete results cannot publish.

### Job-specific tests

- Upload jobs cannot escape a tenant staging root or redeploy another user's/project's VDB.
- Repository and SaaS jobs cannot use another tenant's connection, credential, host/root, source, or project.
- KG/insight jobs cannot synthesize owner/admin authority or publish private results to an unauthorized user.
- KPI matching cannot select a saved query from another tenant/project.
- LLM jobs cannot change artifact, target, environment, approver, mode, or activation state after approval.
- VPN jobs use only persisted approved CIDRs/gateway/routing settings and current tenant/data-plane generation.
- Deletion retries affect only the quarantined tenant and current manifest generation.

### Retry, idempotency, and failure tests

- Duplicate delivery, worker crash after external success, lease expiry, retry, and dispatcher replay produce one logical side effect.
- Authorization denials are terminal and are not retried into success without a new authorized job/generation.
- Parent/child jobs preserve tenant/resource scope and cannot broaden capabilities.
- Cancellation reaches running jobs at the next checkpoint and blocks final publication.
- Safe job status and logs never expose customer data, paths, secrets, network parameters, SQL, prompts, or provider credentials.

## 10. Deployment sequence

1. Record the current worker function/enqueue inventory, Redis producers/consumers, database roles, RLS state, job traffic, and external side-effect matrix.
2. Deploy job/event/outbox tables, typed policies, signing verification, audit events, and separate worker identity in observation mode.
3. Configure versioned queue signing keys/managed identity, Redis ACL/TLS, dispatcher identity, and the non-owner `NOBYPASSRLS` worker database role.
4. Migrate a low-risk idempotent canary job; verify transactional delivery, canonical rebinding, RLS, cancellation, retry, and denial evidence.
5. Migrate high-risk VPN, file/repository, connector, VDB, LLM, and deletion operations one at a time. Disable each legacy payload path after cutover.
6. Migrate Knowledge Graph, indexing, insight, KPI, reference-document, and scheduled refresh work; remove synthetic admin/owner contexts.
7. Replace remaining in-process `BackgroundTasks` with durable jobs and enable the job-policy registry/CI gate.
8. Remove unsigned queue calls, raw tenant/project/user/path/network arguments, shared worker credentials, and compatibility keys.
9. Run two-tenant forgery, membership removal, workload revocation, stale generation, queue replay, worker crash, external idempotency, dependency outage, and rollback drills.

Do not migrate an operation by allowing both the new job and an automatic fallback to the legacy task indefinitely. After its cutover, an unavailable authorization or queue dependency makes that operation unavailable rather than less constrained.

## 11. Rollback

- Roll back one operation only to its immediately previous signed, scoped policy version while retaining the durable job, generation, cancellation, and audit records.
- Stop or quarantine jobs whose deployed worker does not understand their envelope/policy version; do not reinterpret them as legacy raw arguments.
- Keep revoked, cancelled, superseded, expired, and denied states authoritative through rollback.
- If the dispatcher, signature, RLS context, identity store, or policy lookup is unavailable, pause protected job execution and recover the dependency.
- Never restore unsigned trusted Redis payloads, synthetic admin/owner contexts, arbitrary file/network parameters, shared worker administrator credentials, or RLS-bypass database roles.
- Reconcile ambiguous external side effects using provider idempotency/status before retrying or compensating.

## 12. Acceptance criteria

- [ ] Every worker function is registered with a durable job model, signed envelope, exact capability, canonical resource loader, RLS rule, checkpoints, retry, idempotency, and retention policy.
- [ ] Queue messages are authenticated but never treated as current authorization.
- [ ] Tenant/project/user/resource/credential/path/network scope is rebound from persisted canonical records and mismatches fail closed.
- [ ] User jobs verify current account, membership, role/capability, and resource access; system jobs use named TS-ISO-014 workload identities.
- [ ] No worker manufactures `role=admin`, impersonates a representative owner, or trusts user/tenant zero as authority.
- [ ] All tenant-owned worker transactions use the non-owner `NOBYPASSRLS` role and verified TS-ISO-004 scope.
- [ ] Authorization is rechecked at claim and before every external mutation, destructive action, sensitive publication, and final commit.
- [ ] Revocation, membership removal, tenant quarantine, cancellation, deletion, stale generation, and policy changes stop later side effects.
- [ ] Upload, repository, SaaS, Knowledge Graph, insights, KPI, LLM, VPN, deletion, scheduled, and in-process task paths are migrated.
- [ ] Duplicate delivery, retry, crash, lease expiry, and parent/child chaining remain idempotent and cannot broaden scope.
- [ ] Queue/job logs, traces, status, and errors contain no secrets, customer content, raw paths, network secrets, SQL, or prompts.
- [ ] Forged/stale payload, cross-tenant/global-ID, RLS, revocation-race, dependency-failure, and rollback tests pass in a production-like environment.

TS-ISO-017 must remain open until all background functions use the common policy, legacy raw payload and synthetic-admin paths are removed, worker RLS is enforced, and forged/stale/revoked two-tenant jobs cannot reach any database or external side effect.

## 13. Validation addendum

Independent re-verification against `origin/UX-design-03` (`966abba6`), reading `platform-api/app/tasks/workflows.py`, `app/tasks/llm_framework.py`, `app/database.py`, `app/security/rls.py`, `app/auth/jwt.py`, `app/routes/provisioning.py`, `app/services/repository_scanner/scan.py`, `app/routes/project_assets.py`, `app/routes/reference_library_documents.py`, and `app/routes/reference_library_bulk.py` line-by-line rather than trusting this plan's own prose.

**All 11 current-state claims in Section 2 are ACCURATE.** In particular:

- Claim 1 (plain kwargs, no signed/versioned envelope): confirmed — no `hmac`/`sign`/`envelope`/`nonce` token exists anywhere in the 1674-line `workflows.py`.
- Claim 2 (bare `SessionLocal()`, no `rls_scope`): confirmed across all 20 call sites in `workflows.py`. Notably, `app/database.py:60-79` already defines a `tenant_session` helper that wraps `rls_scope` specifically for this use case — its own docstring calls out "Existing jobs remain an explicit rollout blocker until migrated" — but it has zero callers anywhere in the codebase today (see gap 1 below).
- Claim 3 (`_worker_context` synthesizes `role="admin"`): confirmed verbatim at `workflows.py:1183-1195`, reused at 5 call sites (L771, 934, 1072, 1233, 1323).
- Claims 4–11 (VDB redeploy, repository scan, KG rebuild/health-check, SaaS sync, LLM framework artifact/deploy/reindex, VPN provisioning, in-process `BackgroundTasks`): all confirmed with file:line citations matching the plan's description.

**Five additional gaps found, beyond Section 2's own table:**

1. **The `tenant_session` helper (`app/database.py:60-79`) that already solves claim 2 is unadopted dead code.** It wraps `rls_scope` for exactly the background-worker case this plan targets, but repo-wide search finds no call sites at all. The plan's file-change table (Section 6/9) does not mention `app/database.py` — remediation should either migrate tasks onto this existing helper or explicitly replace it, not design a parallel mechanism from scratch.
2. **`enqueue_scan_repository_connection`/`scan_repository_connection` (`workflows.py:162-212`) carry no requester/user_id field at all** — not merely an unverified one, as with the LLM-framework and upload jobs. `RepositoryScanner.scan()` does cross-check tenant/connection/scan consistency internally, but there is no actor identity anywhere in the call chain to re-authorize. Remediation here means *adding* a requester field to the job payload, not validating one that already exists — a materially different fix shape worth calling out separately in Section 6's plan.
3. **`provision_tenant_vpn` proceeds even when no matching `TenantProvisioningRequest` row exists** (`workflows.py:1574-1607`): the `if req is not None` checks gate only post-provisioning status writes, not the AWS provisioning call itself. The plan's rationale describes reusing a persisted "approved request" record, but today that record isn't actually a precondition for the infrastructure change — the redesign should make the check a hard precondition (raise/return early on a missing/unapproved request), not just describe consulting the record.
4. **`refresh_business_insight_result` and `evaluate_stale_graphs` both re-attribute work to a "representative user"** via `KnowledgeGraphLifecycleManager.resolve_representative_user(project_id)` (`workflows.py:439, 748-749`) rather than the actual requester who triggered the underlying event, before `_worker_context` synthesizes admin credentials for that substituted user. This owner-substitution pattern recurs across at least two task families and changes what "the requester" means for these jobs — the plan's authorization-record design (Section 5) should explicitly state whether the original event actor's or the substituted representative owner's consent/role is what's being captured.
5. **`google_drive_token_refresh.py` and `quickbooks_token_refresh.py`** (present in `app/tasks/`, not listed in Section 7's table) are cron-triggered token-rotation jobs that also call `SessionLocal()` directly and write rotated OAuth secrets with no `rls_scope`. They iterate all due credentials rather than trusting a queue-supplied untrusted ID, so they're lower risk than the queue-driven jobs above — but they share the same RLS-scope gap as claim 2 and touch credential material, so the plan should at least note them as lower-priority instances of the same defect rather than omit them.
