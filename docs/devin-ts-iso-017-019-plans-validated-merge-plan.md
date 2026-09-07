# Devin: merge + deploy — two standalone security implementation plans (TS-ISO-017, 019)

**Repository:** `lhoskins/tablescope-lh`
**Target branch:** `UX-design-03`

## Why "no deploy" — read this before anything else

Every branch below adds **exactly one new Markdown file** under `docs/security/` and nothing else — confirmed with `git diff --stat` against each branch's stated base commit, which reports a single file changed in both cases. There is no application code, no database model, no migration, no Terraform change, no CI workflow change in either branch. These are **specifications for security/infrastructure hardening work that has not been implemented yet** — not the hardening itself.

That is why merging them has no runtime effect and needs no rebuild, no `terraform apply`, and no redeploy: there is nothing compiled, no server process touched, and no cloud resource affected by a plan document. The actual controls each plan describes (a signed job-authorization contract with per-tenant RLS-scoped workers in TS-ISO-017; removing public hosts, open SSH, and unrestricted egress from the Terraform in TS-ISO-019) still need to be built — see §5 for how that follow-on work should be scheduled. Don't confuse "the plan is merged" with "the finding is closed."

| Plan | Branch | Original commit | With validation addendum |
|---|---|---|---|
| TS-ISO-017 — Background Job Reauthorization | `codex/ts-iso-017-background-job-reauthorization` | `7439877d6d8486d626492fbab5fecebe4c0c0e9e` | `542bf2df` |
| TS-ISO-019 — Cloud Network Hardening | `codex/ts-iso-019-cloud-network-hardening` | `5e0025240f9f75c4db6ab18d954ebe607a4ff9c7` | `76eed865` |

Both branch from `UX-design-03` commit `414de8f424c76980924af7dea05d64919daaa7ed` — confirmed via `git merge-base` to be a clean linear ancestor of `origin/UX-design-03` (which has since advanced to `966abba6`) — and merge cleanly onto the current tip. Each touches only its own new file, so no conflict is expected against each other or against any of the previously-merged TS-ISO-010/011/012/013/014/016/020/021/022 validation rounds.

---

## 1. What was validated, and how

Every factual claim in each plan's "Current-state finding" table (Section 2 of each doc) was independently re-verified against the real repository content on `origin/UX-design-03` at `966abba6` — reading the actual source and Terraform files line-by-line and citing file:line evidence, not summarizing the plan's own prose back at it. This was done as two parallel research passes (one per plan), each explicitly instructed to fetch and verify against `origin/UX-design-03` and never a bare local branch name, per the stale-checkout lesson from the first TS-ISO-012/013/014/016 validation round.

**Result: 11 + 17 = 28 current-state claims across both plans; 27 confirmed fully accurate, 1 needed a wording correction (not wrong in substance, just imprecise).** Each plan's own file now carries a validation addendum with the full findings; summary below.

### TS-ISO-017 (background job reauthorization)

- All 11 current-state claims confirmed accurate: plain unsigned `arq` kwargs with no envelope (`workflows.py`, whole 1674-line file checked), 20 bare `SessionLocal()` sites with zero `rls_scope` calls, `_worker_context` synthesizing a literal `role="admin"` with no permissions/membership check (reused at 5 call sites), and specific gaps in VDB redeploy, repository scan, KG rebuild/health-check, SaaS sync, LLM-framework artifact jobs, VPN provisioning, and in-process `BackgroundTasks` usage.
- **5 additional gaps found and added to the plan's own addendum, not previously in Section 2's table:**
  1. `app/database.py:60-79` already defines a `tenant_session` helper wrapping `rls_scope` for exactly this worker use case — it has **zero callers anywhere in the codebase**. The remediation should adopt this existing helper rather than design a new one.
  2. `enqueue_scan_repository_connection`/`scan_repository_connection` carry **no requester field at all** (not merely an unverified one) — the fix here is adding an actor field to the payload, a different shape than the "re-verify an existing ID" fix that applies to the other jobs.
  3. `provision_tenant_vpn` proceeds with the raw queue-supplied network parameters even when **no matching `TenantProvisioningRequest` row exists** — the `if req is not None` checks only gate post-hoc status writes, not the AWS provisioning call itself. The redesigned check needs to be a hard precondition, not a description of consulting a record.
  4. `refresh_business_insight_result`/`evaluate_stale_graphs` re-attribute work to a "representative user" (`resolve_representative_user`) before `_worker_context` synthesizes admin credentials for that substituted user — an open design question about whose consent/role the new authorization record should actually capture.
  5. `google_drive_token_refresh.py`/`quickbooks_token_refresh.py` share the same bare-`SessionLocal()` gap and touch credential material, but weren't in Section 7's job inventory — lower priority than the queue-driven jobs, but worth a mention.

### TS-ISO-019 (cloud network hardening)

