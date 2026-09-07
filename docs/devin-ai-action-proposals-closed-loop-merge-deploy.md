# Devin: merge + deploy — closed-loop AI action proposals

**Repository:** `lhoskins/tablescope-lh`
**Target branch:** `UX-design-03`
**Branch to merge:** `devin/merge-ai-action-proposals`
**Original feature branch:** `codex/ai-action-proposals-closed-loop` @ `e083aab1db58a9eec16700f6e9ac3dc18bc57a70`

## Read this first: merge `devin/merge-ai-action-proposals`, not the raw feature branch

The originally reported instructions assumed `git merge --no-ff origin/codex/ai-action-proposals-closed-loop` onto `UX-design-03` would be a clean merge. **It is not.** `UX-design-03` moved forward after this branch's base (`aa489a71`) to include a separately-shipped Project Actions change (Delete/Archive/Restore controls, merged as `b6700252`) that touches several of the same files this branch does. A direct merge produces real conflicts in 2 files (`use-project-actions-board.ts`, `project-actions-workspace.tsx`) that need hand resolution to keep both feature sets.

That resolution has already been done, tested, and — because the validation pass below found one real security bug and one real backend correctness bug in the feature itself — fixed, all on **`devin/merge-ai-action-proposals`**, which is:

```
aa489a71 (base)
└─ e083aab1  feat: add closed-loop AI action proposals          [original branch, unchanged]
└─ b6700252  Merge fix/project-actions-new-action-button (already on UX-design-03)
└─ d828bfb2  Merge closed-loop AI action proposals               [conflict resolution]
└─ 99b58cf7  fix: close reviewer self-assignment bypass and async serialization bug
```

**Merge `devin/merge-ai-action-proposals` into `UX-design-03` — it fast-forwards cleanly** (its second parent is the current `UX-design-03` tip):

```bash
git fetch origin
git checkout -b integrate-ai-action-proposals origin/UX-design-03
git merge --ff-only origin/devin/merge-ai-action-proposals
# push / open PR
```

