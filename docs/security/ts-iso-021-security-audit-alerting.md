# TS-ISO-021: Security Audit and Alerting — Standalone Implementation Plan

**Status:** Open — domain audit tables and structured request IDs exist; complete immutable security telemetry is required

**Severity:** Medium

**Owner:** Security / Platform / SRE / Data Plane / AI Governance

**Target branch:** `UX-design-03`

**Plan branch:** `codex/ts-iso-021-security-audit-alerting`

**Depends on:** TS-ISO-014 (service identity scoping), TS-ISO-017 (background-job reauthorization), TS-ISO-020 (secrets hardening)
**Related findings:** TS-ISO-004 (PostgreSQL RLS), TS-ISO-011 (cross-store deletion), TS-ISO-013 (session-token hardening), TS-ISO-016 (asset-metadata visibility), TS-ISO-019 (cloud-network hardening), TS-ISO-022 (assurance release gates)

## 1. Objective

Create one structured, privacy-safe TableScope security event contract and deliver it reliably to an append-only external evidence sink and detection pipeline.

Authentication, authorization, tenant/project reads, query execution, AI context/retrieval, workload/job actions, secrets, data-plane/network changes, administrative overrides, revocation, deletion, and policy changes must be correlated by trustworthy request/job/session identifiers. Cross-tenant/project probes and use after revocation must generate actionable alerts without logging SQL, prompts, filenames, document content, credentials, tokens, customer network details, or other sensitive payloads.

## 2. Current-state finding

TableScope records many business and AI events, but security coverage, consistency, durability, and detection are incomplete:

| Area | Current behavior | Remaining gap |
|---|---|---|
| General audit model | `audit_events` stores tenant/project/user plus titles, queried tables, and document IDs | It is AI/activity-oriented, may contain sensitive metadata, and is not a complete authorization/security event schema |
| Domain logs | AI governance, project context, LLM framework, billing, Knowledge Graph, actions, and reference library each write separate event shapes | Correlation, required fields, reason taxonomy, retention, and security severity differ by subsystem |
| Immutability | Models describe rows as immutable/append-only | Ordinary application tables and cascading foreign keys do not constitute enforced external immutability or WORM retention |
| Tenant deletion | Several audit rows reference tenant/project with `ON DELETE CASCADE` | Deletion can erase the evidence needed to prove authorization and erasure behavior unless exported first |
| Authorization denials | Role/membership/project checks commonly raise `403` directly | There is no central event emitted for every deny, hidden-resource `404`, RLS denial, service/workload mismatch, or revoked principal |
| Read coverage | Project/asset/data-source reads and downloads are not comprehensively audited | Investigators cannot reliably reconstruct access to sensitive tenant/project resources |
| Query execution | Some AI/intelligence activity records queried tables/documents | Raw SQL/query execution, datasource identity, authorization result, row/byte bounds, and cross-project attempts are not captured under one safe contract |
| AI retrieval | AI governance records selected decisions; permission callbacks and graph/vector paths have targeted tests | Viewer, authorized scope, sources/stores consulted, visibility decision, and denial/revocation events are not uniformly correlated |
| Administrative override | Human/root/admin/service exceptions appear in route-specific logic | No mandatory high-severity event proves who used an override, target tenant/project, reason, MFA/approval, and result |
| Request correlation | Middleware creates or accepts `X-Request-ID` and binds request ID | Client-provided IDs are not separated from trusted server correlation; tenant/user binding timing and propagation to jobs/services are incomplete |
| Background work | Worker logs and job results use local identifiers | Request-to-job-to-external-side-effect lineage is not uniformly preserved; TS-ISO-017 must provide it |
| Structured logs | `structlog` emits JSON to stdout | There is no documented external append-only security sink, delivery SLO, integrity proof, or security-owned access boundary |
| Detection | No central rule set/alert routing exists in the repository | Cross-tenant probes, repeated denial, replay, secret access, route-policy drift, and network isolation events may not page or create cases |
| Cloud telemetry | TS-ISO-019 identifies missing flow/DNS/TGW/SSM and posture controls | Application and cloud signals are not correlated by tenant/workload/change identifiers |

