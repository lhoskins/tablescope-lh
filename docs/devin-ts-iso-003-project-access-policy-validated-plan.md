# Devin: merge + deploy — TS-ISO-003, six confirmed project-access bugs closed

Repository: `lhoskins/tablescope-lh`
**Branch to merge:** `security-ts-iso-003`, at `b5f57435`
**Base:** `release/deploy-2026-08-07`, unchanged at `0976c27f`
**Merge test:** clean, **no conflicts** (verified via throwaway-branch
`git merge --no-commit --no-ff` against current `release/deploy-2026-08-07`
HEAD).

This is increment 2 of the tenant/project isolation security work
(increment 1: `e189ec9e`, TS-ISO-001/002/006/007/008/009/015/018, already on
`release/deploy-2026-08-07`). It addresses **TS-ISO-003** — the systemic
finding that the codebase has "at least 6 divergent project-access
implementations." Rather than blindly rewriting every route family onto one
abstraction, this increment **audited each candidate file, kept the ones
that were already correct untouched, and fixed the ones that weren't** —
six confirmed, independently-reproduced bugs. See §5 for what's
deliberately not in this increment.

---

## 1. Merge rules — read first

1. **Do not modify, rewrite, refactor, rename, or reformat the delivered
   code. Merge as-is.** If `release/deploy-2026-08-07` has moved again by
   the time you run this, resolve any conflict by preserving the delivered
   code exactly and adapting only the surrounding lines it touches — do not
   use conflict resolution as an opportunity to "clean up" anything nearby.
2. Suspected bug in this delta → **report it in the PR description**, don't
   silently change it.

```bash
git fetch origin
git checkout -b devin/ts-iso-003-project-access origin/release/deploy-2026-08-07
git merge origin/security-ts-iso-003
```

---

## 2. What shipped (commit `b5f57435`)

**New:** `platform-api/app/services/project_access.py` — the single
canonical policy (`authorize_project_access`): a project is accessible iff
the caller owns it or has an ACTIVE `ProjectMember` row; `is_shared`
affects discoverability, never authorization by itself.
`ai_proxy_shared.py`'s `_authorize_project_access`/`_check_project_access`
now delegate to it as thin wrappers — its 17 existing importers
(`ai_proxy_*.py`, `conversational_analytics_turns.py`, `project_assets.py`,
`query.py`, `workspaces.py`) are unaffected.

| # | File | Bug | Fix |
|---|---|---|---|
| 1 | `knowledge_graph.py` | `/health` and `/builds/{build_id}` performed **no project-access check at all** — any authenticated user could read another **tenant's** knowledge-graph health/build data by supplying its `project_id`/`build_id`. This is the concrete cross-tenant bug the original TS-ISO-003 finding named but didn't fix. The other routes in this file (`/status`, `/builds` list, `/versions`, `/dependencies/executive-insight`, plus the two rebuild/health-check POSTs) only checked tenant membership via the service-layer `_require_project`, not project ownership/active-membership — a same-tenant, **cross-project** leak for a VIEWER-role user who isn't a member of a private or shared project. | Every route in this file now calls `authorize_project_access()` at the route boundary before touching the lifecycle/health service. |
| 2 | `project_insight.py`, `project_actions_shared.py`, `home_pins.py` | Each had `if project.owner_id == user_id or project.is_shared: return project` — grants **any same-tenant user** access to a shared project, with the membership-check code directly below made unreachable whenever the project happened to be shared. **This is a new finding, not previously documented**: the earlier TS-ISO-009 fix's own comment cited these three files as already-correct examples of filtering `is_active` on membership — true of the code below the shortcut, but that code never runs for a shared project, so the citation missed the real bug. | Removed the `or project.is_shared` shortcut in all three files — a shared project now requires active membership for non-owners, same as everywhere else. |
| 3 | `reference_library_documents.py`, `projects_shared.py` | Queried `ProjectMember` without filtering `is_active` — a removed member (`reference_library_documents.py`) or one demoted from project-admin (`projects_shared.py::_is_project_admin`) kept access/admin rights indefinitely. Same bug class as the already-fixed TS-ISO-009. | Added the `is_active` filter. |

