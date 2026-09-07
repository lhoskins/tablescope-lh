# TS-ISO Security Hardening Program — Phased Implementation Roadmap

**Status:** Active — Phase 1 in progress
**Owner:** Platform / Security
**Covers:** TS-ISO-010, 011, 012, 013, 014, 016, 017, 019, 020, 021, 022
**Also references (already implemented, not in scope of this roadmap):** TS-ISO-003 (project access policy), TS-ISO-004 (Postgres RLS foundation), TS-ISO-005 (vector-store authorization)

## Purpose

Eleven security/infrastructure hardening plans have each been independently validated against the real codebase (see each plan's own "Validation addendum" section under `docs/security/`). This document sequences their **actual implementation** into phases ordered by two things:

1. **Dependency order** — several plans explicitly depend on others (e.g. TS-ISO-021 depends on TS-ISO-014/017/020; TS-ISO-022 depends on evidence from all of them). Building a dependency before the plan that assumes it exists avoids rework.
2. **Blast radius** — pure application-code fixes with no infrastructure/production-secret/network dependency go first; multi-week cloud network migrations and org-wide policy/gate enforcement go last, and only after the things they gate on already exist.

No phase after Phase 1 should begin until the phase before it has shipped and been running in production without incident for a reasonable bake-in period. Do not parallelize Phase 3 onward across more than one plan without confirming the shared dependencies (TS-ISO-014 identities, TS-ISO-004 RLS) are actually enabled for the affected tables/services — several of these controls exist in the codebase today but are deliberately **off by default** (see Phase 0).

---

## Phase 0 — Already implemented (foundation, not new work)

These are referenced as dependencies by multiple plans below and are already merged. Phase 1+ work should build on them, not re-implement them.

| Item | State |
|---|---|
| **TS-ISO-003** — per-project access policy (`app/services/project_access.py`) | Merged and enforced on project/knowledge-graph routes. |
| **TS-ISO-004** — Postgres RLS foundation (`app/security/rls.py`, `rls_scope()`, `manage_postgres_rls.py`) | Merged. Policies exist per-table but are **disabled by default** — a table's RLS only takes effect once `manage_postgres_rls enable --apply` has been run for it. **Action for this roadmap: confirm with the DBA/platform owner which tables currently have RLS actually enabled in production** before assuming any plan below gets RLS coverage "for free." Phases 2–4 below call this out per-plan. |
| **TS-ISO-005** — vector-store query authorization (`vector_store.py` `VectorAccessClaims`, live `_verify_permissions()` callback) | Merged and confirmed live on the query path. Does **not** cover deletion (see TS-ISO-011, Phase 4). |

**Do not** treat "RLS is merged" as "RLS is enforced everywhere." Every phase below that assumes RLS protection must first confirm the specific tables it touches are in the enabled set.

---

## Phase 1 — Fast, isolated, zero-infrastructure fixes (this session)

Each item here is a single-purpose, independently testable code change with no Terraform, no KMS/AWS console work, no schema migration, and no cross-team coordination. All five were flagged during validation as safe to pull forward ahead of their parent plan's full multi-phase rollout. **This phase does require a real code deploy** (app restart / nginx reload) — unlike the earlier plan-document merges, this is not "docs only."

| # | Plan | Fix | Why it's isolated |
|---|---|---|---|
| 1.1 | TS-ISO-020 | Add a fail-closed production startup check for `TABLESCOPE_SECRET_KEY`, mirroring the existing check already in place for `TABLESCOPE_AI_SIGNING_SECRET`. | Same pattern already proven in the codebase for a sibling secret; pure config validation, no runtime behavior change for correctly-configured deployments. |
| 1.2 | TS-ISO-022 | Add `.github/dependabot.yml` covering every real package ecosystem in the repo. | Additive CI config; cannot break the running application. |
| 1.3 | TS-ISO-011 | Wire the existing-but-uncalled `delete_tenant_collection`/`delete_project_vectors` into the real tenant/project deletion path, and fix the exception handler that currently converts every failure into a false "not found" success. | Touches one deletion code path; does not change any read/query behavior. |
| 1.4 | TS-ISO-017 | Migrate one low-risk, idempotent worker job (`run_knowledge_graph_health_check`) from a bare `SessionLocal()` to the existing-but-unadopted `tenant_session` helper, as the plan's own deployment sequence recommends starting with "a low-risk idempotent canary job." | Exactly the canary step TS-ISO-017 §10.4 itself calls for; one job, fully reversible. |
| 1.5 | TS-ISO-010 | Fix `X-Forwarded-For` trust in the file-proxy route so only a configured, verified immediate-proxy peer's header is trusted, instead of blindly parsing the first comma-separated value — closing the live pre-auth spoofing bypass identified during validation. | Nginx config + one function; does not touch the rest of TS-ISO-010's workload-identity redesign. |

See §"Phase 1 implementation" below (and the accompanying Devin doc, `docs/devin-ts-iso-phase1-fastfix-merge-deploy.md`) for the actual diffs, tests, and deploy steps.

---

## Phase 2 — Foundational identity and session hardening

**Prerequisite:** Phase 1 deployed and stable.

| Plan | Scope |
|---|---|
| **TS-ISO-014** — Service Identity Scoping | Full plan: named, scoped workload identities for background jobs and inter-service calls, replacing ambient trust. This is a hard dependency for the remainder of TS-ISO-017, all of TS-ISO-019's application-to-AI routing, and TS-ISO-021's event attribution — build it before those. |
| **TS-ISO-013** — Session-Token Hardening | Full plan: session/token lifecycle hardening (rotation, revocation, assurance level). Independent of TS-ISO-014 but touches the same auth-path code, so land both in this phase together rather than interleaving with later phases' route changes. |

**Why this phase is next:** every later phase that talks about "the worker's identity" or "the current session's assurance level" is currently describing something that doesn't exist yet outside Phase 0/1. Building it now means Phases 3+ implement against a real primitive instead of a synthetic admin context or a placeholder.

**Blast radius:** Medium. These changes sit on the authentication/authorization hot path for every request and every worker. Roll out behind a flag or canary tenant, verify login/session/worker-auth flows end-to-end, before flipping default-on.

---

## Phase 3 — Authorization completion

**Prerequisite:** Phase 2's service identities and session model exist and are stable.

| Plan | Scope |
|---|---|
| **TS-ISO-016** — Asset Metadata Visibility | Full plan: close the remaining metadata-visibility gaps beyond what TS-ISO-003 already covers. |
| **TS-ISO-017** — Background Job Reauthorization | Full plan, beyond the Phase 1 canary: migrate the remaining ~19 `SessionLocal()` call sites onto `tenant_session`/RLS, replace `_worker_context`'s synthetic `role="admin"` with real per-job authorization records, add the missing requester field to the repository-scan job, make VPN provisioning's approved-request check a hard precondition, and resolve the "representative user" owner-substitution design question (all five gaps are documented in the plan's own validation addendum). |
| **TS-ISO-012** — Data-Plane Fallback Completion | Full plan. |

**Why this phase is next:** TS-ISO-017's job-authorization contract needs TS-ISO-014's named workload identities to have somewhere real to attach to; doing it before Phase 2 would mean building the contract twice.

**Blast radius:** Medium-high. TS-ISO-017 touches every background job family (uploads, repository scans, Knowledge Graph rebuilds, SaaS sync, LLM framework, VPN provisioning). Follow the plan's own §10 deployment sequence — canary job first (already done in Phase 1), then migrate one job family at a time, disabling each legacy payload path only after cutover, never running both indefinitely.

---

## Phase 4 — Data lifecycle and file-access redesign

**Prerequisite:** Phase 3's authorization contract exists (TS-ISO-011's deletion saga and TS-ISO-010's workload identity both assume a real per-request/per-job authorization context, not a synthetic one).

| Plan | Scope |
|---|---|
| **TS-ISO-011** — Cross-Store Deletion | Full plan, beyond the Phase 1 Qdrant fix: the durable deletion saga, store adapters, and evidence chain across Postgres/Qdrant/S3/OAuth-provider/quarantine-directory/iptables — the five orphaned data classes found during validation (chat-attachment S3 objects, avatar/logo S3 copies, unrevoked OAuth grants, the file-import quarantine directory and its table, and the per-tenant iptables chain) must all be added to the store inventory, not just the two already-known stores. |
| **TS-ISO-010** — Internal File Proxy Hardening | Full plan, beyond the Phase 1 XFF fix: signed workload identity, opaque locators, signed requests (§4.1–4.6). Has a real Java/WildFly component (the Teiid remote-file connector) in addition to the Python API — implementation and deploy will need a Maven rebuild and WildFly redeploy alongside the platform-api changes, not just an API restart. Reuse the already-existing per-tenant `teiid_api_key` mechanism (`tenant_provisioning_service.py`/`tenant_teiid_resolver.py`) to back the connector's already-present but currently-unused `X-API-Key` support, rather than building a new per-tenant credential path from scratch. |

**Blast radius:** High for TS-ISO-011 (touches five independent stores plus two external OAuth providers); high for TS-ISO-010 (spans two runtimes — Python and Java/WildFly). Both plans should ship with the regression-test baseline called out in their own validation addenda (TS-ISO-010 currently has zero automated tests for the file-proxy route) before their respective redesigns land, not after.

---

## Phase 5 — Cloud network and infrastructure hardening

**Prerequisite:** TS-ISO-012 (Phase 3) and TS-ISO-014 (Phase 2) must be complete — TS-ISO-019 depends on both explicitly.

| Plan | Scope |
|---|---|
| **TS-ISO-019** — Cloud Network Hardening | Full plan. This is a multi-month infrastructure migration, not a fast-follow: replace the only reachable public application host with a private ALB/SSM topology, prove SSM administration and break-glass recovery *before* removing SSH, move the AI instance into the existing private subnet, remove the hardcoded `/32` trust of a single IP, enforce IMDSv2, attach the SSM IAM instance profile that today only exists as an unattached output and a comment saying "create manually," bind Docker container ports to loopback instead of all interfaces, replace all-egress security groups with default-deny plus approved-endpoint allowlists, and retire the shared-subnet/TGW routes to every tenant VPC and on-prem CIDR once TS-ISO-012's tenant-gateway migration is complete. |
| **TS-ISO-020** — AI/Infrastructure Secrets Hardening | Remainder beyond Phase 1's SECRET_KEY check: the full envelope-encryption/KMS redesign (§5.4–5.5), moving off static long-lived AWS keys in the compose/boto3 client construction, `chmod`-restricting the `.env` files both cloud-init templates write secrets into, and closing the replay-protection asymmetry between the two AI HMAC directions (one has a fail-open Redis check, the other has none). |

**Why this is last before observability/gates:** this phase requires production AWS console/Terraform-apply access, a staged blue/green cutover per TS-ISO-019 §10 ("use replacement infrastructure and weighted cutover rather than mutating the only reachable host in place"), and cannot be executed by an automated agent without a human explicitly approving each cutover step (DNS/target-weight shifts, SSH removal, NAT/route changes). **This phase must not be run unattended.** Each numbered step in TS-ISO-019 §10 and TS-ISO-020 §5 should be its own reviewed change with an explicit rollback drill per §11 of each plan before the next step starts.

**Blast radius:** Highest in the entire program — a mistake here can take down the only production application host or the AI service. No step in this phase should be executed without the specific human sign-off called for in each plan's own rollback section.

---

## Phase 6 — Observability, audit, and release gates

**Prerequisite:** Phases 2–5 substantially complete — both plans in this phase are explicitly designed to consume evidence from everything before them.

| Plan | Scope |
|---|---|
| **TS-ISO-021** — Security Audit and Alerting | Full plan. Build the `SecurityEventV1` canonical event schema using `app/services/billing_audit.py`'s existing canonical-event-name-constant + single-emit-function pattern as the starting template (found during validation to already implement the exact shape Section 5.1 describes, just log-only with no persistence/tenant-binding/alerting yet). Depends on TS-ISO-014 (service identity, for event attribution), TS-ISO-017 (job reauthorization, for job-side events), and TS-ISO-020 (secret lifecycle events) per its own header — all three land in Phases 2, 3, and 5 respectively. |
| **TS-ISO-022** — Assurance and Release Gates | Remainder beyond Phase 1's dependabot baseline: the full release-gating program — inventory/manifest schema, the cross-cutting isolation test matrix (26 existing component-level isolation test files already provide a strong foundation per the validation addendum; the gap is stitching them into one cross-cutting gate, not writing tests from zero), and the CODEOWNERS/branch-protection-as-code the validation pass confirmed does not exist today. Depends on evidence from every plan TS-ISO-004 through TS-ISO-021 existing and having passed its own acceptance criteria — this is intentionally the last plan to actually start blocking anything. |

**Why this is last:** TS-ISO-022's entire design is to gate future releases on evidence that the other ten plans' controls exist and pass — enforcing it before those controls exist would either block all releases immediately or (more likely) ship a gate with nothing real to check, which is worse than no gate. TS-ISO-022's Phase A (inventory, manifest schema, dependency tracking) is the exception — it can and should start in Phase 1 alongside the dependabot baseline, since it only needs the other plans' acceptance criteria to exist as text, which they now do.

---

## Sequencing summary

```
Phase 0 (done):  TS-ISO-003, 004, 005
Phase 1 (now):   TS-ISO-020(partial) · 022(partial) · 011(partial) · 017(canary) · 010(partial)
Phase 2:         TS-ISO-014 · TS-ISO-013
Phase 3:         TS-ISO-016 · TS-ISO-017(remainder) · TS-ISO-012
Phase 4:         TS-ISO-011(remainder) · TS-ISO-010(remainder)
Phase 5:         TS-ISO-019 · TS-ISO-020(remainder)
Phase 6:         TS-ISO-021 · TS-ISO-022(remainder)
```

## Ground rules for every phase after Phase 1

1. **No phase starts before the previous phase has deployed and run in production without a rollback for at least one full business cycle** (the plans' own bake-in/monitoring windows vary; use the longer of the plan's stated window or one week).
2. **Confirm RLS/identity coverage per-table/per-service before assuming it, per Phase 0's note.** "The plan is merged" and "the migration is merged" are not the same as "the control is enabled in production."
3. **Phases 5 requires explicit human approval at every cutover step** — this roadmap does not authorize an agent to run `terraform apply` against production, rotate production secrets, or change GitHub org/branch-protection settings unattended. Each such action needs its own confirmation at the time it's about to happen, not a blanket approval from this document.
4. **Each phase gets its own Devin merge+deploy doc** (this roadmap's Phase 1 doc is `docs/devin-ts-iso-phase1-fastfix-merge-deploy.md`), written only once that phase's code actually exists and has been tested — not written speculatively ahead of the implementation.
5. **No plan is closed by shipping its Phase.** Track the underlying finding as open in whatever issue tracker this repo uses until the plan's own acceptance criteria (its final numbered checklist) are fully met and evidenced, exactly as every prior validation round in this program has recommended.