### Root cause

Audit logging was implemented feature by feature to support product history and governance views. Those records are valuable, but they were not designed as a security evidence pipeline with a universal schema, enforced immutability, complete deny/read coverage, privacy minimization, delivery guarantees, or detection ownership.

## 3. Scope and non-goals

This plan covers:

- a canonical security event taxonomy and versioned schema;
- centralized emission for requests, policies, reads, queries, AI, jobs, identities, secrets, network/data-plane, overrides, revocation, and deletion;
- transactional delivery, local operational views, external append-only/WORM evidence, integrity, retention, access, and privacy controls;
- detection rules, alert routing, investigation context, tests, dashboards, runbooks, and assurance evidence.

This plan does not record customer content for observability, replace ordinary application/activity history, or expose security telemetry across tenants. It does not claim that logs prevent an attack; application, RLS, network, secret, and job controls remain independently mandatory.

## 4. Security event invariants

1. Every event has a server-generated event ID, schema version, trusted timestamp, source, environment, action, outcome, severity, and safe reason code.
2. Authenticated events identify principal type/ID, tenant, project, session or credential generation, and request/job trace where applicable.
3. Client correlation IDs are validated and stored separately; they never replace the server event/request/trace ID.
4. Authorization allow, deny, hidden-not-found, override, revocation, and policy-change decisions are emitted from central enforcement points.
5. Events contain identifiers and classifications only—never secrets, bearer material, raw SQL, prompts, content, filenames/titles, signed URLs, connector payloads, or customer network secrets.
6. Security events are delivered at least once with idempotent external ingestion and monotonic per-source sequencing.
7. High-risk mutations cannot commit without durable audit acceptance; lower-risk reads use a bounded durable spool during sink outage and alert immediately.
8. The external evidence copy is append-only/WORM, encrypted, access-logged, security-owned, and not deleted by tenant application cascades.
9. Tenant-facing audit views enforce tenant/project/RLS and expose a privacy-minimized subset; platform security access is separately approved and audited.
10. Alert rules are version-controlled, tested against positive and negative fixtures, severity-owned, deduplicated, and linked to a response runbook.
11. Clock, delivery, schema, redaction, sequence, and integrity failures are themselves security events and alerts.
12. Retention, legal hold, tenant deletion, and subject privacy requirements are explicit and cannot silently erase required assurance evidence.

## 5. Target design

### 5.1 Canonical event schema

Create a versioned `SecurityEventV1` contract:

```text
event_id UUID
schema_version
occurred_at / observed_at
source_service / source_instance / environment / region
event_category / event_type / action / outcome / severity / reason_code
server_request_id / trace_id / parent_event_id
job_id / delivery_id / external_request_id
principal_type / principal_id / actor_user_id / workload_identity_id
session_id_hash / credential_id / credential_generation / mfa_level
tenant_id / project_id
resource_type / resource_id_hash-or-safe-id / resource_generation
authorization_policy / policy_version / required_capability
route_template / http_method / response_class
source_ip_prefix_or_keyed_hash / user_agent_class
data_classification / fields_redacted
sequence / integrity_reference
details (strict allowlisted typed fields)
```

Use canonical numeric/UUID identifiers already visible to the authorized platform, but hash or tokenize identifiers whose retention would expose personal/customer metadata. Never place resource names, asset titles, filenames, document IDs presented as content, SQL text, query results, prompts, model responses, network credentials, S3 keys, or URL query strings in `details`.

Maintain a schema registry, compatibility rules, generated validators, and an event catalog with owner, severity, required fields, retention, tenant visibility, and alert mappings.

### 5.2 Trusted correlation

