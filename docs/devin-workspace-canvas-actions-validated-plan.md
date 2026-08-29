# Devin: merge + deploy — Workspace canvas (publish/rename/delete UI + data-source picker gap)

Repository: `lhoskins/tablescope-lh`
**Branch to merge:** `UX-design-01`
**Base:** `release/deploy-2026-08-07`
**Merge test:** clean, no conflicts (verified via throwaway-branch
`git merge --no-commit --no-ff` against `origin/release/deploy-2026-08-07`,
current HEAD `6c3a2df9`). One file, `workspace_context.py`, auto-merges —
the base branch renamed a local variable there for mypy (`row` →
`saved_query`/`dashboard`/`document`) after this branch forked; no logic
overlap.

This closes out a design review of the new "Workspace" feature (named,
ownable, publishable multi-card canvases per project): the review found the
feature architecturally sound and non-regressive, but flagged that the
backend's publish/unpublish/rename/delete endpoints had no UI, and that the
"Add card" picker silently omitted data sources despite full backend
support. Both are fixed in the second commit below.

---

## 1. Merge rules — read first

1. **Do not modify, rewrite, refactor, rename, or reformat the delivered
   code.** Merge as-is. If the base has moved further by the time you run
   this, resolve any conflict by preserving the delivered code exactly and
   adapting only the surrounding lines it touches — do not take the
   opportunity to "clean up" anything nearby.
2. Suspected bug in this delta → **report it in the PR description** with
   the exact line and reason. Do not silently change it.
3. Two commits, both authored in this delta:

```bash
git fetch origin
git checkout -b devin/workspace-canvas-actions origin/release/deploy-2026-08-07
git merge origin/UX-design-01
```

---

## 2. What shipped

| Commit | What it does |
|---|---|
| `a163c7fb` | The base Workspace feature: `workspaces` / `workspace_cards` tables (migration `0086`, single head, revises `6aeba63f3092`), owner/visibility model (`private` \| `shared_project`, mirrors the existing `project_assets` pattern), full CRUD + publish/unpublish routes (`app/routes/workspaces.py`), and the canvas UI (tab bar, card grid, add-card picker, AI assistant panel scoped to the active workspace's cards). |
| `39a051d1` | **This increment.** (a) Each workspace tab gets an owner-gated kebab menu — Rename (inline, commit on blur/Enter, cancel on Escape), Publish/Unpublish (toggles `visibility`), Delete (behind a confirm dialog, reassigns the active tab if the deleted one was active) — wired to the publish/unpublish/rename/delete endpoints that already existed in `a163c7fb` but had no caller anywhere in the UI. (b) The "Add card" picker now also offers **database and SaaS data sources** (`useProjectDataSources`), not just tables/dashboards/documents. Restricted to sources whose `id` is a `DatabaseDataSource` row (`isDatabase`/`isSaas`) — file-backed sources use a different id space (`FileSourceMeta.id`) and were deliberately excluded rather than risk sending the backend a `resource_id` it resolves against the wrong table. |

**33 files changed, 3479 insertions(+), 30 deletions(-)** across both
commits (`git diff --stat 33c7dbf6..39a051d1`). No files outside
`platform-api` and `web-ui`.

### Test status

- **web-ui**: `tsc --noEmit` clean, `eslint` clean, full `vitest` suite —
  **90 files / 545 tests passed**, including 8 new tests in this increment
  (`workspace-tab-bar.test.tsx`: menu gating, rename, publish, unpublish,
  delete; new `workspace-add-card.test.tsx`: data-source offering and the
  database/SaaS-vs-file id filtering).
- **platform-api**: `test_workspaces.py` (backend CRUD/publish/rename/delete,
  owner-only enforcement) and `test_workspace_context.py` were exercised as
  part of the original `a163c7fb` review — this increment (`39a051d1`)
  touched no backend files, so re-run them as part of normal CI rather than
  as a targeted check:
  ```bash
  cd platform-api && pytest tests/test_workspaces.py tests/test_workspace_context.py -q
  ```

---

## 3. Deploy steps

1. Merge per §1.
2. **New Alembic migration**: `0086_workspaces` (from `a163c7fb`, already on
   this branch, revises `6aeba63f3092`). Confirm it is still the single head
   after merging — `release/deploy-2026-08-07` has not added any migrations
   since this branch forked, so it should apply cleanly:
   ```bash
   cd platform-api && alembic heads   # expect exactly one head
   alembic upgrade head
   ```
3. No new environment variables, no new dependencies, no config changes.
4. No cache to clear and no background job to re-run — this is a plain
   CRUD + UI feature, nothing precomputed.
5. Rebuild both changed images:
   ```bash
   docker compose build platform-api web-ui
   docker compose up -d platform-api web-ui
   ```

### Rollback

No data is destroyed by the migration (two new tables, nothing altered on
existing tables), so rollback is redeploying the previous images. If you
also need to reverse the migration: `alembic downgrade -1` drops
`workspace_cards` and `workspaces` — only safe if no workspace has been
created against the new build yet.

---

## 4. Verify live

- Create a workspace, pin a table/dashboard/document card to it — unchanged
  from the base feature.
- **Data-source picker gap fix**: open "Add card" on a workspace you own —
  confirm database and SaaS-connected data sources now appear in the list
  alongside tables/dashboards/documents, and that pinning one and reopening
  the workspace still shows it (round-trips through the backend correctly).
  A **file-uploaded** (CSV/Excel) data source should **not** appear in this
  list — that's intentional, not a regression; see §2.
- **Kebab menu, as the workspace owner**: rename a workspace inline (Enter
  to commit, Escape to cancel), publish it (confirm the "shared" indicator
  appears on the tab), unpublish it, then delete it — confirm the tab
  disappears and, if it was the active tab, another workspace (or the empty
  state, if none remain) becomes active.
- **As a non-owner** viewing a workspace shared to the project: confirm the
  kebab menu does **not** appear on any tab — these actions stay
  owner-only, matching the backend's existing enforcement.

---

## 5. Explicitly out of scope

- The original design review recommended a live Postgres dry-run of
  migration `0086` as a follow-up (the CLI-level check in this repo's
  sandbox hits an async-driver limitation unrelated to the migration
  itself, documented in the review). Recommend doing that dry-run as part
  of this deploy's staging pass if it hasn't already happened.
- No other gaps were identified against the Workspace feature in the
  review this increment closes out. If you find one during merge/deploy,
  report it per §1.2 rather than fixing it inline.
