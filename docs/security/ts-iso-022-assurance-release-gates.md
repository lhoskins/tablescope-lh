# TS-ISO-022: Assurance and Release Gates — Standalone Implementation Plan

**Status:** Open — useful component and isolation tests exist; a complete, reproducible, blocking assurance program is required

**Severity:** Medium

**Owner:** Product Security / Platform / SRE / Quality Engineering / Release Engineering

**Target branch:** `UX-design-03`

**Plan branch:** `codex/ts-iso-022-assurance-release-gates`

**Depends on:** TS-ISO-004 through TS-ISO-021 remediation contracts and evidence

**Related findings:** All TableScope isolation findings, especially TS-ISO-012 (data-plane fallback), TS-ISO-014 (service identity), TS-ISO-017 (background jobs), TS-ISO-019 (cloud network), TS-ISO-020 (secrets), and TS-ISO-021 (security audit/alerting)

## 1. Objective

Make tenant, project, identity, storage, AI, job, secret, network, and deletion isolation a release-blocking property rather than a collection of optional or feature-local tests.

Every production artifact must be built once from a reviewed commit, scanned, signed, accompanied by provenance and a software bill of materials, exercised against a deterministic two-tenant/two-project authorization matrix, and promoted by immutable digest only after required checks pass. Pre-release and post-deployment evidence must be reproducible, privacy-safe, retained, and mapped to every open or closed TS-ISO finding. A failed, missing, skipped, flaky, stale, or unevaluable required control blocks release.

## 2. Current-state finding

The repository contains valuable unit, integration, and focused isolation tests, but the workflows do not yet prove the full system boundary:

| Area | Current behavior | Remaining gap |
|---|---|---|
| Platform API workflow | Installs dependencies, checks file length, runs Ruff, mypy, pytest, and builds an unpushed image | Push triggers include `main` and `feature/**`, not `UX-design-03`; path filters can omit cross-component and policy changes |
| Web workflow | Runs frontend lint, type checking, tests, build, and an image build | It is component-scoped and does not prove API authorization, BFF/header behavior, or end-to-end tenant isolation |
| VPN/SMB workflow | Provisions and tests a customer-network simulator using AWS OIDC and uploads evidence | It is manual-only, defaults to an unrelated development ref, serializes all runs, and is not a required release check |
| Isolation tests | Tests cover tenant isolation, project access, Knowledge Graph, AI proxy permissions, RLS context, datasource authorization, data planes, and SMB network isolation | There is no canonical matrix proving all routes, stores, principals, states, and asynchronous paths with the same fixtures |
| Test principals | Many tests use broad service headers or in-process identities | A permissive service credential can mask missing end-user/project checks and does not prove TS-ISO-014 capability scoping |
| Databases | Fast tests commonly use an in-process application/database setup | They do not prove production PostgreSQL RLS policies under each actual runtime role or connection-pool reset behavior |
| Negative testing | Feature tests include selected cross-tenant/project cases | Object-ID substitution, stale membership, revoked sessions, hidden-resource semantics, confused-deputy, replay, and mixed-scope batches are not generated systematically |
| Security scanning | No repository-wide blocking secret, SAST, dependency, IaC, container, or DAST program is defined | Vulnerable dependencies, exposed credentials, unsafe Terraform, and runtime authorization regressions can ship without a common policy decision |
| Supply chain | Images are built during component CI but not signed or promoted by digest | A later deployment can rebuild different bytes; there is no required SBOM, provenance attestation, signature, or admission verification |
| Branch controls | No `CODEOWNERS` or version-controlled branch/ruleset contract is present | Required reviewers, status checks, force-push restrictions, and security ownership cannot be audited from the repository |
| Finding closure | Individual plans list acceptance criteria | There is no machine-readable finding-to-test-to-evidence manifest or automatic check against missing/stale evidence |
| Independent assurance | No penetration-test/retest gate is represented in release metadata | Internal tests alone cannot close externally identified isolation findings or prove adversarial coverage |
| Exceptions | No common waiver schema or expiration check exists | A check can be made optional, bypassed, or left flaky without a visible owner, compensating control, and deadline |

### Root cause

Assurance grew alongside product features. Component workflows optimize for developer feedback and targeted test suites demonstrate important fixes, but no single release policy composes those results into a security claim. Environment-dependent tests, broad service identities, path-filtered workflows, and manual cloud validation leave gaps between what is tested and the artifact that is deployed.