Generate `server_request_id` and trace ID at the outermost middleware before authentication. Accept a valid bounded client `X-Request-ID` only as `client_request_id`; reject/control characters and length abuse. Propagate server IDs through:

- authentication and authorization dependencies;
- database RLS context and query tags where safe;
- outbound AI, connector, Teiid, storage, and infrastructure clients;
- TS-ISO-017 job/outbox/envelope/child jobs;
- TS-ISO-011 deletion manifests and TS-ISO-020 rotations;
- cloud tags/provider request IDs and security events.

After authentication, bind canonical principal/tenant/session/workload fields to the request context. Do not rely on middleware ordering that attempts to read `request.state.context` before authentication has populated it.

### 5.3 Central enforcement instrumentation

Emit security events from shared chokepoints rather than relying on every route author:

- token/session/workload authentication;
- membership, RBAC, MFA/step-up, project access, asset visibility, and capability dependencies;
- TS-ISO-004 RLS scope establishment and database policy errors;
- query authorization/execution service;
- AI permission, vector/lexical/KG context assembly, and visibility filters;
- file proxy, object storage, VDB/Teiid, connector, and data-plane resolvers;
- job claim/checkpoints/cancellation/revocation;
- secret provider/KMS/rotation;
- tenant/project/user/resource lifecycle and administrative override.

Route handlers emit business-specific context only through typed event helpers. Central denial logic uses safe reason codes such as `TENANT_MISMATCH`, `PROJECT_MEMBERSHIP_INACTIVE`, `ASSET_PRIVATE`, `WORKLOAD_CAPABILITY_DENIED`, `SESSION_REVOKED`, `JOB_GENERATION_STALE`, and `RLS_SCOPE_MISSING`. Public responses can remain generic `403`/`404`; event details remain security-restricted.

### 5.4 Required coverage

Capture at minimum:

- login/exchange/SSO/LDAP/MFA success and failure, refresh reuse, logout/revocation, user disable, role/membership changes;
- workload authentication, audience/capability denial, replay, rotation, and use after revocation;
- tenant/project/resource read, download, export, create, update, delete, visibility change, and hidden-resource probe;
- query request/authorization/datasource set/execution outcome using safe query hash and bounded result metrics, never SQL/results;
- AI request/authorized project and source-class counts/vector/lexical/KG decision/model route/output publication, never prompt/content;
- background job request/claim/checkpoint/deny/retry/cancel/side-effect/final state;
- secret/KMS access decision, version stage/use/rotation/revocation, never value/ciphertext;
- data-plane provision/bind/health/quarantine/fallback denial/VPN route/firewall policy/deletion;
- administrative/root/break-glass/tenant switch/override with reason, approval, MFA, target, duration, and result;
- security policy/configuration/schema/migration/release-gate changes.

For routine high-volume reads, record one event per sensitive operation or a rigorously defined aggregation with immutable underlying access evidence. Sampling must never apply to denials, overrides, secrets, credential use, exports/downloads, permission changes, destructive actions, or cross-boundary probes.

### 5.5 Durable delivery

Write the security event and business mutation into a transactional outbox in the same database transaction. An event dispatcher validates/redacts, assigns source sequence, and delivers at least once to the external sink. The sink deduplicates by `event_id`.

For events occurring before a tenant database transaction—invalid authentication, malformed signatures, network/proxy denies—write to a hardened local/managed log transport with disk-backed buffering. Bound memory/disk use and protect against attacker-generated denial storms.

High-risk actions such as administrative override, key rotation/revocation, workload grant, model activation, VPN/data-plane mutation, tenant deletion, and audit-policy change fail closed if a durable audit acknowledgement cannot be obtained within the approved window. Ordinary reads may proceed only under a documented bounded spool policy; spool exhaustion fails safely and pages operations.

### 5.6 External immutable evidence

Use a security-owned AWS account or equivalent boundary:

