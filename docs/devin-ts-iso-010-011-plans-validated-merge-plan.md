# Devin: merge + deploy — two standalone security implementation plans (TS-ISO-010, 011)

**Repository:** `lhoskins/tablescope-lh`
**Target branch:** `UX-design-03`

## Why "no deploy" — read this before anything else

Every branch below adds **exactly one new Markdown file** under `docs/security/` and nothing else — confirmed with `git diff --stat` against each branch's stated base commit, which reports a single file changed in both cases. There is no application code, no database model, no migration, no configuration change, no Java connector change in either branch. These are **specifications for security hardening work that has not been implemented yet** — not the hardening itself.

That is why merging them has no runtime effect and needs no rebuild: there is nothing compiled, no server process, and no schema touched by a plan document. The actual controls each plan describes (a signed workload-identity system for the file proxy in TS-ISO-010; a durable cross-store deletion saga in TS-ISO-011) still need to be built, and *that* work will absolutely require migrations, new services, a Java/WildFly rebuild (TS-ISO-010 touches the Teiid remote-file connector), and a real deploy — see §5 for how that follow-on work should be scheduled. Don't confuse "the plan is merged" with "the vulnerability is fixed."

| Plan | Branch | Original commit | With validation addendum |
|---|---|---|---|
| TS-ISO-010 — Internal File Proxy Hardening | `codex/ts-iso-010-file-proxy-hardening` | `8a1561b4f42b285e5ae7c3ca468331c188d9fc94` | `1e21149bdc77f084c59bf398f93caed925ccfe1e` |
| TS-ISO-011 — Cross-Store Deletion | `codex/ts-iso-011-cross-store-deletion` | `c7262d1384b49108434acad465025df1a1d4b179` | `2fa581fcc3b56d992767c1e59c3af351cdef7f5e` |

Both branch from `UX-design-03` commit `1416dcf89cde8ff7219dc49c4f880d6f83be7de7` and merge cleanly onto the current tip — no conflict expected since each touches only its own new file, and neither overlaps with the four plan files already merged from the prior TS-ISO-012/013/014/016 validation round (`docs/ts-iso-012-013-014-016-validation`, already in `UX-design-03` as of `414de8f4`).

---

## 1. What was validated, and how

Every factual claim in each plan's "Current-state finding" table (Section 2 of each doc) was independently re-verified against the real repository content on `origin/UX-design-03` — reading the actual source files line-by-line and citing file:line evidence, not summarizing the plan's own prose back at it. This was done as two parallel research passes (one per plan), each explicitly instructed to verify against `origin/UX-design-03` and never a bare local branch name, following a stale-checkout mistake caught and corrected during the prior TS-ISO-012/013/014/016 validation round.

**Result: all 9 + 9 = 18 current-state claims across both plans were confirmed accurate.** Two findings turned out to be more severe than the plans' own wording states, and eleven additional concrete gaps were found and added to each plan's own file as a "Validation addendum" section:

### TS-ISO-010 (file proxy)