## 3. Scope and non-goals

This plan covers:

- version-controlled release policy, protected branches, ownership, reviews, exceptions, and evidence retention;
- a deterministic authorization/isolation contract across tenants, projects, roles, states, stores, data planes, APIs, UI/BFF, AI, background jobs, and deletion;
- production-like PostgreSQL/RLS, Redis/queue, object/vector/graph stores, gateway/proxy, AI, and customer-network test environments;
- SAST, software-composition, secret, IaC, container, SBOM, provenance, signature, DAST, migration, and configuration checks;
- artifact promotion, pre-deploy, canary, post-deploy, rollback, external penetration testing, and finding closure.

This plan does not declare the application secure because CI is green, replace code review or threat modeling, run destructive tenant tests against customer production data, or permit scanners to upload customer code/data to unapproved services. It defines the minimum evidence required to make and release TableScope isolation claims.

## 4. Assurance invariants

1. `UX-design-03`, release branches, and `main` require the same named security checks; direct and force pushes are prohibited.
2. Every security-relevant change is reviewed by the owning engineering team and the applicable security/data-plane owner from `CODEOWNERS`.
3. Required checks cannot be skipped through path filters when shared authorization, schemas, migrations, infrastructure, deployment, identity, storage, AI, or workflow files change.
4. The isolation contract always creates at least two tenants and two projects per tenant with distinct users, roles, services, jobs, data planes, and resources.
5. Every allow case has a matching deny/hidden case using a different tenant/project/principal, and expected denial never mutates or discloses target data or metadata.
6. Revocation, membership change, session refresh, queued-job execution, retry, and credential/key rotation are tested across time, not only at request creation.
7. PostgreSQL tests execute with production-equivalent runtime roles, grants, RLS policies, connection pooling, transactions, and context cleanup.
8. Object, file, vector, graph, cache, search, audit, and derived stores are tested for reads, writes, listings, counts, exports, deletion, and restore behavior.
9. Required tests are deterministic, containerized or provisioned from versioned IaC, seed their own data, and emit enough evidence to reproduce a failure without exposing sensitive values.
10. A required test that is missing, skipped, quarantined, flaky above threshold, timed out, or unable to provision is a failed gate.
11. Release artifacts are built once, scanned, signed, attested, and promoted by digest; staging and production never rebuild from source.
12. No production deployment accepts an unsigned artifact, unapproved configuration, unapplied migration, unresolved critical/high policy violation, or expired waiver.
13. Each TS-ISO finding maps to executable controls, test IDs, evidence, owner, status, and independent retest where required.
14. Evidence contains no credentials, bearer material, customer content, SQL, prompts, filenames, signed URLs, connector payloads, or private network configuration.
15. Emergency release is a separate audited process with explicit incident authority, compensating controls, automatic expiry, and mandatory retrospective/retest.

## 5. Target assurance architecture

### 5.1 Versioned control manifest

Add `security/assurance/isolation-controls.yaml` as the source of truth. Each control entry must contain:

```yaml
id: ISO-AUTHZ-PROJECT-READ-001
finding_ids: [TS-ISO-003, TS-ISO-016]
boundary: project_metadata
operation: read
principal: tenant_user
allowed_fixture: tenant_a.project_a.member
denied_fixtures:
  - tenant_a.project_b.non_member
  - tenant_b.project_c.member
expected_denial: hidden_not_found
tests:
  - platform-api/tests/security/contracts/test_project_metadata.py
required_tiers: [pull_request, nightly, release]
evidence: junit_case_and_security_event
owner: platform-security
```

Validate the manifest against a JSON Schema. CI fails for duplicate IDs, unknown finding IDs, missing test files, unowned controls, missing deny fixtures, or a control marked closed without passing evidence.

Keep a separate `findings.yaml` entry for TS-ISO-001 through TS-ISO-022 with severity, state, remediation commit, verification test IDs, independent-review reference, accepted residual risk, and closure date. Markdown plans remain human guidance; machine-readable state drives the gate.

### 5.2 Canonical two-tenant/two-project fixture

Build one reusable fixture with randomized opaque IDs:

- tenant A: projects A1 and A2; owner, admin, editor, analyst/member, viewer, removed user, suspended user;
- tenant B: projects B1 and B2 with an equivalent but distinct principal set;
- platform support/admin identities with explicit approval/MFA state;
- narrow service identities for API, worker, AI, connector, deletion, and data-plane operations;
- fresh, expired, revoked, wrong-audience, wrong-tenant, and stale-generation sessions/tokens;
- private/shared/tenant-wide/project-only resources in every supported store;
- isolated, VPN, and explicitly approved shared data-plane modes;
- pending/running/retried/cancelled jobs captured before and after membership or policy revocation.

The harness must make tenant/project IDs deliberately interchangeable in route paths, bodies, query strings, headers, object keys, callbacks, job payloads, and downstream requests. It must verify response status/body shape, row count, observable metadata, mutations, side effects, and TS-ISO-021 event/alert output.

### 5.3 Authorization contract discovery

Generate a checked route inventory from the FastAPI OpenAPI schema plus explicitly registered non-HTTP entry points. Each route declares:

- authentication scheme and permitted principal types;
- tenant and project resolution source;
- required action/capability and MFA/approval requirement;
- hidden-resource versus explicit-forbidden response policy;
- resource and downstream stores touched;
- audit event/control IDs;
- whether background work or external side effects are produced.

Fail CI when a new/changed route, websocket, callback, worker task, CLI, migration utility, signed-URL endpoint, internal AI method, or connector action lacks an assurance declaration. Compare implementation middleware/dependencies to the declaration so documentation alone cannot satisfy the check.

### 5.4 Store and execution matrix

For each control, exercise all relevant layers:

| Boundary | Required checks |
|---|---|
| PostgreSQL | application policy plus RLS under each real runtime role; pooled-connection reset; transaction rollback; maintenance/migration-role denial |
| Object/file storage | prefix/bucket/access-point policy; signed URL scope/TTL; proxy reauthorization; range/list/head; derived preview/export; delete markers and restore |
| Vector/graph/search | namespace/filter enforcement; count/metadata/query/traversal; ingestion; rebuild; cache; deletion and stale-index handling |
| Redis/cache/queue | tenant/project keying; cache hit/miss equality; payload sealing; job claim/retry/dead-letter; revocation at execution |
| AI | authorization callback; context assembly; tool invocation; prompt/response persistence; citations; model gateway; replay and service capability |
| Connector/query | datasource ownership; SQL/query execution; schema/table metadata; credential use; callbacks; exports; timeout/retry |
| Network/data plane | route/DNS/endpoint policy; VPN overlap; S3 boundary; fallback denial; instance metadata; egress; teardown and reprovision |
| UI/BFF | server-side tenant/project derivation; cookie/session handling; forwarded headers; ID substitution; cache-control; browser-visible metadata |

Database migration tests must upgrade from the oldest supported release snapshot, validate policies/grants/indexes, run the isolation matrix, downgrade only where officially supported, and prove a failed migration leaves the prior release recoverable.

### 5.5 Test tiers and required cadence

| Tier | Trigger | Blocking scope | Target |
|---|---|---|---|
| Pull request | Every PR to protected branches | manifest/schema; route drift; unit/contract matrix; RLS integration; lint/types; secret/SAST/SCA/IaC; deterministic component E2E | Fast enough for normal review |
| Merge queue | Candidate merge group | all PR checks on the exact merge commit; image build; SBOM/provenance; container scan; smoke integration | Prevent green-branch/red-merge races |
| Nightly | Default integration branch | full stores, workers, AI, browser/BFF, mutation/fuzz matrix, migrations, deletion, sink failure, backup/restore | Trend flakiness and broad regressions |
| Pre-release | Signed release candidate | production-like isolated and VPN data planes, authenticated DAST, full artifact/config policy, disaster/rotation/revocation drills | Required release approval |
| Post-deploy | Canary then each environment | digest/config verification; synthetic cross-project denials; RLS/data-plane/network/audit health; rollback readiness | Automatic halt/rollback |
| Periodic | At least quarterly and after material boundary change | independent penetration test, restoration exercise, threat-model/control review | Executive/security closure evidence |

Keep expensive cloud tests concurrent per isolated run ID/account/VPC rather than one global environment. Apply hard cost/time limits and unconditional teardown, but a teardown failure remains an alert and blocks new runs that might collide.

### 5.6 Security and supply-chain gates

Implement pinned, maintained tools or approved equivalents for:

- secret scanning of the working tree, generated artifacts, and relevant Git history;
- Python and TypeScript SAST with custom tenant/project trust-boundary rules;
- dependency/SCA and license policy for Python, npm, containers, Terraform providers, and bundled third-party software;
- lockfile/frozen-install enforcement and dependency update automation;
- Terraform formatting, validation, policy-as-code, misconfiguration, IAM, encryption, logging, endpoint, security-group, user-data, and public-access checks;
- Dockerfile/container configuration plus OS/application vulnerability scanning;
- CycloneDX or SPDX SBOM for every deployable image/artifact;
- SLSA-compatible build provenance, keyless or KMS-backed signing, transparency/attestation retention, and admission verification;
- authenticated API/browser DAST with tenant/project ID substitution, mass-assignment, header spoofing, replay, redirect, CORS/CSRF, and signed-URL cases;
- repository/workflow static validation, including action pinning, minimal permissions, untrusted-input handling, OIDC environment controls, and artifact integrity.

Policy must define severity thresholds and an approved upstream-advisory process. A scanner outage, malformed report, missing target, or expired database is not a passing scan.

### 5.7 Build once and promote by digest

The merge-queue commit builds each deployable image/package exactly once in an isolated runner. The pipeline:

1. resolves dependencies only from approved registries and locked versions;
2. builds without production credentials;
3. generates SBOM and provenance bound to commit, workflow, builder, and artifact digest;
4. scans the immutable digest;
5. signs the digest after policy passes;
6. deploys that digest to pre-release;
7. attaches test/evidence attestations to the same digest;
8. promotes the unchanged digest to production after approval;
9. verifies signature, provenance, and approved configuration at admission and after rollout.

Tags are display aliases only. Deployment definitions, rollback records, and environment inventory store digests. If any byte changes, a new candidate and full applicable gates are required.

### 5.8 Branch protection and review policy

Add `CODEOWNERS` for authorization, identity, middleware, RLS/migrations, object/vector/graph/file stores, workers, AI, Terraform/network, secrets, security telemetry, workflows, and assurance manifests.

Configure GitHub rulesets for `UX-design-03`, release branches, and `main`:

- pull request and merge queue required;
- at least one code-owner review and security-owner review for boundary changes;
- dismissal of stale approvals after relevant changes;
- required signed commits where organization policy supports them;
- required linear/current branch state or merge-queue commit;
- named non-optional checks with expected app/source identity;
- no branch deletion, force push, administrator bypass, or self-approval outside the emergency process;
- restricted workflow and policy-file changes;
- environment approval for pre-release and production with separation of duties.

Export or query the live ruleset during release. A repository file describing desired controls is not evidence that GitHub enforces them.

### 5.9 Evidence and release decision

Produce a signed release evidence manifest bound to the artifact digest:

```text
source commit and protected-branch/merge-queue decision
reviewers and required ownership categories
control-manifest and finding-manifest digests
test suite IDs, versions, results, duration, retries, skips, and environment identity
security scan policy versions and normalized findings
migration/schema/RLS/grant fingerprints
SBOM, provenance, image signatures, IaC plan digest, and deployment config digest
pre-release/canary/post-deploy synthetic results
approved unexpired waivers and compensating controls
independent assessment/retest references
```

Store evidence in the TS-ISO-021 security-owned immutable archive with least-privilege access and retention policy. Redact fixtures and logs before upload. Release policy evaluates structured reports, not human-entered green labels.

### 5.10 Waivers, flakes, and emergency release

A waiver requires a unique ID, affected control/artifact/environment, risk statement, severity, owner, security and product approval, compensating control, creation time, hard expiry, and remediation issue. Waivers cannot suppress integrity/provenance failure, known active credential exposure, proven cross-tenant access, or an untested destructive migration.

Retries are recorded. A test becomes quarantinable only after it has first failed the gate, an owner and expiry are assigned, and equivalent blocking coverage exists. Quarantine expiry fails CI. Track flake rate per test and environment; do not convert infrastructure instability into a pass.

Emergency deployment requires an active incident, two-person authorization, immutable event, a previously signed artifact where possible, scoped compensating controls, automatic expiry, and immediate post-deploy synthetics. The full missed suite and retrospective are mandatory within the approved window.

## 6. Implementation phases

### Phase A — Inventory and policy baseline

