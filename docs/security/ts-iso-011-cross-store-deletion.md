# TS-ISO-011: Cross-Store Deletion — Standalone Implementation Plan

**Status:** Open — implementation required  
**Severity:** High  
**Owner:** Platform / Data Plane / Security / Operations  
**Target branch:** `UX-design-03`  
**Plan branch:** `codex/ts-iso-011-cross-store-deletion`  
**Depends on:** TS-ISO-005 vector authorization (merged), isolated S3 tenant storage resolution (merged)  
**Related findings:** TS-ISO-004 (Postgres RLS), TS-ISO-012 (isolated S3), TS-ISO-013 (session revocation), TS-ISO-017 (job reauthorization)

## 1. Objective

Replace synchronous and best-effort tenant/project deletion with a durable, idempotent deletion saga that immediately revokes access, purges every required data store, verifies absence, records immutable evidence, respects legal holds and retention policy, and reports completion only when every mandatory store has reached a verified terminal state.

The workflow must cover tenant, project, and isolated data-plane deletion without silently treating external teardown, retained resources, or dependency failures as success.

## 2. Current-state finding

Deletion is implemented as independent cleanup calls rather than an end-to-end security control:

| Area | Current behavior | Security gap |
|---|---|---|
| Project delete | Deletes the Postgres `Project` row and commits | External stores, caches, files, jobs, vectors, VDB objects, and generated artifacts are not orchestrated |
| Tenant delete | Best-effort VDB undeploy, a fixed list of database deletes, best-effort folder removal, then success | Failures can be swallowed and the table list is incomplete/brittle |
| Data-plane delete | Performs partial cleanup and returns a host teardown script | Host/container/network teardown has no durable acknowledgement or final verification |
| S3 | Supports individual object deletion; data-plane delete retains bucket/KMS by default | No prefix inventory, version/delete-marker purge, retention decision, or zero-object verification |
| Qdrant | Has tenant/project delete helpers | Some errors are treated as not-found; platform deletion is not durably wired to them; shared reference vectors also require scoping |
| Redis | Cleanup is distributed across features | No authoritative key registry, bounded scan/delete, or post-delete verification |
| Jobs | File-import jobs are durable but deletion does not coordinate all queued/running/dead-letter work | A worker can recreate data after a delete request or leave payloads/results behind |
| Teiid | Undeploy errors can be logged and skipped | A VDB, view, credential, or network resource can survive a reported deletion |
| Audit | Audit rows can cascade with tenant/project deletion | Evidence that deletion was requested and completed can be erased with the target |

### Root cause

The API treats deletion as a row-level CRUD operation. TableScope now persists tenant data across multiple independently failing stores and external control planes, so deletion must be modeled as a durable distributed workflow with explicit policy and verification.

## 3. Security and correctness invariants

1. A valid deletion request makes the target unavailable before asynchronous purge begins.
2. New work for a deletion-pending tenant/project is rejected by APIs and workers.
3. Each store operation is idempotent and safe to retry after a crash or timeout.
4. A dependency error is distinguishable from an already-absent target and never becomes an implicit success.
5. Completion requires verification for every mandatory store.
6. Policy-authorized retention is an explicit terminal state with policy ID, scope, and expiry—not a hidden pending or skipped step.
7. Legal hold prevents destructive steps while still permitting access revocation/quarantine where policy allows.
8. Evidence survives deletion of the tenant/project and is tamper-evident.
9. Workers and APIs enforce tombstones throughout the workflow so deleted data cannot be recreated.
10. Cross-tenant identifiers are validated before any destructive operation.
11. Postgres cleanup does not rely on an indefinitely maintained handwritten subset of tables.
12. Once a destructive step begins, the target cannot be automatically reactivated.

## 4. Target lifecycle

### 4.1 Phase 1 — Request, quarantine, and revoke

The public request is a short database transaction:

1. Authorize the requester and require a stable idempotency key.
2. Create the deletion job and its required store-step records.
3. Mark the tenant/project/data plane `deletion_pending` and record the job ID.
4. Increment the target's access/membership generation.
5. Revoke or invalidate sessions, credentials, cache generations, and vector access.
6. Mark queued/running jobs as cancellation requested and prevent new jobs.
7. Commit and return `202 Accepted` with the deletion job ID.

All normal data routes, search/vector retrieval, exports, and workers must deny a target in `deletion_pending`, `quarantined`, or later states. This provides immediate isolation even when physical purge takes hours or is delayed by retention policy.