If `UX-design-03` has moved again since this doc was written, `--ff-only` will fail — in that case do a normal merge and expect no conflicts (this branch's tip already contains everything `UX-design-03` had at merge time).

---

## What was validated

Two independent research passes read every changed file in full against `origin/codex/ai-action-proposals-closed-loop` (not a bare local branch) — one covering the backend (migration, models, routes, the new `ai_action_proposals.py` service, the workflow task hook), one covering the frontend (the new proposal/outcome panels, every status-enum touchpoint, the board wiring, the detail page). Their claims were then independently exercised by actually running both test suites in a worktree with real dependencies installed (not deferred to CI) and by hand-resolving and re-testing the merge conflict.

### Confirmed accurate, as originally reported

- Migration `0095` is the sole head off `0094`, purely additive (11 nullable columns, `SET NULL` FKs, sane indexes), no data-loss risk.
- Goal/KPI matching in `ai_action_proposals.py` and the CRUD-side `_validate_goal_metric_scope` both correctly reject cross-project references — confirmed by reading the actual queries, not just the plan's description.
- `tenant_id`/`project_id` scoping is consistent everywhere in the new service file.
- The grounded-outcome write-back (`outcome_snapshot`, `outcome_status`, `outcome_refreshed_at`) is a real, durable, queryable commit — not a log line — and correctly scoped.
- The new `rebuild_project_insight` worker task hook correctly has `tenant_id` in scope already (avoids the known project_id-only gap this codebase has elsewhere).
- Optimistic locking (`expected_version`) is checked on the new `/review` endpoint exactly like every other mutation in this file.
- Audit history for accept/reject/defer is real `AuditEvent` inserts, not just logging.
- Every status-badge/color/order/group lookup across the ~12 small UI files was updated consistently for the two new states; `is-overdue.tsx` correctly excludes `pending_review` from ever being flagged overdue.

### Found and fixed in this pass

1. **Security — reviewer self-assignment bypass (high severity).** `reviewer_user_id` was settable by the request body on both create and update, gated only by `Role.EDITOR` — which in this app's RBAC (`app/auth/rbac.py`) has the *same rank* as `Role.MEMBER`. Any active project member could set `reviewer_user_id` to themselves, then call `POST .../review` as the "designated reviewer" (`context.user_id in {action.reviewer_user_id, project.owner_id}`) and self-approve or self-reject their own AI proposal — completely bypassing the feature's core "project-owner or designated-reviewer" human-in-the-loop premise. **Fixed**: added `_require_can_assign_reviewer()` (`project_actions_shared.py`) — only the project owner or an admin may now set `reviewer_user_id`, at create or update. 3 new regression tests confirm a non-owner is 403'd on both paths and the legitimate owner path still works.
2. **Correctness — async serialization crash on 2 of the feature's own new code paths.** `create_action`, `update_action`, `review_action_proposal`, and `restore_action` all call `session.refresh(action, ["subtasks"])` immediately after `session.commit()`, then synchronously `ProjectActionOut.model_validate(action)`. Committing expires every plain column on the object; refreshing only the `subtasks` relationship left `updated_at` (and everything else) expired, and Pydantic's synchronous attribute read outside any `await` raised `MissingGreenlet: greenlet_spawn has not been called`. This was **not a merge artifact** — the pattern predates this branch — but this branch's own two new tests (`test_ai_proposal_requires_human_review_and_is_not_active`, `test_completed_action_waits_for_refreshed_insight_outcome`) are the first to actually exercise it, and both failed before the fix. **Fixed**: an unrestricted `session.refresh(action)` added immediately before the `["subtasks"]`-scoped refresh at all four call sites.
3. **Frontend correctness.** `project-action-detail.tsx`'s "Edit & accept" flow chains a second API call (`review()`) inside `updateAction`'s `onSuccess`, with no try/catch. A rejected promise inside `onSuccess` is not routed to react-query's `onError` — so a failure there (stale version, wrong reviewer) produced no toast, no navigation, just a silent unhandled rejection. **Fixed**: wrapped in try/catch with a proper error toast.
4. Two of my own existing regression test suites (from the earlier, separately-merged Delete/Archive/Restore work) needed fixture updates after the merge — new `reviewAction` mutation and new required `ProjectActionListItem` fields (`source_surface`, `reviewer_user_id`, etc.) weren't in their mocks. No assertions were weakened, only mock shapes updated to match the new type.
5. One of this feature's own new tests (`action-proposal-panel.test.tsx`) had a fixture bug, not a component bug: the "KPI" field intentionally falls back to reusing the success-criterion's `name` when no distinct `metric` is supplied, and the test fixture didn't supply one — so `getByText("On-time delivery")` legitimately matched twice. Fixed by giving the fixture a distinct `metric` value.

### Found, not fixed — flag for follow-up, not a merge blocker

- **Proposal-creation dedup is in-memory/in-transaction only** (`ai_action_proposals.py`) — no unique constraint or lock backs it. Two overlapping refreshes for the same project (double-click, or a live request racing the background rebuild worker) can both pass the pre-insert dedup check and create duplicate proposals. Confirmed no unique index exists on `(project_id, source_insight_fingerprint)`. Recommend a follow-up: partial unique index (excluding NULLs) plus `ON CONFLICT DO NOTHING` or an advisory lock keyed on `project_id`.
- **Editing a pending proposal's content is not owner/reviewer-gated.** The generic `update_action` (still `Role.EDITOR`/`MEMBER`) can change `title`, `description`, `priority`, `goal_id`, etc. on a `pending_review` action — only the `status` field itself is blocked from changing outside the review flow. A non-reviewer project member can silently alter what the designated reviewer is about to approve. Not fixed here since it's a broader scope/design question (should *any* field edit on a pending proposal require reviewer-level authorization?) rather than a clear-cut bug; the reviewer-assignment bypass (item 1 above) was the concrete, unambiguous exploit path and is closed.
- **No stale-lock_version recovery in the UI after a review conflict** — if `/review` 409s, `detailMap[id]` is never invalidated, so retries keep hitting the same stale version until the page reloads.
- **`project-action-detail.tsx` has no Reject/Defer entry point at all** — only an Accept-via-`?review=1`-query-param hack and an unconditional Archive button. A reviewer who lands on a pending proposal's detail page directly (bookmark, deep link) can edit-and-save or archive it, but can't reject or defer from that screen.
- **Dead, duplicated import boilerplate** copy-pasted into ~12 small files (`status-order.tsx`, `is-overdue.tsx`, etc.) — harmless to the build, but worth a cleanup pass.
- Test coverage for the auth-bypass scenario (item 1) and the cross-project goal/KPI 422 rejection path was previously absent; the auth-bypass gap is now closed by this pass's 3 new tests, the goal/KPI-rejection gap remains untested.

None of the "not fixed" items above are merge blockers on their own — they're pre-existing-shaped gaps (missing tests, missing UI affordances, a race that needs load to trigger) rather than something this merge newly breaks. The reviewer self-assignment bypass (item 1, fixed) was the one item that made "project-owner/designated-reviewer authorization" not true as shipped, which is why it was fixed rather than just flagged.

---

## Testing performed

Run for real, in a worktree with actual dependencies installed — not deferred to CI.

| Suite | Result |
|---|---|
| `alembic heads` | Single head: `0095` |
| `pytest tests/test_project_actions.py tests/test_ai_action_proposals.py` | **18 passed** (15 original + 3 new reviewer-escalation regression tests) |
| Full `pytest` (platform-api) | **1945 passed**, 12 failed, 4 skipped. All 12 failures independently confirmed pre-existing on a clean `origin/UX-design-03` checkout in this same session (unrelated: visualization engine, percent-change summary, business-insight snapshot staleness, billing data-plane provisioning) — none touch any file this branch changes. |
| `tsc --noEmit` (web-ui) | Clean |
| `next lint` (scoped to changed files) | Clean — only the same pre-existing `max-lines` warning on `project-actions-workspace.tsx` already known from the earlier Delete/Archive/Restore round |
| Full `vitest run` (web-ui) | **610 passed**, 10 failed. All 10 are the same pre-existing, unrelated `intelligence-card.test.tsx` failures (`ChartSuggestionDialog` missing a `QueryClientProvider` in that test's own harness) confirmed earlier this session — not touched by this branch. |

No regressions from this merge or its fixes in either suite.

---

## Deploy

This branch **does** need a real deploy — new migration, new backend routes, new frontend code.

```bash
# 1. Pull the merged UX-design-03 onto the deploy host.

# 2. Rebuild the affected services.
docker compose build platform-api platform-api-worker web-ui

# 3. Apply the migration.
cd platform-api
alembic upgrade head   # expect: 0095 (head)
cd ..

# 4. Restart.
docker compose up -d platform-api platform-api-worker web-ui
docker compose ps
```

`platform-api-worker` must be rebuilt/restarted too — `app/tasks/workflows.py`'s `rebuild_project_insight` task is what triggers `sync_ai_action_proposals` after a background insight refresh.

---

## Post-deployment validation

1. Refresh a Business Insight and a Project Insight that contain a recommended action.
2. Confirm one deduplicated action appears under **Pending review**.
3. Expand it and verify source insight, success criterion/KPI, target, steps, reviewer, and duplicate check all render.
4. **New**: as a project member who is *not* the owner and not the assigned reviewer, confirm `POST .../review` (and setting `reviewer_user_id` on create/update) is rejected with 403.
5. As the actual owner, Accept it and confirm it moves to **Not started**.
6. Complete the action and confirm the result says it's awaiting an Insight refresh.
7. Refresh Business and Project Insight again.
8. Confirm the completed action shows the updated insight card as its grounded result.
9. Verify rejected proposals remain visible and audited.
10. Confirm the pre-existing Delete/Archive/Restore controls (from the separately-merged branch) still work correctly on ordinary (non-proposal) actions after this merge.

---

## On the GitHub token

The request to "revoke the GitHub token pasted into chat and create a replacement" can't be carried out from here: no token value appears anywhere in the message this session received, and this session has no capability to manage GitHub personal-access-token security settings (the GitHub tools available are repository-scoped, not account-credential-scoped). If a real token was pasted into any chat, revoke it directly at **github.com → Settings → Developer settings → Personal access tokens**, and rotate any place it was configured (CI secrets, deploy scripts, etc.) — this needs to happen outside this session regardless of what this doc says.

## Report back

Confirm the fast-forward merge lands cleanly, `alembic upgrade head` reaches `0095`, and both full test suites still show only the same pre-existing, unrelated failures listed above (nothing new). Flag explicitly if the dedup-race or edit-not-gated items (see "Found, not fixed" above) should be scheduled as their own follow-up work.