**9 files changed, 516 insertions(+), 46 deletions(-).**

### Test status

- **14 new tests** (`tests/test_ts_iso_003_project_access.py`), one or more
  per fix above, covering: cross-tenant denial on `/health` and
  `/builds/{id}`, same-tenant non-member denial on both private and shared
  projects, active-member success, and deactivated-member denial. **Each
  test was independently confirmed to fail against the pre-fix code** (via
  `git stash`) before being counted as passing — not just written to match
  the new behavior.
- **Full platform-api suite**: `1652 passed, 3 failed, 4 skipped` (852s).
  The 3 failures (`test_business_insight_phase1.py::test_snapshot_fresh_when_no_kg_build_postdates_it`,
  `test_snapshot_stale_after_kg_rebuild`, `test_snapshot_null_without_run`)
  are `redis.exceptions.ConnectionError` — no local Redis in this sandbox,
  identical to the pre-existing failures already documented in the
  increment-1 doc (reproducible on `release/deploy-2026-08-07` before this
  branch's commits, unrelated to this change). The 4 skips are the VPN/SMB
  E2E suite (needs a live endpoint), also pre-existing.
- `ruff check` and `mypy` on all changed files: clean.

---

## 3. Deploy steps

1. Merge per §1.
2. No new environment variables, no new dependencies, no migration —
   this is application-logic only.
3. Rebuild `platform-api`:
   ```bash
   docker compose build platform-api
   docker compose up -d platform-api
   ```
4. `platform-api-worker` runs the same image — recreate it too if it isn't
   already picked up by the `up -d` above, since the knowledge-graph
   rebuild/health-check workflows it processes are unaffected by these
   route-level checks but should still run the same image as the API.

### Rollback

No data changes — rollback is redeploying the previous `platform-api`
image.

---

## 4. Verify live

- **`knowledge_graph.py` cross-tenant**: as a user in tenant A, request
  `GET /api/projects/{a project id from tenant B}/knowledge-graph/health`
  (or `/builds/{id}`) — expect 404, not another tenant's data.
- **Same-tenant, non-member, shared project**: as a user with no
  `ProjectMember` row on a *shared* project in your own tenant, request
  that project's KG `/status`, or its `/insight`, or its `/actions` list,
  or try to pin something into it via Home Pins — expect 403 (404 for Home
  Pins specifically, per that file's existing error-code design) on all
  four, where before this fix at least the latter three would have
  succeeded.
- **Active member still works**: add yourself as an active `ProjectMember`
  on that same project and confirm all of the above now succeed (200/201).
- **Deactivated member**: remove/deactivate a `ProjectMember` row and
  confirm Reference Library project-tier document listing now returns 403
  for that user, and that a demoted-from-admin member can no longer edit
  datasource column types on that project.

---

## 5. Explicitly out of scope for this increment

The remaining files this session found and confirmed **already correct**
during the audit — `data_source_catalog.py`, `home_intelligence_suite.py`,
`home_intelligence_suggestions.py`, `projects_crud.py` — were deliberately
left untouched. Consolidating them onto `app.services.project_access` is a
pure refactor with no bug behind it: real value for long-term
maintainability (one rule to read instead of six), but strictly lower
priority than the six confirmed bugs above, and separable work. Recommend
scoping it as its own follow-up if/when it's prioritized, rather than
folding it into a security-bug-fix PR.

The rest of the original tenant/project isolation assessment
(TS-ISO-004, 005, 010–014, 016, 017, 019–022) remains open, per
`docs/devin-tenant-project-isolation-security-validated-plan.md` §4 —
unchanged by this increment.