### 4.2 Phase 2 — Durable purge and verification

A background worker leases the job and executes independent, retryable store adapters. Each adapter writes its attempt and evidence before releasing the lease. After all purge steps reach an allowed terminal state, a separate verification pass confirms absence. Only then may the job become `completed`.

Recommended job states:

```text
requested
quarantining
retention_hold
purging
verifying
completed
failed
manual_intervention
cancelled_pre_purge
```

Recommended step states:

```text
pending
blocked_by_hold
running
retry_wait
purged
verified_absent
retained_by_policy
failed
manual_intervention
```

`completed` is legal only when every required step is `verified_absent` or `retained_by_policy` under an applicable recorded policy. `purged`, `not_found`, `skipped`, timeouts, and exhausted retries are not sufficient.

## 5. Durable data model

Add an Alembic migration after the current migration head and ORM models for:

### `deletion_jobs`

- `id` UUID primary key
- `target_type`: `project`, `tenant`, or `tenant_data_plane`
- `tenant_id` and optional `project_id`/`tenant_data_plane_id`
- stable target snapshot containing non-secret immutable identifiers
- `requested_by_user_id` and requester authorization snapshot
- unique `(target_type, target_id, idempotency_key)`
- `status`, `policy_version`, `legal_hold`, `retention_until`
- `access_revoked_at`, `purge_started_at`, `verified_at`, `completed_at`
- `lease_owner`, `lease_expires_at`, optimistic `version`
- safe aggregate error code; no sensitive external payload
- final manifest hash and evidence-chain head
- created/updated timestamps

### `deletion_steps`

- `id`, `deletion_job_id`, `store`, `scope`, `required`
- `status`, `attempt_count`, `max_attempts`, `next_attempt_at`
- `started_at`, `last_attempt_at`, `completed_at`, `verified_at`
- adapter/checkpoint version and resumable cursor/checkpoint
- safe error code and redacted diagnostic reference
- deletion counts/bytes and evidence hash
- policy ID and retention expiry for `retained_by_policy`
- unique `(deletion_job_id, store, scope)`

### `deletion_events`

Use an append-only evidence table or external immutable audit sink that is not owned by a cascading tenant/project foreign key. Include sequence number, previous-event hash, event hash, actor/worker identity, timestamp, action, result, policy version, and redacted evidence payload.

### Target tombstones

Add `deletion_status`, `deletion_job_id`, and `deletion_requested_at` to `Tenant`, `Project`, and `TenantDataPlane`, or use a centralized tombstone table that can be checked efficiently by every request and worker. Hard-delete business rows only after external stores have been purged and verified.

## 6. Store inventory and adapter contracts

Every adapter implements:

```text
plan(job) -> deterministic scoped manifest
quarantine(job, checkpoint) -> result
purge(job, checkpoint) -> result + next checkpoint
verify(job, manifest) -> verified result
```

Adapters must accept only resolved UUIDs/prefixes from the immutable job snapshot, enforce the job tenant/project scope again, support bounded batches, persist cursors, and tolerate already-absent records without hiding connectivity or authorization failures.

### 6.1 Postgres

- Build a registry of every model/table that stores `tenant_id`, `project_id`, source ownership, credentials, generated results, or feature-specific artifacts.
- Add a CI test that introspects SQLAlchemy/Alembic metadata and fails when a tenant/project-bearing table is not classified in the registry.
- Delete child/business rows in a documented dependency order; delete the tenant/project identity row last.
- Use a transaction-scoped, target-restricted database role/function. When TS-ISO-004 RLS is enabled, do not grant a global application `BYPASSRLS` role for purge.
- Preserve deletion jobs/events outside target-owned cascades.
- Verify with table-by-table counts using the same inventory registry.
- Treat foreign-key failures or unclassified residual rows as workflow failures requiring remediation.

### 6.2 S3

- Resolve the exact bucket, region, endpoint, KMS context, and tenant/project prefix through `tenant_storage_resolver`; never accept arbitrary bucket/prefix input from the API request.
- Enumerate current objects, all versions, multipart uploads where applicable, and delete markers under the exact target prefix.
- Delete in bounded batches and persist pagination/version checkpoints.
- Re-list and verify that no target versions, current objects, delete markers, or multipart uploads remain.
- Detect Object Lock, legal hold, retention mode, access denial, and KMS/endpoint errors explicitly.
- For an isolated tenant bucket, record whether policy requires bucket/KMS retention or destruction. Bucket/KMS destruction is a separate approved infrastructure step after object verification; default retention must be represented as `retained_by_policy` with a policy ID.
- Never claim tenant deletion complete merely because a delete marker hides retained versions.