1. Create the machine-readable finding and isolation-control manifests plus schemas.
2. Inventory all HTTP/non-HTTP entry points, stores, principal types, data-plane modes, deployable artifacts, and existing tests.
3. Map every TS-ISO acceptance criterion to controls and mark missing coverage explicitly.
4. Define severity, failure, evidence, flake, waiver, retention, and independent-assurance policies.
5. Establish baseline workflow/check names before making them required.

**Exit criterion:** every boundary and finding is owned and mapped; absence is visible and machine-detectable.

### Phase B — Deterministic isolation harness

1. Implement the canonical tenant/project/principal/resource fixture as reusable factories.
2. Add generated allow/deny/hidden/revoked/replayed test cases from the route and control manifests.
3. Run PostgreSQL with production-equivalent roles, grants, RLS, pooling, and migrations.
4. Add containerized Redis/queue, AI, object/file, vector, graph/search, connector, and proxy adapters with production authorization paths.
5. Replace broad service headers in assurance cases with TS-ISO-014 scoped workload credentials.
6. Verify TS-ISO-021 events and alerts alongside application results.

**Exit criterion:** the full local/integration matrix is reproducible from one documented command and detects seeded isolation mutations.

### Phase C — CI and security gates

1. Remove unsafe branch/path omissions and include `UX-design-03` and merge groups.
2. Split fast PR checks from parallel integration suites while keeping one stable required summary check.
3. Add secret, SAST, SCA/license, IaC, workflow, container, SBOM, provenance, and signature policies.
4. Add authenticated DAST and mutation tests using the canonical personas.
5. Publish signed, normalized reports and an aggregate policy decision.
6. Add drift checks for OpenAPI routes, migrations, RLS/grants, IAM, security groups, data-plane configuration, and finding coverage.

**Exit criterion:** a seeded vulnerability, missing report, new unclassified route, skipped isolation test, or unsigned artifact prevents merge/promotion.

### Phase D — Production-like release validation

1. Provision ephemeral isolated and VPN data-plane environments from the candidate IaC.
2. Run network, S3, connector/file proxy, AI, job, deletion, audit/alert, rotation, revocation, and restore exercises.
3. Convert VPN/SMB validation from an unrelated manual ref to candidate-bound reusable workflows with automatic release invocation.
4. Validate migration from the supported previous release with realistic scale and rollback checkpoints.
5. Run canary and post-deploy cross-project synthetic denials using dedicated non-customer fixtures.

**Exit criterion:** the exact signed release digest and deployment configuration pass pre-release and post-deploy gates with complete retained evidence.

### Phase E — Enforcement and independent closure

1. Apply and export live GitHub rulesets, CODEOWNERS, environments, and separation-of-duty approvals.
2. Require the stable aggregate gate on all protected branches.
3. Commission an independent penetration test of tenant/project, workload, AI, storage, job, data-plane, and administrative boundaries.
4. Convert every valid result into a tracked finding and rerun the same or stronger independent retest after remediation.
5. Schedule quarterly assurance review, recovery drill, rule tuning, dependency refresh, and evidence-access review.

**Exit criterion:** no TS-ISO finding closes on implementation alone; required internal evidence and applicable independent retest are present and verified.

## 7. Expected repository changes

Paths are illustrative; keep modules small and reuse existing test utilities where appropriate.

```text
.github/
  CODEOWNERS
  dependabot.yml
  workflows/
    assurance-pr.yml
    assurance-nightly.yml
    assurance-release.yml
    assurance-post-deploy.yml
    reusable-isolation.yml
    reusable-security-scan.yml
    vpn-smb-e2e.yml
security/assurance/
  isolation-controls.yaml
  isolation-controls.schema.json
  findings.yaml
  findings.schema.json
  release-policy.yaml
  waiver.schema.json
  tools/
    validate_controls.py
    discover_entrypoints.py
    evaluate_release.py
platform-api/tests/security/contracts/
  conftest.py
  test_route_inventory.py
  test_authorization_matrix.py
  test_store_isolation.py
  test_job_and_revocation.py
  test_audit_contract.py
platform-api/tests/integration/
  test_production_rls_matrix.py
  test_migration_isolation.py
  test_cross_store_deletion.py
scripts/assurance/
  run-local.sh
  build-evidence-manifest.py
  verify-artifact.sh
  verify-live-ruleset.py
docs/security/
  assurance-runbook.md
  emergency-release-runbook.md
  independent-assessment-scope.md
```