1. deliver normalized events to CloudWatch Logs/OpenSearch/SIEM for timely detection and investigation;
2. archive canonical batches to an encrypted S3 bucket with versioning, Object Lock compliance/governance mode per policy, retention, legal hold, and restricted deletion;
3. record batch manifest, event count, first/last sequence, object digest, schema version, and signing/integrity metadata.

Use a dedicated KMS key whose administrators cannot also delete/alter evidence without separation of duties. Application roles can publish through a narrow service but cannot read, update, or delete the external archive. CloudTrail logs all evidence access and policy changes.

Add per-source sequence numbers and signed/hash-chained batch manifests to detect gaps or modification. Run scheduled reconciliation between outbox, delivery acknowledgements, hot sink, and WORM archive; alert on gaps, duplicates beyond expected retry, clock skew, or signature failure.

### 5.7 Local audit storage and immutability

Retain domain audit tables for product views where useful, but do not treat them as the authoritative security evidence copy. Consolidate or map them to the canonical event schema.

- give runtime roles insert/select-only access required by the feature;
- revoke update/delete on security event relations;
- use database triggers/policies to reject mutation outside an explicit retention/migration role;
- remove `ON DELETE CASCADE` as the sole lifecycle for required security evidence;
- partition by time/tenant where needed and export before eligible purge;
- audit every privileged retention, legal-hold, or correction operation as a new event.

Corrections append a superseding event; they never rewrite history.

### 5.8 Privacy, tenant visibility, and retention

Define retention by event category and regulatory/customer agreement. Security evidence may outlive application tenant rows, but must retain only pseudonymous IDs and minimal facts needed to prove access/control behavior. Maintain a secure tenant-to-token mapping only for the approved retention/legal purpose.

Tenant administrators may view their tenant's safe audit subset. Project-level viewers receive only events their role and project membership permit. Security operators access cross-tenant telemetry only through MFA/step-up, approved role, case/ticket context, and audited queries. Support exports are redacted and time/tenant scoped.

TS-ISO-011 deletion must export/verify required evidence, sever customer-content references, tokenize identities where policy requires, and then delete application data without deleting the independent evidence archive.

### 5.9 Detection and alerting rules

Implement version-controlled rules for:

- cross-tenant/project/resource ID probing and repeated hidden-resource `404` patterns;
- access after membership, session, workload, credential, tenant, project, or asset revocation;
- RLS missing/mismatch/denial and runtime database role drift;
- service/workload wrong audience/capability/tenant, replay, wildcard grant, or synthetic-admin use;
- forged/stale/replayed background jobs and side effects after cancellation;
- secret/KMS unusual consumer/version/region, decrypt failures, old-key use, rotation failure, or administrative access;
- AI permission mismatch, private metadata/context denial, unexpected source-count changes, or direct vector/graph bypass attempts;
- file-proxy target/signature/replay/size denial and connector/VDB/storage boundary mismatch;
- data-plane fallback attempt, cross-tenant network path, VPN/TGW/security-group drift, public IP/SSH/all-egress/IMDSv1 event;
- administrator override, break-glass, MFA bypass attempt, mass export/delete, and audit configuration change;
- event delivery gap, redaction/schema failure, WORM/KMS policy change, disabled sensor, or clock drift.

Each rule defines severity, threshold/window, suppression/deduplication, enrichment, owner, escalation target, response SLO, runbook, test fixtures, and safe closure criteria. High-confidence boundary violations page; lower-confidence anomalies create triage cases. Alert messages contain safe IDs and console links, not content or secrets.

### 5.10 Dashboards and operations

Security dashboards cover authentication/denials, tenant/project boundary probes, privileged operations, workload/jobs, secrets/rotations, AI retrieval, data-plane/network, event health, and open incidents. Metrics separate expected policy denials from unusual patterns without treating denial volume alone as a breach.

Runbooks include principal/session/workload revocation, tenant quarantine, job cancellation, key rotation, data-plane isolation, evidence preservation, customer notification decision, and recovery verification. Every incident response action emits its own event.