### 6.3 Qdrant and AI artifacts

- Use the TS-ISO-005 authenticated internal vector-store contract and tenant/project authorization.
- For project deletion, remove project vectors from the tenant collection and project-tier reference vectors from any shared reference collection.
- For tenant deletion, delete or deterministically purge the tenant collection and any tenant-owned reference artifacts.
- Add authenticated internal deletion/verification endpoints if direct access cannot preserve service ownership.
- Return separate results for verified absent, unavailable dependency, access denied, and malformed scope. Do not convert exceptions into not-found.
- Verify by scoped count/scroll queries returning zero.
- Include knowledge-graph nodes/edges, extracted text, embeddings, search indexes, and AI-generated intermediate artifacts in the adapter inventory.

### 6.4 Redis

- Define a central registry of all tenant/project key namespaces, including sessions, permission generations, caches, locks, query runs/results, imports, rate-limit state, and feature-specific keys.
- Prefer keyed set indexes per tenant/project for new namespaces. For legacy namespaces, use bounded `SCAN` with exact anchored patterns; never use production `KEYS`.
- Revoke access-generation/session keys during quarantine, then purge all registered keys.
- Delete in bounded batches and verify a second bounded scan returns zero.
- A Redis outage must pause/retry the step, not silently succeed.

### 6.5 Queues, running jobs, and dead letters

- Maintain a durable registry mapping every queued/running job to tenant/project and payload location.
- At quarantine, set cancellation requested and prevent enqueue for tombstoned targets.
- Workers must recheck the tombstone before starting and between irreversible phases; this is the deletion-specific portion of TS-ISO-017 and does not by itself close that finding.
- Remove queued messages, dead-letter payloads, retries, progress keys, temporary uploads, and results after workers acknowledge cancellation.
- Use fencing tokens/generation checks so a late worker cannot publish data after purge.
- Verify no active, queued, retrying, or dead-letter job remains for the target.

### 6.6 Teiid and data-plane resources

- Undeploy project views and tenant VDBs, remove target credentials/data sources, and verify their absence through the Teiid management API.
- Do not catch-and-skip provisioning errors. Record an adapter failure and retry or require manual intervention.
- For data-plane containers, volumes, networks, and host directories, create a signed, expiring teardown action bound to the deletion job and resolved target.
- The operator/agent posts an authenticated completion callback with resource inventory and evidence. The API must not treat generation of a shell script as teardown completion.
- Replace broad `rm -rf` instructions with a helper that resolves and verifies an approved tenant root, refuses symlinks/broad paths, quarantines the directory, deletes it, and reports a manifest hash.

### 6.7 Local files, exports, and generated data

- Inventory tenant/user/project folders, uploaded files, transformed files, exports, previews, cached query results, generated reports, and temporary/spooled content.
- Resolve every target beneath an approved configured root and refuse empty, root, workspace-wide, symlink-escaped, or mismatched tenant paths.
- Prefer an atomic move to a deletion quarantine before recursive removal where the filesystem permits it.
- Verify every manifest entry is absent and quarantine is empty after its recovery window.

### 6.8 Observability, audit, snapshots, and backups

- Export the minimum deletion evidence to a tenant-independent immutable sink before deleting tenant-owned audit rows.
- Classify logs, traces, metrics labels, database snapshots, S3 replication, and backups by retention policy and deletion capability.
- Store policy ID, legal basis, retention expiry, and restoration safeguards for any retained copy.
- Ensure restore procedures reapply deletion tombstones before restored data becomes accessible, preventing deleted tenants/projects from reappearing.
- Schedule post-retention purge and verification as a continuation or child deletion job.

## 7. API and authorization changes

Add privileged endpoints:

```text
POST /api/projects/{project_id}/deletion-jobs
POST /api/tenants/{tenant_id}/deletion-jobs
POST /api/tenant-data-planes/{data_plane_id}/deletion-jobs
GET  /api/deletion-jobs/{job_id}
POST /api/deletion-jobs/{job_id}/retry
POST /api/deletion-jobs/{job_id}/cancel
POST /api/deletion-jobs/{job_id}/legal-hold
DELETE /api/deletion-jobs/{job_id}/legal-hold
```

Requirements:

- Tenant/project deletion requires owner/admin authorization plus the existing high-risk-operation controls; tenant and legal-hold operations require the appropriate root/security-admin role.
- Request bodies must not supply store locations, bucket names, prefixes, collection names, or filesystem paths.
- `cancel` is permitted only before any destructive step has started. It must perform a verified unquarantine/re-enable transaction.
- Retry resumes failed/pending steps; it does not create a second deletion job.
- Status responses expose safe store-level state without secrets or sensitive paths.
- Existing `DELETE` routes become compatibility wrappers that create a job and return `202`; remove synchronous `204` deletion after clients migrate.
- If the orchestrator is unhealthy, reject new destructive requests. Never fall back to the old best-effort deletion path.

## 8. Orchestrator behavior

- Use an existing durable worker framework only if it provides persisted jobs, leases, retries, and crash recovery; do not use an in-process background task.
- Acquire jobs and steps with database leases and optimistic versioning.
- Set exponential backoff with jitter and store-specific retry classification.
- Renew leases during long paginated operations; another worker may safely resume from the committed checkpoint after expiry.
- Require idempotency at the public request, job, step, and external-operation levels.
- Keep the immutable target manifest fixed after purge begins; record separately discovered residuals.
- Use a reconciler to detect stuck leases, incomplete target tombstones, unverified steps, and residual resources.
- A finalizer independently recomputes required steps from the policy/versioned inventory and refuses completion if any required adapter is missing.

## 9. Expected file changes

| Area | Files |
|---|---|
| Models/migration | new `platform-api/app/models/deletion_job.py`, model exports, new Alembic revision, tombstone fields on tenant/project/data-plane models |
| API | new `platform-api/app/routes/deletion_jobs.py`; update `projects_crud.py`, `tenants_crud.py`, `tenant_data_planes_crud.py` |
| Core workflow | new `platform-api/app/services/deletion_orchestrator/core.py`, policy/inventory/finalizer/evidence modules |
| Store adapters | new `postgres.py`, `s3.py`, `qdrant.py`, `redis.py`, `jobs.py`, `teiid.py`, `filesystem.py`, and observability/backup adapter modules |
| Worker | new durable deletion task/worker registration and reconciler schedule |
| Existing deletion | deprecate and then remove direct success paths in `platform-api/app/services/tenant_deletion_service.py` |
| Authorization | tenant/project access guards, session/cache generation, enqueue guards, worker tombstone checks |
| AI server | authenticated internal vector/KG purge and verification endpoints plus TS-ISO-005 enforcement |
| Storage | extend S3 service with scoped version/delete-marker/multipart purge and verification |
| Operations | data-plane teardown agent/callback, retention/legal-hold policy, recovery and evidence runbooks |
| Tests | unit, adapter-contract, integration, failure-injection, restart/retry, and two-tenant isolation suites |

Exact paths and the migration revision must be confirmed against the repository head when implementation starts.

## 10. Implementation phases

### Phase A — Inventory and policy

1. Approve the authoritative store/resource inventory and data retention matrix.
2. Add the Postgres model-classification CI check and Redis/file/job namespace registries.
3. Define legal-hold precedence, cancellation boundary, evidence retention, S3 bucket/KMS policy, and backup handling.
4. Version the deletion policy so every job can be reproduced and audited.

### Phase B — Durable workflow and immediate revocation

1. Add deletion job/step/event tables and target tombstones.
2. Implement authenticated create/status/retry/cancel/hold endpoints.
3. Add the durable worker, leases, checkpoints, finalizer, and reconciler.
4. Make all API authorization, TS-ISO-005 vector access, enqueue paths, and workers deny tombstoned targets.
5. Convert existing DELETE endpoints into job-creation wrappers behind a feature flag.

### Phase C — Store adapters

1. Implement Postgres registry-based deletion and verification.
2. Implement S3 current/version/delete-marker/multipart purge and verification using the resolved tenant boundary.
3. Implement Qdrant, reference-vector, KG, search, and extracted-text purge/verification.
4. Implement Redis namespace purge and queue/job cancellation verification.
5. Implement Teiid/VDB/credential purge and verified data-plane teardown callback.
6. Implement safe local/generated/export cleanup and retained-copy policy steps.

### Phase D — Evidence, operations, and enforcement

1. Add hash-chained immutable evidence and a downloadable security-admin manifest.
2. Add metrics, alerts, stuck-job reconciliation, and manual-intervention runbooks.
3. Run dry-run inventories in a production-like environment and resolve every unclassified resource.
4. Enable the workflow for projects, then tenants, then isolated data planes.
5. Remove the old direct purge service only after all clients use deletion jobs and reconciliation shows no legacy path.