- 16/17 claims confirmed fully accurate, including: default-VPC/public-subnet fallback, `associate_public_ip_address = true` on the app instance, SSH default `0.0.0.0/0` on both instances, all-protocol/`0.0.0.0/0` egress on both security groups, the ED25519 key + `.pem`-file-write pattern, SSH/log-tail command outputs, the AI instance sitting in the **public** subnet despite a private subnet existing in the same Terraform, the hardcoded `app_server_ip` default trusted as a bare ingress CIDR, all-egress + NAT route for the AI subnet, the SSM output present with no `iam_instance_profile` ever attached (plus an explicit code comment admitting the IAM role must be created by hand), the total absence of any `metadata_options` block (IMDSv2 unenforced) on either instance, the plain unauthenticated instance-metadata `curl` in the idle-check cron script, unbound Docker port publishing in both compose files, all-egress tenant/S3-endpoint security groups, and shared-subnet/TGW routes propagated to every tenant VPC and on-prem CIDR.
- **1 correction:** the plan states CI "formats" the VPN test Terraform in addition to running it. In fact `.github/workflows/vpn-smb-e2e.yml`/`scripts/vpn-smb-e2e/run.sh` run only `terraform init`/`plan`/`apply` — there is no `terraform fmt` or `terraform validate` step anywhere. The no-IaC-scanner half of the claim is confirmed accurate. Corrected wording is now in the plan's own addendum; this makes the starting gap slightly larger than originally stated (no automated formatting or static validation at all, not just no security-specific scan).

Full citations for every claim and every gap are in each plan's own "Validation addendum" section — read those before starting implementation, not just this summary.

---

## 2. Merge

```bash
git fetch origin

git checkout -b merge-ts-iso-017 origin/UX-design-03
git merge origin/codex/ts-iso-017-background-job-reauthorization
# push / open PR

git checkout -b merge-ts-iso-019 origin/UX-design-03
git merge origin/codex/ts-iso-019-cloud-network-hardening
# push / open PR
```

Each merge adds exactly one file: `docs/security/ts-iso-017-background-job-reauthorization.md` or `docs/security/ts-iso-019-cloud-network-hardening.md`. No conflict is expected merging both into the same target branch sequentially, or against any previously-merged TS-ISO plan-validation branch.

**Merge rule:** do not edit the plan content while merging. If a reviewer disagrees with a specific claim or the addendum, resolve it as a follow-up commit with its own file:line justification.

---

## 3. Verification

| Check | Result |
|---|---|
| Each branch contains exactly one plan file (plus its addendum commit) | Confirmed via `git diff --stat` against each branch's stated base commit — single-file diff in both cases (434 and 393 lines respectively for the original plan commits; the addendum commits add 19 and 10 lines respectively) |
| Branch ancestry | `git merge-base <branch> 414de8f424c76980924af7dea05d64919daaa7ed` returns the base commit itself for both — each is a clean linear descendant |
| Commit SHA match against GitHub | Both original commit SHAs (`7439877d...`, `5e002524...`) match exactly what `git fetch origin` retrieved |
| Whitespace | `git diff --check` clean on both addendum commits |
| Factual claim validation | 28 current-state findings across both plans; 27 confirmed accurate, 1 wording correction (no claim found materially wrong) — see §1 |

No `pytest`/`vitest`/`ruff`/`mypy`/`tsc`/`terraform validate` run is applicable — these branches contain no application or infrastructure code, only Markdown.

---

## 4. Deploy

**Nothing to deploy** — see the note at the top of this document. Merging these two branches into `UX-design-03` has zero runtime effect.

---

## 5. What happens next (scheduling, not deployment)

1. TS-ISO-017 depends on TS-ISO-004 (Postgres RLS foundation, already merged) and TS-ISO-014 (service identity scoping, plan already merged but not yet implemented) per its own header. The `tenant_session` adoption gap (§1) is a good candidate for an early, isolated fix since the helper already exists — it doesn't require the full signed-envelope/job-model redesign to land first.
2. TS-ISO-019 depends on TS-ISO-012 (data-plane fallback completion) and TS-ISO-014 (service identity scoping) per its own header, and is explicitly related to TS-ISO-017 (both plans list each other as related findings, since job workers and the network they run on are two faces of the same worker-identity problem).
3. TS-ISO-021 (security audit/alerting, already validated) lists TS-ISO-017 as a dependency for its Phase B integration — sequence TS-ISO-017's core job-authorization contract ahead of that phase. TS-ISO-022 (assurance/release gates, already validated) depends on evidence from every TS-ISO plan including these two, so it remains realistically the last of the eleven to actually enforce anything.
4. TS-ISO-019 is a multi-month infrastructure migration (replace the only reachable public host with a private ALB/SSM topology before removing SSH) — its own plan text is explicit that "replacement infrastructure and weighted cutover" must be used rather than mutating the one reachable host in place, and that SSH must not be removed until SSM and its private dependencies are independently proven. This is not a fast-follow fix; it needs its own project plan, staged rollout, and rollback drills exactly as Sections 10–11 describe.
5. Neither plan should be treated as closed by merging its planning doc. Each plan's own closing line states its exit condition — track the underlying finding as open in whatever issue tracker this repo uses until the implementation and its test evidence are actually complete.

---

## 6. Report back

Confirm both PRs merge cleanly into `UX-design-03` with no conflicts. No further verification (test run, deploy, migration, `terraform apply`) applies to this merge.