## 6. Implementation work breakdown

### Phase A — Schema, catalog, and correlation

1. Inventory every current audit table, structured log, authorization dependency, sensitive read, external call, and cloud signal.
2. Define `SecurityEventV1`, event/reason catalog, privacy allowlist, retention, tenant visibility, and alert mapping.
3. Implement trusted request/trace IDs and propagation through requests, jobs, AI, storage, connectors, and infrastructure.
4. Add security event/outbox models, typed emitter, redaction/validation, source sequence, and delivery health.
5. Map existing domain audit events to the canonical schema without breaking product history.

### Phase B — Authorization and sensitive-operation coverage

1. Instrument authentication, sessions, membership/RBAC/MFA, project access, asset visibility, workload capability, and RLS chokepoints.
2. Instrument query authorization/execution and sensitive read/download/export paths.
3. Instrument AI permission/context/vector/lexical/KG decisions with source-class counts only.
4. Integrate TS-ISO-017 jobs, TS-ISO-020 secret lifecycle, and TS-ISO-011 deletion.
5. Instrument data-plane/network/admin override/break-glass/policy changes.

### Phase C — External sink and immutability

1. Deploy the security-owned hot sink and KMS-encrypted S3 Object Lock archive.
2. Implement at-least-once delivery, deduplication, signed/hash-chained batches, acknowledgements, and reconciliation.
3. Restrict application roles to publish-only; enforce database insert-only/no-update-delete controls.
4. Define tenant deletion/tokenization and retention/legal-hold workflow.
5. Test sink/spool outage, backpressure, tamper/gap detection, and recovery.

### Phase D — Detection, alerting, and response

1. Implement the cross-boundary, revocation, RLS, workload, job, secret, AI, network, override, and telemetry-health rules.
2. Configure severity routing, deduplication, on-call/case integration, SLOs, and runbooks.
3. Add dashboards and evidence links with tenant/security access controls.
4. Run synthetic attacks and verify alert correlation from request through database/job/cloud events.
5. Tune thresholds without sampling mandatory events or logging additional content.

### Phase E — Enforcement and assurance

1. Require durable audit acknowledgement for high-risk actions.
2. Enable gap/tamper/sensor health release and operational gates.
3. Add schema/redaction/rule fixture tests to TS-ISO-022.
4. Exercise incident, tenant quarantine, compromise, deletion, sink outage, and rollback drills.
5. Produce the independent-review evidence package and remove obsolete duplicate logging paths.

## 7. Expected file changes

| Area | Expected files |
|---|---|
| Event schema/core | new security event schemas, catalog, typed emitter, redaction, correlation, outbox, dispatcher, integrity services |
| Models/migration | new security event/outbox/delivery models, audit-table privilege/trigger changes, new Alembic revision |
| Middleware/auth | request ID middleware, authentication, session, membership, RBAC, MFA, project/asset/workload authorization |
| Data/AI | query service/routes, AI proxy/permissions/context/grounding/vector/KG, downloads/exports, storage/VDB/connectors |
| Jobs/secrets | TS-ISO-017 job events/checkpoints and TS-ISO-020 provider/rotation events |
| Tenant/admin | tenant/project/user lifecycle, data-plane/VPN/firewall, overrides, break-glass, deletion manifests |
| Cloud evidence | Terraform for log streams/delivery, KMS, S3 Object Lock, CloudTrail, flow/DNS/TGW/WAF/SSM integrations |
| Detection | version-controlled rule definitions, routing, dashboards, synthetic probes, runbooks |
| Tests/CI/docs | schema/redaction, coverage matrix, delivery/tamper/outage, alert fixtures, retention, access, deployment and rollback |

Exact sink products, retention periods, alert destinations, account boundaries, file paths, and Alembic revision require security/legal/operations confirmation before implementation.

## 8. Test plan

### Schema, privacy, and correlation

