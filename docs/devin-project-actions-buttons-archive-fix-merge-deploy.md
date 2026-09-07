# Devin: merge + deploy — Project Actions "New action" fix + Delete/Archive/Restore buttons

**Repository:** `lhoskins/tablescope-lh`
**Target branch:** `UX-design-03`
**Branch:** `fix/project-actions-new-action-button`
**Base:** `b1e71fc5892ec5c69f030d1ec58acd57ea15f456` (confirmed to be the current tip of `origin/UX-design-03` — this branch fast-forwards cleanly, no merge conflicts possible)

## This needs a real deploy, not just a merge

Every file touched is under `web-ui/` — no backend, no migration, no Terraform. This is a plain frontend fix + feature, but unlike a documentation-only merge it **does change what ships to the browser**, so `web-ui` needs a rebuild and restart after merging. See "Deploy" below.

## What changed and why

Two related fixes to `/projects/{id}/actions`, from separate user-reported issues in the same session:

### 1. "New action" button was unresponsive (commit `e1971063`)

**Bug:** When a project has zero non-archived actions matching the current view — the exact state right after archiving a project's only action — the board rendered a "No actions match the current filters" placeholder instead of the normal grouped board. The toolbar's "New action" button only updates state that the grouped board consumes (which group shows its inline add-title row); with the placeholder showing, that board never mounted, so clicking the button silently did nothing.

**Fix:** `web-ui/components/tablescope/project-actions/project-actions-workspace.tsx` now falls through to the grouped board whenever an add is in progress, instead of unconditionally showing the empty-state placeholder. The grouped board already handled an in-progress add against a zero-item group correctly — it just never got the chance to render. Timeline view is intentionally left on the old behavior since it has no inline-add UI of its own to fall through to.

### 2. No way to permanently delete an action (commit `2248e834`)

**Gap:** The backend has always fully supported the action lifecycle — archive (soft delete), restore, and a permanent delete (`DELETE /projects/{id}/actions/{action_id}/permanent`) that requires the action be archived first — but the frontend only ever wired up archive/restore, and only inside a "⋮" row-menu dropdown. There was no "Delete" anywhere in the UI.

**Fix:**
- `web-ui/lib/api/project-actions.ts` — added `deletePermanently()` calling the existing backend endpoint.
- `web-ui/components/tablescope/project-actions/hooks/use-project-actions-board.ts` — added a `deleteAction` mutation mirroring the existing `archiveAction`/`restoreAction` pattern.
- `onDelete` threaded through `ActionRow` → `GroupSection`/`TimelineView` (both render the same shared `RowMenu`) down to the row menu itself.
- **`RowMenu`** now shows **Archive** for an active action, or **Restore + Delete** for an already-archived one (matching the backend's archive-before-delete requirement exactly). Delete is gated behind the app's existing generic `ConfirmDialog` since it's irreversible; Archive/Restore stay one-click, same as before.
- **`ProjectActionDetail`** (the single-action page) had the same gap — it unconditionally showed "Archive" even when viewing an already-archived action. It now switches between Archive and Restore/Delete based on `action.archived_at`, with the same delete confirmation.

## Testing performed

| Check | Result |
|---|---|
| `tsc --noEmit` | Clean, no errors |
| `next lint` (scoped to changed files) | Clean — only a pre-existing `max-lines` warning on `project-actions-workspace.tsx` (566 lines vs. the 500 soft limit), not introduced by this change |
| New regression tests | `project-actions-workspace.test.tsx` (1 test, reproduces the empty-state bug — confirmed to fail on the pre-fix code and pass on the fix), `row-menu.test.tsx` (5 tests: Archive-only when active, Restore+Delete when archived, delete requires confirmation, cancel doesn't delete, hidden entirely when `canManage` is false), `project-action-detail.test.tsx` (4 tests: same button-visibility and confirm-gating behavior on the detail page) |
| Full `vitest run` | **608 passed**, 10 failed, rest skipped/n-a. All 10 failures are in `components/tablescope/home/intelligence-card.test.tsx` (`ChartSuggestionDialog` missing a `QueryClientProvider` in that test's harness) — confirmed pre-existing and unrelated: no file outside `web-ui/components/tablescope/project-actions/` and `web-ui/lib/api/project-actions.ts` was touched by this branch, so this branch cannot be the cause. |

## Merge

```bash
git fetch origin
git checkout -b merge-project-actions-fixes origin/UX-design-03
git merge origin/fix/project-actions-new-action-button
# fast-forward, no conflicts expected -- merge-base is the current UX-design-03 tip
# push / open PR
```

## Deploy

1. **Merge and pull the merged branch onto the production host's checkout.**
2. **Rebuild and restart only `web-ui`** — no other service is affected:
   ```bash
   cd /home/ubuntu/tablescope
   sudo docker compose build web-ui
   sudo docker compose up -d web-ui
   sleep 6
   sudo docker compose restart nginx
   sudo docker compose ps --format "{{.Name}} {{.Status}}" | grep -E "web-ui|nginx"
   ```
   (This is exactly `deploy_webui.sh` at the repo root, already present on the host per the existing deploy convention.)
3. **No `alembic upgrade`, no `platform-api`/`platform-api-worker`/`teiid` rebuild needed** — the backend endpoints this feature calls (`archive`, `restore`, `.../permanent`) already exist and are unchanged.

## Verification after deploy

| Check | How |
|---|---|
| New action button works with zero actions | On a project with no active (non-archived) actions, open Board view and click "New action" — the inline add-title row must appear (not silently do nothing). |
| Archive → Delete flow | Archive an action, open its "⋮" menu — it should now show "Restore" and "Delete" (not "Archive"). Click Delete, confirm in the dialog, and verify the action disappears from the Archived view. |
| Restore flow | Archive an action, click "Restore" from the "⋮" menu — it should reappear in the active board. |
| Detail page parity | Open an archived action's detail page directly (`/projects/{id}/actions/{actionId}`) — header should show Restore + Delete, not Archive. |
| Permission gating | As a Viewer (non-editor/admin) role, confirm none of Archive/Restore/Delete appear anywhere. |

## Report back

Confirm the PR merges cleanly (it should fast-forward with zero conflicts) and that `web-ui` restarts healthy after the rebuild. If the four verification checks above pass, this closes both the original "New action button not responding" report and the "I need a delete archive and unarchive button" request from the same session.