- **The `X-Forwarded-For` weakness is a live, unauthenticated pre-auth bypass today, not a passive weakness as Section 2 frames it.** `nginx/conf.d/app.conf` appends to `X-Forwarded-For` rather than replacing it, and `_client_ip()` trusts the first comma-separated value. An external caller with no network position at all can spoof a trusted tenant CIDR directly in a request header and pass the route's only real authorization check. This is worth pulling forward and fixing ahead of the plan's own phased rollout — it does not require the full workload-identity redesign to close, only correct XFF handling (trust only from a configured, verified immediate-proxy peer) and could ship as an isolated, fast-follow fix before the rest of Section 5's phases land.
- **A per-tenant `teiid_api_key` secret mechanism already exists** (`tenant_provisioning_service.py`/`tenant_teiid_resolver.py`) and should back the Java connector's already-present but currently-unused `X-API-Key` support, rather than the plan building an entirely new per-tenant credential path from Section 4.1 forward.
- Zero automated tests exist for this route today — recommend treating a regression-test baseline as an explicit early deliverable, not something that only appears at the end of Phase D.
- The route bypasses Postgres RLS entirely (it's on the anonymous-path list, so `AuthMiddleware` never establishes `rls_scope`), not just the app-level tenant checks Section 2 names.

### TS-ISO-011 (cross-store deletion)

- **Qdrant deletion is not "not durably wired" — it's dead code.** `delete_tenant_collection`/`delete_project_vectors` have zero callers anywhere in the codebase, and the one function's exception handler converts *every* failure (not just genuine not-found) into a false "not found" success. Section 6.3 should name both defects explicitly.
- **Five concrete data classes are orphaned by tenant/project deletion today** and are missing from Section 6/9's store inventory: chat-attachment S3 objects, avatar/company-logo S3 copies, unrevoked OAuth grants at the identity provider (Google Drive/QuickBooks tokens are deleted from our DB but never revoked upstream), the file-import quarantine directory plus the `file_import_jobs` table itself (absent from the tenant-purge table list), and the host-level per-tenant iptables firewall chain (the rendered teardown script never touches it, so a stale network-egress rule survives a "torn down" data plane indefinitely).

Full citations for every claim and gap are in each plan's own "Validation addendum" section (added to the file in this validation pass) — read those before starting implementation, not just this summary.

---

## 2. Merge

```bash
git fetch origin

git checkout -b merge-ts-iso-010 origin/UX-design-03
git merge origin/codex/ts-iso-010-file-proxy-hardening
# push / open PR

git checkout -b merge-ts-iso-011 origin/UX-design-03
git merge origin/codex/ts-iso-011-cross-store-deletion
# push / open PR
```

Each merge adds exactly one file: `docs/security/ts-iso-010-file-proxy-hardening.md` or `docs/security/ts-iso-011-cross-store-deletion.md`. No conflict is expected merging both into the same target branch sequentially.

**Merge rule:** do not edit the plan content while merging. If a reviewer disagrees with a specific claim or the addendum, resolve it as a follow-up commit with its own file:line justification.

---

## 3. Verification

| Check | Result |
|---|---|
| Each branch contains exactly one plan file (plus its addendum commit) | Confirmed via `git diff --stat` against each branch's stated base commit — single-file diff in both cases |
| Branch ancestry | `git merge-base <branch> 1416dcf89cde8ff7219dc49c4f880d6f83be7de7` returns the base commit itself for both — each is a clean linear descendant |
| Commit SHA match against GitHub | Both original commit SHAs (`8a1561b4...`, `c7262d13...`) match exactly what `git fetch origin` retrieved |
| Whitespace | `git diff --check` on both files shows only intentional Markdown hard-line-break trailing double-spaces in the header metadata block (6 lines each, e.g. `**Status:** Open — implementation required  `) — this is deliberate Markdown syntax, not a formatting defect, and matches the style already used in the previously-merged `ts-iso-004-postgres-rls-design.md`. No unintended whitespace issues found. |
| Factual claim validation | 18/18 current-state findings across both plans confirmed accurate against `origin/UX-design-03`; see §1 |

No `pytest`/`vitest`/`ruff`/`mypy`/`tsc`/`mvn` run is applicable — these branches contain no application code.

---

## 4. Deploy

**Nothing to deploy** — see the note at the top of this document. Merging these two branches into `UX-design-03` has zero runtime effect.

---

## 5. What happens next (scheduling, not deployment)

1. **TS-ISO-010's XFF finding (§1) can and should ship as an isolated, fast fix independent of the rest of the plan.** Trusting `X-Forwarded-For` only from a configured, verified immediate-proxy peer (rather than blindly parsing the first CSV value) closes the live spoofing path without needing the full signed-workload-identity redesign (Section 4.1–4.3 of the plan) to land first. Recommend scheduling this as its own small, fast PR ahead of the rest of TS-ISO-010's phases.
2. The remainder of TS-ISO-010 (workload identity, opaque locators, signed requests — Sections 4.1–4.6) and all of TS-ISO-011 (the deletion saga, store adapters, evidence chain) are multi-phase efforts described in each plan's own "Implementation work breakdown" and "Deployment sequence" sections. Track each as its own scheduled engineering effort referencing the plan doc as spec, the same way the prior TS-ISO-012/013/014/016 validation round recommended.
3. TS-ISO-010 has a real Java/WildFly component (the remote-file connector) in addition to the Python API — implementation and deploy for that plan will need a Maven rebuild and WildFly redeployment alongside the platform-api changes, not just an API restart.
4. TS-ISO-011 depends on TS-ISO-004 (Postgres RLS foundation, already merged) and TS-ISO-005 (vector-store authorization, already merged) for its Postgres and Qdrant adapters respectively — both dependencies are satisfied on `UX-design-03` today, so TS-ISO-011's Phase A (inventory and policy) can start without waiting on any other in-flight plan.
5. Neither plan should be treated as closed by merging its planning doc. Each plan's own closing line states its exit condition (e.g. "TS-ISO-011 must remain open until the production-like isolation matrix... have been reviewed and attached to the finding") — track the underlying finding as open in whatever issue tracker this repo uses until the implementation and its test evidence are actually complete.

---

## 6. Report back

Confirm both PRs merge cleanly into `UX-design-03` with no conflicts. No further verification (test run, deploy, migration) applies to this merge.
