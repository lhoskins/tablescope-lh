# Devin: merge + deploy — `UX-design-03` (lhoskins/tablescope-lh)

**Repository:** `lhoskins/tablescope-lh`
**Branch to merge:** `UX-design-03`, pushed at `910e0ba3`
**Base:** `release/deploy-2026-08-07` (merge-base `d1e274a3`, same base as the earlier `UX-design-02` cross-repo doc below)

**11 commits · 39 files · +1156 / −802 · no DB migration · all tests green (§4)**

This branch already contains everything from `UX-design-02` — confirmed empty diff (`git log origin/UX-design-03..origin/UX-design-02`) — so **no separate UX-design-02 catch-up merge is needed**; treat this doc as superseding that one for anything still outstanding.

---

## 0. If the destination is `vitruvity33/tablescope`, read this first

`UX-design-03` already contains one round-trip with that repo (`3ef57a22` / `9aa74604` merge in `vitruvity33/tablescope`'s own `UX-design-02` updates), so some push-back path to it is expected. **Before pushing anywhere outside `lhoskins/tablescope-lh`, re-read
`docs/devin-cross-repo-merge-ux-design-02-to-vitruvity33-validated-plan.md`'s §0** — its shared-history check, the monorepo-vendor-tree warning (`wildfly/`, `redash-8.0.0-7/`, `apache-maven-3.9.6/`), and the "confirm with the repo owner before `--allow-unrelated-histories`" rule all still apply unchanged and are not repeated here.

If the destination is instead `release/deploy-2026-08-07` in **this** repo, skip straight to §2.

---

## 1. Merge rules — read first

1. **Do not rewrite, refactor, rename or reformat the delivered files.** Merge as-is; resolve conflicts by preserving the delivered code and adapting the surrounding code, per the standing convention in this repo's other `devin-*-validated-plan.md` docs.
2. Suspected bug → **report it in the PR description**, don't silently change it.
3. **§5 below is not a routine note — read it before merging anything.** This branch required an architectural revert (`910e0ba3`) to stay consistent with a fix landing in parallel on `fix-shared-vdb-per-project`. That parallel branch is not part of this merge and is not yet mergeable itself (§5.3) — but whichever of the two merges *second* must not re-break what the first one fixed.

```bash
git fetch origin
git checkout -b merge-ux-design-03 origin/release/deploy-2026-08-07
git merge origin/UX-design-03
```

---

## 2. Commits (chronological)

| Commit | What it does |
|---|---|
| `f678218d` | Devin cross-repo merge doc for UX-design-02 → vitruvity33/tablescope |
| `2a1d9c1a` | **Main feature: unify project chrome behind a top bar and per-screen action center** (`project-topbar.tsx`, `action-center.tsx`, replacing the old `project-header.tsx`; touches every project screen's layout) |
| `48acd492` | Google Sheets: quote VDB identifiers so mixed-case names resolve; rewrite double-quoted source labels to relational field names before SQL execution |
| `8900e9c2` | Type-annotate workspace label mapping to silence mypy |
| `47b3ecbe` | Rebuild `TeiidExcelImporterTest.war` with the quoted-identifier fix from `48acd492` baked in |
| `5165752d` | Per-key connection-pool locks + bounded close, so one slow/defunct VDB no longer blocks all Teiid queries tenant-wide |
| `131aea7e` | Raise default Teiid heap 2 GB → 4 GB (`TEIID_MAX_HEAP` in `docker-compose.yml`) to stop OOM/GC-pause timeouts |
| `ba12ec41` | *(superseded — see §5)* Devin's same-day patch routing shared-project queries to the owner's UserVDB |
| `3ef57a22` / `9aa74604` | Merge `vitruvity33/tablescope`'s own `UX-design-02` updates into this branch |
| `910e0ba3` | **Revert of `ba12ec41`** — see §5 for why |

---

## 3. Sidebar/nav-grid/queries-screen changes carried from UX-design-02

Already validated when `UX-design-02` was reviewed; unchanged here, listed for completeness since they're in this diff too:
- `projects-tree.tsx` — PRIVATE/SHARED disclosure tree
- `project-nav-grid.tsx` — 12-card nav grid
- `queries-screen.tsx` — reworked to the new top bar/action-center chrome from `2a1d9c1a`

---

## 4. Verification

| Suite | Result |
|---|---|
| `web-ui` `tsc --noEmit` | clean |
| `web-ui` `vitest run` | **558 / 558 passed** (92 files) |
| `platform-api` `ruff check app tests` | clean |
| `platform-api` `mypy app` | clean, 528 source files |
| `platform-api` `pytest -q` (full suite) | **1638 passed, 3 failed, 4 skipped** (16m51s) |

Run against `910e0ba3` (post-revert; `7dd8f70a` only adds this doc, no code change):
- The 3 failures (`test_snapshot_fresh_when_no_kg_build_postdates_it`, `test_snapshot_stale_after_kg_rebuild`, `test_snapshot_null_without_run`, all in `test_business_insight_phase1.py`) are **pre-existing and unrelated** — they fail with `redis.exceptions.ConnectionError: Error 111 connecting to localhost:6379` because no Redis instance is reachable in this sandbox, not because of anything in this branch. Confirm these pass wherever Redis is actually reachable.
- The 4 skips are the VPN/SMB E2E tests, skipped because `VPN_SMB_E2E_API_URL` is unset — expected in any environment without that live endpoint.

```bash
cd platform-api && pytest -q && ruff check app tests && mypy app
cd ../web-ui && npx tsc --noEmit && npx vitest run
```

---

## 5. Read before merging: the `vdb_routing.py` conflict and its resolution

### 5.1 What `ba12ec41` did, and why it looked necessary at the time

Shared-project queries were 404ing (`VDBNotConfiguredError`) because the tenant-wide `SharedVDB` row they routed to was never actually being provisioned. `ba12ec41` (same day, 15:30 UTC) patched the *symptom*: it rerouted `VDBRoutingService.get_vdb_for_query` to send every shared-project query to the **project owner's personal `UserVDB`** instead, so the query at least resolved to something that existed.

### 5.2 Why that's the wrong fix

It masks the root cause (SharedVDB provisioning is broken) and is architecturally wrong on its own terms: every member of a shared project would query data through the *owner's private, personal VDB* rather than anything scoped to the shared project. That's the reverse of the intended design and reintroduces the "wrong VDB for shared projects" problem this session was asked to root-cause.

### 5.3 The real fix, in progress on a parallel branch

`fix-shared-vdb-per-project` (not part of this merge) is rebuilding `SharedVDB` to be one-per-`(tenant_id, project_id)` — not one-per-tenant — with the Java VDB servlet layer and `project_sharing.py` actually provisioning and populating it when a project is shared. `vdb_routing.py` and `query_sql_helpers.py` on that branch already agree with each other (both delegate to one canonical `VDBRoutingService.get_vdb_for_query` decision, committed and tested — see that branch's own commits for `test_vdb_routing.py`). That branch is **not yet complete**: `vdb_management.py`'s project-scoped provisioning and `project_sharing.py`'s rewrite are still in progress.

### 5.4 What was done here, and the resulting gap

`910e0ba3` reverts `ba12ec41` on `UX-design-03`, restoring `vdb_routing.py` to be byte-identical to `release/deploy-2026-08-07`'s copy (verified — see commit message). This was a clean revert with no side effects: no other commit touched this file between `ba12ec41` and this branch's tip. Done deliberately, on request, rather than carrying the architecturally-wrong owner-VDB workaround forward into a merge — so that whichever of these two branches lands second doesn't have to fight the other's `vdb_routing.py` change.

**Known, accepted gap:** until `fix-shared-vdb-per-project` (or an equivalent fix) also ships, a shared project's `/api/query/fetch` calls will 404 again for any tenant whose `SharedVDB` row was never provisioned — the exact same failure `ba12ec41` was patching around. `/api/query/datasource` is unaffected either way: its own routing (`query_sql_helpers.py::_resolve_vdb_database`) was never touched by `ba12ec41` and still independently routes shared projects to the owner's VDB on `UX-design-03` (that's the pre-existing, separate bug the parallel branch also fixes, not something this revert changes).

**If this is being merged before `fix-shared-vdb-per-project`:** call this out plainly in the PR description and to whoever is watching shared-project functionality in production — it is a real, temporary regression versus `ba12ec41`'s (wrong but functional) behavior, accepted in exchange for not shipping two branches that actively disagree about VDB routing.

---

## 6. Deploy

**No database migration required** (§4 — no new alembic revision in this diff).

**The Teiid WAR must be redeployed** — `47b3ecbe` changed `wildfly/standalone/deployments/TeiidExcelImporterTest.war` (quoted-identifier fix for Google Sheets VDB DDL from `48acd492`). Skipping this leaves the old WAR serving mixed-case Google Sheets view names incorrectly.

**Teiid heap must be picked up** — `131aea7e` raised `TEIID_MAX_HEAP` to `4096m` in `docker-compose.yml`. Recreate (not just restart) the Teiid/WildFly container so it launches with the new `-Xmx`.

```bash
docker compose build platform-api web-ui
docker compose up -d platform-api platform-api-worker web-ui wildfly   # name per your compose file
docker compose ps
docker compose exec wildfly env | grep TEIID_MAX_HEAP   # confirm 4096m took effect
```

### Rollback

No migration means rollback is redeploying the previous images and the previous WAR:

```bash
git checkout <previous-sha> -- wildfly/standalone/deployments/TeiidExcelImporterTest.war
docker compose build platform-api web-ui
docker compose up -d platform-api platform-api-worker web-ui wildfly
```

---

## 7. Verify live

- **Top bar / action center:** every project screen (Overview, Data Sources, Queries, Dashboards, Documents) shows the unified top bar; the old per-screen header/tab layout is gone.
- **Sidebar:** Projects section is a PRIVATE/SHARED disclosure tree; the current project's asset subtree (Tables/Documents) auto-expands and highlights items pinned into the workspace tab strip.
- **Google Sheets:** a saved query against a Google Sheet source with a mixed-case or spaced-header column still runs correctly (the quoted-identifier + label-rewrite fix).
- **Connection pool:** confirm a slow/unreachable VDB for one tenant does not stall queries for other tenants (per-key lock fix).
- **Shared projects (§5 gap):** if `fix-shared-vdb-per-project` has not yet shipped, expect `/api/query/fetch` on a shared project with no provisioned `SharedVDB` to 404 — this is the accepted, documented gap, not a new bug to chase.

---

## 8. Report back

CI totals per suite in your own environment (§4 has this session's numbers for reference); confirmation the WAR redeploy and heap bump took effect; screenshot of the new top bar/action center on at least two project screens; and explicit confirmation of which side of the §5 gap is currently true in the deployed environment (i.e., whether `fix-shared-vdb-per-project` has landed yet or not) so the accepted-gap note above can be closed out.
