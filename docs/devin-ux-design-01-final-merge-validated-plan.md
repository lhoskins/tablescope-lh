# Devin: merge + deploy — UX-design-01 (Workspace canvas), catch-up complete

Repository: `lhoskins/tablescope-lh`
**Branch to merge:** `UX-design-01`, now at `384a0d0`
**Into:** `release/deploy-2026-08-07`, unchanged at `8162756`
**Catch-up status:** `UX-design-01` is **0 commits behind** `release/deploy-2026-08-07`
— PR #202 (`Catch up UX-design-01 from release/deploy-2026-08-07`, merged) already
brought the 8 intervening release commits (through `8162756e`) into
`UX-design-01`. `release/deploy-2026-08-07` itself was not touched by that
PR and remains the protected backup/source — it still has none of this
branch's feature commits.
**Merge test:** clean, **no conflicts** (verified via throwaway-branch
`git merge --no-commit --no-ff` of `UX-design-01` against current
`release/deploy-2026-08-07` HEAD `8162756e`).

This supersedes `docs/devin-workspace-canvas-actions-validated-plan.md`
(written before the catch-up) — use this one. It covers the same feature;
the branch has simply been brought current against the release backup in
the interim, and this is now a straightforward, conflict-free merge.

---

## 1. Merge rules — read first

1. **Do not modify, rewrite, refactor, rename, or reformat the delivered
   code.** Merge as-is. If `release/deploy-2026-08-07` has moved again by
   the time you run this, resolve any conflict by preserving the delivered
   code exactly and adapting only the surrounding lines it touches — do not
   take the opportunity to "clean up" anything nearby.
2. Suspected bug in this delta → **report it in the PR description** with
   the exact line and reason. Do not silently change it.
3. `release/deploy-2026-08-07` is the protected backup/source branch — this
   merge goes **from** `UX-design-01` **into** it, not the reverse. Do not
   push directly to `release/deploy-2026-08-07` outside a reviewed PR.

```bash
git fetch origin
git checkout -b devin/ux-design-01-merge origin/release/deploy-2026-08-07
git merge origin/UX-design-01
```

Because the catch-up (PR #202) already reconciled the two branches, this
merge is expected to apply **cleanly with zero conflicts** — if you hit
one, `release/deploy-2026-08-07` has moved since this doc was written and
you're merging against a moving target; re-run the catch-up first rather
than resolving by hand.

---

## 2. What shipped — every commit in `UX-design-01` ahead of the release backup

| Commit | What it does |
|---|---|
| `a163c7fb` | Base Workspace feature: `workspaces` / `workspace_cards` tables (migration `0086_workspaces`, single head, revises `6aeba63f3092`), owner/visibility model (`private` \| `shared_project`, mirrors the existing `project_assets` pattern), full CRUD + publish/unpublish routes (`app/routes/workspaces.py`), and the canvas UI (tab bar, card grid, add-card picker, AI assistant panel scoped to the active workspace's cards). |
| `39a051d1` | Owner-gated kebab menu on each workspace tab — Rename (inline, commit on blur/Enter, cancel on Escape), Publish/Unpublish (toggles `visibility`), Delete (behind a confirm dialog, reassigns the active tab if the deleted one was active) — wired to the publish/unpublish/rename/delete endpoints `a163c7fb` shipped but that had no UI caller. Also: the "Add card" picker now offers database/SaaS data sources (`useProjectDataSources`, filtered via `isDatabase`/`isSaas`) alongside tables/dashboards/documents — file-backed sources are deliberately excluded (different id space, `FileSourceMeta.id` vs. `DatabaseDataSource.id`, and the backend resolves a `data_source` card against the latter). |
| `f39dc5de` | Docs only: the merge/deploy handoff this file supersedes. No app code. |
| `384a0d0c` | Catch-up merge commit (PR #202) — brings `release/deploy-2026-08-07` through `8162756e` into this branch. No feature changes; this is why the merge in §1 is now conflict-free. |

**34 files changed, 3609 insertions(+), 30 deletions(-)** in the feature
delta (`git diff --stat origin/release/deploy-2026-08-07 origin/UX-design-01`).
Touches only `platform-api` and `web-ui`.

### Validation (from the catch-up merge, PR #202, and confirmed against current `release/deploy-2026-08-07` HEAD)

| Check | Result |
|---|---|
| TypeScript typecheck | passed |
| Web UI tests | **545 passed** (90 files) |
| Platform API targeted suites (workspace CRUD/publish/rename/delete, owner enforcement, and adjacent API/security coverage carried by the catch-up) | **67 passed** |
| Alembic migration graph | **one head** (`0086_workspaces`) |
| Merge conflicts | **none** |

---

## 3. Deploy steps

1. Merge per §1.
2. **New Alembic migration**: `0086_workspaces` (revises `6aeba63f3092`).
   Confirm it is still the single head after merging:
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

- Create a workspace, pin a table/dashboard/document card to it.
- **Data-source picker**: open "Add card" on a workspace you own — database
  and SaaS-connected data sources appear alongside tables/dashboards/
  documents; pinning one and reopening the workspace round-trips correctly.
  A **file-uploaded** (CSV/Excel) data source should **not** appear — that's
  intentional (see §2), not a regression.
- **Kebab menu, as the workspace owner**: rename a workspace inline (Enter
  to commit, Escape to cancel), publish it (the "shared" indicator appears
  on the tab), unpublish it, then delete it — the tab disappears and, if it
  was active, another workspace (or the empty state) becomes active.
- **As a non-owner** viewing a workspace shared to the project: the kebab
  menu does **not** appear on any tab — these actions stay owner-only,
  matching the backend's existing enforcement.

---

## 5. Explicitly out of scope

- A live Postgres dry-run of migration `0086` beyond the CLI-level head
  check above — recommended as part of this deploy's staging pass if it
  hasn't already happened.
- No other gaps are known against the Workspace feature as of this merge.
  If you find one during merge/deploy, report it per §1.2 rather than
  fixing it inline.