Do not combine every check into one opaque script. Each job must publish a structured report, and the final policy evaluator must enumerate every required input and explain a denial without leaking test secrets.

## 8. Required test cases

### 8.1 Contract completeness

- every OpenAPI route and registered non-HTTP entry point maps to an owner and control IDs;
- adding an unclassified route/task/callback causes the gate to fail;
- each allow fixture has cross-project, cross-tenant, revoked, and wrong-principal negative cases;
- expected hidden/forbidden semantics match without existence, count, timing, or metadata leakage;
- every denial and approved override produces the required TS-ISO-021 event.

### 8.2 Identity and temporal authorization

- owner/admin/editor/viewer permissions match the declared matrix;
- tenant role never implies unrelated project membership;
- suspended/removed users, revoked sessions, stale MFA, wrong audiences, and old generations fail;
- service/workload identities can perform only named capabilities for the bound tenant/project/resource/job;
- jobs authorized at enqueue are reauthorized at execution and before side effects;
- retries, dead-letter replay, callbacks, exports, signed URLs, and AI tools preserve the same boundary.

### 8.3 Store and data lifecycle

- cross-tenant/project read/write/list/count/search/traverse/export/delete/restore fails in every store;
- RLS protects raw SQL and bypass attempts for every runtime role and pooled connection;
- object keys, vector filters, graph traversals, cache keys, search indexes, and file proxy paths cannot omit scope;
- deletion is idempotent, removes derived data, records tombstones/evidence, and prevents resurrection;
- backup/restore and rebuild do not reintroduce deleted or foreign-tenant data;
- isolated/VPN S3 locations remain tenant-data-plane-specific and fallback is denied.

### 8.4 Pipeline policy

- known test secrets and real secret patterns are distinguished safely; a seeded credential fails the gate;
- seeded SAST, dependency, Terraform/IAM, container, and workflow defects fail the expected policy;
- missing/truncated/malformed/expired scanner reports fail closed;
- SBOM/provenance/signature bind to the deployed digest and fail after tampering;
- a tag pointing to a different digest is rejected;
- an expired waiver, skipped test, unowned flake, or missing independent retest blocks release.

### 8.5 Production-like and operational failure

- an ephemeral environment can be reproduced from a commit and destroyed without shared-state collision;
- VPN route/DNS/security-group/S3 probes prove customer network and storage boundaries;
- audit sink, secret provider, replay store, queue, vector/graph store, and data-plane failures do not weaken authorization;
- canary synthetics detect a deliberately seeded policy/network/RLS regression and halt rollout;
- rollback restores the prior signed digest and compatible schema without bypassing gates;
- evidence access, retention lock, redaction, integrity, and reconstruction exercises pass.

## 9. Deployment and rollout

1. Land manifests and non-blocking workflows; record two weeks of runtime, flake, and scanner baselines.
2. Fix false negatives, missing route/store coverage, and unstable environments; do not lower denial expectations to obtain green results.
3. Make the aggregate PR/merge-queue assurance decision required on `UX-design-03` first.
4. Enable release candidate build-once/sign/promote and production-like data-plane tests.
5. Apply equivalent rules to release branches and `main`, verify them through the GitHub API, and restrict policy/workflow ownership.
6. Enable admission and post-deploy digest/config/synthetic verification in report-only mode, then enforce.
7. Complete independent assessment and retest before closing applicable isolation findings.

Roll out controls in observable stages, but never describe report-only validation as an enforced release gate.

## 10. Rollback and failure policy

- Workflow/config rollback uses a reviewed prior version and must not remove the last enforced aggregate gate.
- If the gate evaluator is defective, releases pause until a reviewed hotfix or formal emergency process restores a trustworthy decision.
- If an integration environment is unavailable, preserve artifacts/logs, alert the owner, and fail the applicable gate; do not synthesize a pass.
- If a scanner database/service is unavailable or stale beyond policy, block new releases or use a previously approved, still-current offline mirror.
- If post-deploy isolation synthetics fail, halt rollout, revoke exposed sessions/workloads if indicated, restore the prior signed digest, preserve evidence, and open an incident.
- A rollback artifact must already be signed, attested, vulnerability-policy compliant for the emergency policy, and schema-compatible.