- Validate every event type against required/forbidden fields and schema version.
- Inject secrets, tokens, SQL, prompts, filenames, titles, content, signed URLs, IPs, and connector payloads; verify rejection/redaction before every sink.
- Trace one HTTP request through auth, policy, RLS, AI/query, job, external provider, and response with stable server IDs and parent links.
- Reject malformed/oversized client request IDs and prove they cannot collide with trusted IDs.
- Ensure tenant/user context is bound after authentication and never leaks across concurrent requests/tasks.

### Coverage and detection

- Exercise the full two-tenant/two-project allow/deny matrix and verify correlated events for both permitted and denied outcomes.
- Probe known IDs across tenant/project boundaries, hidden assets, removed members, revoked sessions/workloads, and stale jobs; verify the expected rule alerts.
- Verify query and AI events contain only safe hashes/classifications/counts while still proving authorized sources and outcome.
- Trigger administrative override, key rotation, model/data-plane change, export/delete, and tenant quarantine; verify approval/MFA/reason/result lineage.
- Test rule thresholds, windows, deduplication, suppression, severity, routing, and runbook links with deterministic fixtures.

### Durability and immutability

- Crash between business mutation, outbox write, publish, acknowledgement, and archive; prove no committed high-risk action lacks evidence.
- Replay delivery and verify one logical external event.
- Attempt update/delete through application, migration, tenant admin, and evidence publisher roles; verify denial and alert.
- Delete a tenant/project/user and prove the WORM evidence remains, privacy-tokenized according to policy.
- Modify/drop/reorder batches, block a sink, skew a clock, exhaust spool, or disable a sensor; verify reconciliation and health alerts.
- Restore database/application backups and prove evidence sequence/integrity remains continuous.

### Access and operations

- Tenant administrators see only their safe tenant events; project viewers and ordinary users cannot browse security telemetry beyond policy.
- Security cross-tenant searches require approved role/MFA/case and generate an access event.
- Alert payloads, tickets, notifications, dashboards, and exports contain no raw customer data or secret material.
- Retention expiry, legal hold, evidence export, and authorized purge use separation of duties and append new events.

## 9. Deployment sequence

1. Record all current event producers/tables/logs, sensitive operations, request/job IDs, cloud telemetry, retention, access roles, and baseline event volume.
2. Deploy `SecurityEventV1`, correlation, redaction, outbox, delivery health, and mappings in shadow mode; do not remove domain audits.
3. Deploy the security-owned hot sink and WORM archive, publish canary events, verify KMS/access/retention/integrity, and run outage recovery.
4. Instrument authentication/authorization/RLS denials and high-risk admin/secret/data-plane/job operations first.
5. Add sensitive reads, query execution, AI retrieval/context, downloads/exports, asset visibility, connector/storage/VDB, and lifecycle coverage.
6. Enable detection rules in test/observe mode, run synthetic cross-project/revocation probes, verify routing, and tune safe thresholds.
7. Require durable audit acknowledgement for high-risk mutations and enable event-gap/sensor-health alerts.
8. Enforce database immutability, tenant deletion export/tokenization, retention/legal hold, and restricted tenant/security views.
9. Add TS-ISO-022 blocking coverage/redaction/rule/evidence gates and complete independent security review.

Do not disable an existing audit source until canonical-event parity and external delivery are proven. During sink failure, never preserve a high-risk action by silently dropping its event.

## 10. Rollback

- Retain canonical event/outbox rows, external evidence, sequence, integrity manifests, and detection history through application rollback.
- Re-enable a previous emitter/schema only if the sink accepts it explicitly and required security fields remain present.
- If the hot sink fails, use the tested durable spool/archive path and page operations; pause high-risk actions when acknowledgement policy requires it.
- Never roll back to mutable-only local evidence, uncorrelated client request IDs, content-bearing security logs, disabled deny events, or unaudited overrides.
- A tenant deletion, legal hold, compromised identity, or security incident must not erase evidence during rollback.