## 11. Test plan

### Workflow tests

- Duplicate requests with the same idempotency key return the same job.
- A target becomes inaccessible immediately after the quarantine transaction.
- No API or worker can create new target data after tombstoning.
- Worker crash before/after each checkpoint resumes without skipping or unsafe duplicate effects.
- Lease expiry, concurrent workers, retryable failures, permanent failures, and manual intervention have deterministic outcomes.
- Completion is rejected while any required step is pending, purged-but-unverified, failed, or missing.
- Cancellation succeeds only before destructive work and safely restores access; it is rejected afterward.
- Legal hold blocks purge, records policy, and does not restore ordinary access.

### Store tests

- Postgres inventory detects every classified row and CI fails for a newly added unclassified tenant/project table.
- S3 deletes and verifies current objects, noncurrent versions, delete markers, and multipart uploads under only the target prefix.
- S3 Object Lock/retention and denied access produce explicit non-success states.
- Project deletion removes tenant-collection vectors and shared project-tier reference vectors without affecting another project.
- Qdrant unavailability is not interpreted as absence.
- Redis deletes only exact target namespaces and verifies zero keys without using `KEYS`.
- Queued, running, retrying, and dead-letter jobs cannot republish after deletion.
- Teiid failure prevents completion; successful undeploy is independently verified.
- Filesystem path traversal, symlink escape, empty target, and broad-root targets are refused.
- Audit evidence remains available after the target business rows are gone.
- Backup restore tests reapply tombstones before traffic and do not resurrect deleted targets.

### Isolation matrix

Create two tenants with two projects each and representative data in every store. Delete one project, then one tenant. Prove:

- all target resources are absent or explicitly retained by policy;
- sibling projects and the other tenant are unchanged;
- cross-tenant IDs, prefixes, collections, and paths are rejected;
- repeated execution remains safe;
- the final evidence manifest matches independently measured counts.

## 12. Deployment sequence

1. Take verified backups and test restore with deletion tombstone replay before enabling destructive adapters.
2. Deploy the schema, API, worker, tombstone guards, and reconciler with job creation disabled.
3. Run inventory-only/dry-run jobs for seeded production-like tenants; compare manifests to independent store queries.
4. Enable project deletion for security-admin canaries; inject a failure into each adapter and verify retry/resume/no-early-completion.
5. Enable tenant deletion canaries, including versioned S3 data, shared reference vectors, jobs, and Teiid resources.
6. Enable isolated data-plane deletion only after the signed teardown acknowledgement and retained-bucket/KMS policy are exercised.
7. Monitor job age, failed steps, residual counts, late worker writes, unclassified resources, and evidence verification.
8. Migrate clients from synchronous DELETE semantics, then remove the legacy direct purge path.

## 13. Rollback and recovery

- Before any destructive step starts, an authorized cancellation can reverse quarantine after verification that no purge occurred.
- After any destructive step starts, rollback is not an automatic reactivation. Keep the target tombstoned and use an approved cross-store restore/reconciliation procedure.
- Disabling the feature flag stops new jobs but must not abandon existing tombstones or leased work; drain or deliberately pause them with visible status.
- Never route around a failed adapter by marking it skipped, and never restore the prior synchronous best-effort delete path.
- Recovery from backup must replay completed deletion manifests/tombstones before the restored environment accepts traffic.

## 14. Acceptance criteria

- [ ] Project, tenant, and data-plane deletion requests return durable job IDs and immediately revoke access.
- [ ] Every required store/resource class has a versioned adapter and independent verifier.
- [ ] Postgres and Redis registries fail CI when a new tenant/project data class is unclassified.
- [ ] S3 versions, delete markers, and multipart uploads are purged or explicitly retained under policy.
- [ ] Tenant/project vectors, shared reference vectors, KG/search/extracted artifacts, and AI intermediates are verified absent.
- [ ] Queued/running/dead-letter jobs cannot recreate deleted data.
- [ ] Teiid and external data-plane teardown require positive acknowledgement and verification.
- [ ] Completion is impossible with pending, failed, missing, or merely best-effort steps.
- [ ] Legal holds and retention decisions are explicit, authorized, expiring, and auditable.
- [ ] Immutable hash-chained evidence survives removal of target-owned rows.
- [ ] Two-tenant/two-project production-like tests prove no collateral deletion and no residual access.
- [ ] Restore tests prove completed deletions are not resurrected.