## 11. Acceptance criteria

- [ ] `UX-design-03`, release branches, and `main` enforce reviewed pull requests, code owners, merge-queue/current-commit validation, and stable required assurance checks.
- [ ] Every HTTP and non-HTTP entry point, principal, store, data-plane mode, and TS-ISO finding is represented in validated machine-readable control/finding manifests.
- [ ] A deterministic two-tenant/two-project fixture runs allow, cross-project, cross-tenant, revoked, replayed, and wrong-principal cases with narrow service identities.
- [ ] Production-equivalent PostgreSQL roles/RLS/pooling and every object, file, vector, graph, cache, queue, AI, connector, and query boundary pass required isolation tests.
- [ ] PR, nightly, pre-release, and post-deploy tiers fail on missing, skipped, flaky, timed-out, malformed, or stale required evidence.
- [ ] Secret, SAST, dependency/license, IaC, workflow, container, SBOM, provenance, signature, migration, and authenticated DAST policies are blocking at the documented tier.
- [ ] Each artifact is built once and the same signed digest is promoted through pre-release and production with admission and runtime verification.
- [ ] VPN/SMB, isolated/VPN S3, fallback, network, rotation, revocation, deletion, restore, audit/alert, and failure-mode exercises run against the release candidate.
- [ ] Evidence is signed, privacy-safe, immutable, retained, and bound to commit, artifact digest, configuration, environment, control IDs, and finding IDs.
- [ ] Waivers and emergency releases are approved, audited, scoped, compensated, time-bounded, automatically expired, and prohibited for proven cross-tenant exposure.
- [ ] Seeded authorization, RLS, store, job, network, secret, workflow, scanner-report, provenance, and post-deploy mutations are detected and block/halt release.
- [ ] Independent penetration testing covers the complete isolation boundary and independent retest is required before applicable findings close.

TS-ISO-022 must remain open until the protected-branch and deployment systems—not documentation or convention—block release of any artifact lacking complete, reproducible, privacy-safe isolation evidence and applicable independent retest.

## 12. Validation addendum

All thirteen current-state findings in Section 2 were independently re-verified against `.github/workflows/{platform-api,web-ui,vpn-smb-e2e}.yml` (the only three workflow files in the repository), the repo root and `.github/` tree for `CODEOWNERS`/ruleset/`dependabot.yml` files, and the `platform-api/tests/` directory, and confirmed **accurate**. One finding is stronger than stated:

- **Section 2's "No repository-wide blocking secret, SAST, dependency, IaC, container, or DAST program" row understates the gap — even the passive baseline is missing.** There is no `dependabot.yml` anywhere in the repository (root or `.github/`), so there isn't even automated dependency-update PRs today, let alone a blocking SCA gate. Section 6/9's Phase A inventory step should record this explicitly: the starting point is zero automated dependency tracking of any kind, not "informal/non-blocking" tracking.

The Section 2 "Isolation tests" row is well-supported: `platform-api/tests/` contains a broad, on-point set of test files covering every named category — tenant isolation (`test_tenant_isolation.py`, `test_tenants.py`), project access (`test_ts_iso_003_project_access.py`), Knowledge Graph (`test_knowledge_graph*.py`, seven files), AI proxy permissions (`test_ai_proxy_permissions.py`, `test_ai_proxy_shared.py`), RLS context (`test_postgres_rls_context.py`), datasource authorization (`test_query_datasource_authorization.py`), data planes (`test_tenant_data_planes.py`), and SMB/network isolation (`test_smb_tenant_network_isolation.py`, `test_smb_path_security.py`, `test_vpn_smb_repository.py`) — confirming the plan's characterization that useful component-level coverage already exists; the gap is exactly what Section 2 states: no canonical cross-cutting matrix ties them together with shared fixtures.

One caveat on method: live GitHub branch-protection rules, rulesets, and required-status-check configuration are enforced through GitHub's own settings/API, not repository file contents, and could not be verified by reading the repository alone. The absence of a `CODEOWNERS` file and any ruleset-as-code file in the repo is confirmed and accurate, but Section 5.8's instruction to "export or query the live ruleset during release" rather than trust a repository file is exactly right — this validation pass is itself an example of why: it could only confirm what's missing from the repo, not what may or may not be separately configured in GitHub's UI today.