## 11. Acceptance criteria

- [ ] A versioned canonical event/reason catalog covers authentication, authorization, RLS, reads, queries, AI, workloads/jobs, secrets, network/data-plane, overrides, revocation, deletion, and policy changes.
- [ ] Trusted request/trace/job/session/workload identifiers correlate actions across API, database, AI, workers, storage/connectors, and cloud telemetry.
- [ ] Central enforcement points emit allow/deny/hidden/override/revocation decisions; route-local omission cannot create a silent gap.
- [ ] Events and alerts contain no secrets, tokens, SQL, prompts, filenames/titles, content, signed URLs, connector payloads, or customer network secrets.
- [ ] Delivery is at least once and idempotent; high-risk mutations require durable acknowledgement and lower-risk outage buffering is bounded/tested.
- [ ] The authoritative external evidence archive is encrypted, append-only/WORM, security-owned, integrity-verified, and independent of tenant deletion cascades.
- [ ] Database audit rows cannot be updated/deleted by runtime roles; corrections append rather than rewrite.
- [ ] Cross-tenant/project probes, revoked access, RLS mismatch, service/job replay, secret misuse, AI visibility denial, network drift, and override events produce tested correlated alerts.
- [ ] Tenant and security audit views enforce least privilege, MFA/approval where required, retention, privacy tokenization, and audited evidence access.
- [ ] Sink outage, spool exhaustion, delivery replay, gap/tamper, clock skew, sensor disablement, incident, deletion, and rollback drills pass.
- [ ] TS-ISO-022 blocks release when required event coverage, redaction, detection fixtures, delivery health, or evidence integrity fails.

TS-ISO-021 must remain open until the complete security-event matrix is emitted from central controls, immutable external evidence and alerting are operational, and cross-project plus revocation probes produce correlated alerts without content leakage.

## 12. Validation addendum

All seven current-state findings in Section 2 were independently re-verified line-by-line against `platform-api/app/models/audit_event.py`, the five other domain audit-event models (`ai_governance_audit.py`, `project_context/audit.py`, `llm_framework.py`, `billing.py`, `analytical_method_catalog.py`), `app/auth/{membership,rbac}.py`, `app/main.py`, and `app/logging_config.py`, and confirmed **accurate**, with one refinement:

- **The `ON DELETE CASCADE` finding is true for a subset of the domain audit shapes, not universally.** `AuditEvent` and `ProjectContextAuditEvent` both cascade on `tenant_id`/`project_id`; `AIGovernanceAuditEvent` cascades on `tenant_id` but its `project_id` is a bare `Integer` with no FK at all; `LLMAuditEvent` and `BillingEvent` have **no tenant_id/project_id columns whatsoever** — cascade behavior doesn't apply to them because they aren't tenant/project-scoped rows in the first place. Section 5.7's "remove `ON DELETE CASCADE` as the sole lifecycle for required security evidence" should be scoped per-model against this actual variance rather than treated as one uniform fix.

**A directly reusable building block already exists and should be cited in Section 5.1/5.3's design rather than building the emitter pattern from zero:** `platform-api/app/services/billing_audit.py` already implements a canonical-event-name-constant plus single `audit(event: str, **fields) -> None` emission function over `structlog`, with an explicit "callers must pass only non-secret fields" discipline in its own docstring. It doesn't solve persistence, tenant/project binding, or alert routing (it's log-only), but its shape — one emit function, a closed vocabulary of event-name constants, structured kwargs — is the closest existing analogue in the codebase to the `SecurityEventV1` typed-emitter pattern Section 5.1 describes, and Phase A's "map existing domain audit events to the canonical schema" work should treat it as a template rather than reinvent the emission API surface. `app/services/ai_confidence_audit.py` and `app/services/kg_evidence_audit.py` follow a related but DB-row-oriented "best-effort audit write must never break the calling action" pattern also worth reviewing during Phase A's inventory step.
