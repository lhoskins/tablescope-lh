# Review: "Port the YouTube Chat 3-pane layout into the Tablescope Workspace"

**Devin plan reviewed:** agent `devin-local`, session `scythe-paddleboat`, created 2026-09-05
**Checked against:** actual files in both repos, not just the plan text — `/Etlagent/etlagent-platform` (reference) and `vitruvity33/tablescope` on `UX-design-04` (HEAD `d66be1e8`, target)

## Headline: this plan is unusually well-grounded

Every line count, class name, function name, and constant the plan cites from the ETLAgent reference checks out exactly — `youtube-chat-layout.css` is 705 lines, `modules/resize.js` is 145 with `MIN_PANE_WIDTH = 240` at line 8, `modules/notes.js` is 647 with `COLLAPSE_THRESHOLD_CHARS = 320` at line 29 and the `yt-notes-${pid}` storage key, `modules/selection.js` is 174 with the mouseup/Escape/execCommand behavior described, and the pane flex ratios (`#pane1{flex:1.1}`, `#pane2{flex:1.4}`, `#pane3{flex:0.9}`) are exact. On the Tablescope side, `workspace-canvas.tsx` really is the `grid-cols-1/2/3` layout described, `workspace-card.tsx`'s body really is a one-line stub, `useAddableResources()` exists and does what's claimed, and `submitCanonicalTurn` already has an `active_resources[]` field wired all the way to the backend (`conversational_analytics_turns.py`). This isn't a plan built from guessing at file names — whoever wrote it actually read both codebases.

That said, five things need resolving before Devin starts building, and one number should be re-checked.

## 1. "Opts out of the docked assistant" — that switch doesn't exist yet

The plan says `workspace-screen.tsx` "opts out of the docked assistant," phrased as if it's flipping an existing option. It isn't one. `ProjectShell`'s `contextPanel` unconditionally renders `<WorkspaceAssistantPanel>` (`project-shell.tsx` line 121) — there's no prop anywhere to suppress it. Moving chat into pane 1 while the docked panel keeps rendering would mean two AI assistants competing for the same conversation on one page. This needs a new `ProjectShell` prop (e.g. `hideDockedAssistant`) threaded through to the `contextPanel` render — a small, real piece of scope that isn't listed in §5 (new components) or §8 (phasing). Worth adding explicitly so it doesn't get missed or improvised mid-implementation.

## 2. The "persisted per project" precedent is actually global

§5 says pane widths should be "persisted per project (following `workspace-assistant-storage.ts`)." Checked that file: `ASSISTANT_WIDTH_KEY` and `ASSISTANT_COLLAPSED_KEY` are plain string constants with no project id in them at all — one shared width/collapse state for the entire app, not even per-project, let alone per-workspace. So the cited precedent doesn't support "per project"; it supports "global." Given a single project can now hold several named workspaces (the whole point of the Workspace feature), there's a real design question hiding here: should pane widths be one global setting, one per project, or one per named workspace? Pick one deliberately — don't let it default to "per project" just because the plan said so, since the file it points to actually does something different.

## 3. Dashboards are addable but have no preview — a live dead-click

§2 is explicit: "No dashboards — they aren't part of this flow." But §5 reuses `useAddableResources()` unchanged for the "+ Add Files" picker, and that hook includes dashboards (`useProjectDashboards(...)` mapped to `resource_type: "dashboard"`, confirmed in `workspace-add-card.tsx`). Nothing in the plan filters dashboards out of that picker, and pane 2's preview switch (§2) only handles `document`/`table`/`data_source`. As written, a user can pin a dashboard card in pane 1 and then click it with no defined pane-2 behavior. Either strip `dashboard` out of `useAddableResources()`'s results when it's called from this new pane-1 strip, or give pane 2 an explicit "dashboards aren't previewable here — open it from the Dashboards tab" state. Either is fine; the plan just needs to pick one.

## 4. Notes are keyed per-project, but the data model is per-workspace

The snippet shape in §3 includes `workspaceId`, but the storage key proposed is `tablescope-workspace-notes-{projectId}` — no workspace id in the key. Since a project can hold multiple named private and shared workspaces, that means every workspace's notes pool into one flat array under one key. The plan never says whether the Notes pane filters that pool down to `workspaceId === active workspace` when rendering, or deliberately shows a project-wide notes list regardless of which workspace tab is open. This isn't something you can resolve by re-reading the reference app — ETLAgent has no multi-workspace concept, so there's no precedent to port for this one. It needs an explicit decision: scoped-per-workspace notes (filter on render) or one shared notes pool per project (in which case say so, and the `workspaceId` field is just provenance, not a filter key).

## 5. Uncommitted local state the plan doesn't account for

The actual working tree on `UX-design-04` right now has real changes beyond what the plan lists:

- `web-ui/lib/dev-mock/` (untracked) and a small hook-in to `web-ui/app/providers.tsx` (`installDevMocks()` called at module load) are already sitting there uncommitted. This matches §7's own note that "`mock-api.ts` is currently untracked in your worktree — committing it makes the sandbox reproducible" — so this isn't a surprise, but it means that commit needs to happen as part of (or just before) this PR, or the mock layer §7 depends on silently isn't actually in the branch.
- Separately, and *not* mentioned anywhere in the plan: `workspace-tab-bar.tsx` and its test already have an uncommitted, unrelated UX change sitting in the working tree (swapping the hover-only overflow-menu delete action for an always-visible × button). The plan's own file table lists this component as "Keep as-is" for this task — worth confirming that pending edit gets committed first so "keep as-is" means the current working state, rather than Devin's sandbox starting from a version that doesn't have it and the edit getting lost or conflicting later.

## 6. Minor — verify the test baseline fresh

§9 states "baseline 92 files / 558 tests." A plain file count on `UX-design-04` right now shows 107 `*.test.ts(x)` files, not 92. That gap is plausibly just drift since whenever that baseline was recorded, but given it's the number Devin will diff new tests against, worth re-running `npx vitest run` fresh right before starting rather than trusting the number as written.

## What's genuinely solid and needs no changes

The phasing in §8 (frame → pane 1 → pane 2 → pane 3 → mocks/tests) is the right build order — it makes drag/collapse/maximize provable before any pane-specific logic exists, which is exactly how you'd want to de-risk a layout port like this. The chat-grounding change in §6 is correctly scoped (reuse the existing endpoint and `active_resources[]` field verbatim, drop ETLAgent's external-LLM providers entirely rather than stubbing them) — confirmed that field already exists end-to-end on both sides, so this part really is as small as the plan says. And making `backLabel`/`onBack` optional on the three detail-view components (§2) is a correctly identified, necessary change — all three currently require both props, so embedding them in pane 2 without a back link would fail to compile as-is without this fix.