TS-ISO-011 must remain open until the production-like isolation matrix, failure-injection suite, cross-store verification, and evidence manifest have been reviewed and attached to the finding. Implementing only the database job tables or only the current known stores is not sufficient to close it.

## 15. Validation addendum

All nine current-state findings in Section 2 were independently re-verified line-by-line against `platform-api/app/routes/{projects_crud,tenants_crud,tenant_data_planes_crud}.py`, `app/services/tenant_deletion_service.py`, `app/services/s3_storage.py`, `ai-server/tablescope-ai-api/app/services/vector_store.py`, and the Redis/job-queue call sites, and confirmed **accurate**. One finding (Qdrant) is worse in practice than stated:

- **Qdrant deletion is not merely "not durably wired" — the helpers are entirely dead code.** `delete_tenant_collection` and `delete_project_vectors` exist in `ai-server/.../vector_store.py`, but a repository-wide search finds **zero callers** anywhere in `platform-api` or `ai-server`: no router exposes them, and neither `tenant_deletion_service.py` nor `projects_crud.py`'s delete routes import or invoke them. Additionally, `delete_tenant_collection`'s `except Exception` handler converts *every* failure — not just a genuine not-found — into a logged "not found" outcome, meaning even a future caller of this function would get a false-positive success on a real connectivity or authorization error. Both defects (dead code + broad exception-swallowing) should be named explicitly in Section 6.3 rather than only "some errors are treated as not-found."

Five additional data classes are orphaned by tenant/project deletion today, confirmed with file:line evidence, and should be added to Section 6/9's store inventory — the plan's own Section 6.7 gestures at "generated data" broadly, but these are concrete, named gaps worth calling out individually since each requires a different adapter:

- **Chat-attachment S3 objects.** `ChatAttachment.tenant_id` cascades at the database level, but the actual S3 object is only ever removed by the per-attachment delete flow in `chat_attachment_service.py`. `tenant_deletion_service.py`'s `purge_app_tenant` never touches `chat_attachments` or calls S3 delete for them — every chat attachment ever uploaded by a deleted tenant remains in S3 permanently.
- **Avatar and company-logo S3 copies.** `avatar_storage.py` and `company_logo_storage.py` each best-effort-upload a copy to S3 (`{tenant_id}/{user_id}/avatar/{file_id}`, `{tenant_id}/logo/{file_id}`) alongside the local file `delete_tenant_folders` does clean up. No code path anywhere calls `s3.delete_file` for either key pattern.
- **OAuth connector credentials are deleted locally but never revoked at the identity provider.** `connector_credentials` rows are deleted by `purge_app_tenant`, but no code in `platform-api` calls a token-revocation endpoint for Google Drive or QuickBooks — `google_drive/oauth.py` has token exchange/refresh but no `revoke_token`. The underlying OAuth grant stays live at the provider indefinitely after a "complete" tenant deletion until someone revokes it out-of-band. This is a genuine data-exposure gap (a stale, still-valid OAuth grant against a deleted tenant's former connected account) that Section 6 should add as its own numbered store, not fold into "connector_credentials" as if a DB row delete were sufficient.
- **File-import quarantine directory, and the `file_import_jobs` table itself, are both absent from the deletion path.** `file_import_jobs` is not present in `purge_app_tenant`'s explicit table list at all (confirmed against the current list), and the on-disk quarantine tree (`file_import_quarantine_path/{tenant_id}/{user_id}/{job_id}`, distinct from the `customer_base_path` tree that folder deletion does clean up) is only ever cleared by the per-job cancel route or the unrelated periodic `cleanup_expired_jobs` sweep — never by tenant/project deletion. Section 6.5/6.7 should name this specific path explicitly since it is not covered by either the "jobs" or "local files" adapter as currently scoped.
- **The host-level per-tenant iptables firewall chain is not addressed by the rendered data-plane teardown script.** `tenant_firewall_service.py` generates a per-tenant `iptables` chain, a config file under `/etc/tablescope/tenant-firewall.d`, and a systemd unit — all applied on the host. The teardown script `render_teardown_script` produces (returned by the data-plane delete route, Section 2's "Data-plane delete" row) only runs `docker compose down`, network disconnect/remove, and `rm -rf` of the tenant root; it never references the firewall chain, config file, or systemd unit. A stale per-tenant network-egress-allow rule persists on the host indefinitely after a data plane is "torn down." Section 6.6's teardown-agent design should explicitly include firewall-chain removal in its resource inventory and completion-callback contract.
