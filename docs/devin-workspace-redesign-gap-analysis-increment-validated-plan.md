# Devin: merge + deploy — Workspace redesign gap analysis, increment 1 (nav grid, sidebar tree, project Chats)

Repository: `lhoskins/tablescope-lh`
**Branch to merge:** `UX-design-02`, at `e62d3c1e`
**Base:** `release/deploy-2026-08-07`, unchanged at `7499717c`
**Merge test:** clean, **no conflicts** (verified via throwaway-branch
`git merge --no-commit --no-ff` of `UX-design-02` against current
`release/deploy-2026-08-07` HEAD).

This implements `docs/ux-workspace-redesign-gap-analysis.md` — a review of
Devin's original five-phase "Workspace UX: Nav cards + Asset tree + Canvas +
Right panel tabs" plan, filed after the Workspace feature itself
(`workspace-feature-spec.md`) shipped separately. That review flagged one
item ("named workspaces" as a data model) as blocking and resolved
everything else with concrete, checked-against-the-real-code answers. The
blocking item shipped earlier (`a163c7fb`/`39a051d1`, already in
`release/deploy-2026-08-07`). **This increment covers the rest of the
review's own suggested order of operations, items 1–2** — see §5 for what's
deliberately not in this increment.

---

## 1. Merge rules — read first

1. **Do not modify, rewrite, refactor, rename, or reformat the delivered
   code.** Merge as-is. If `release/deploy-2026-08-07` has moved again by
   the time you run this, resolve any conflict by preserving the delivered
   code exactly and adapting only the surrounding lines it touches.
2. Suspected bug in this delta → **report it in the PR description**, don't
   silently change it.
3. `release/deploy-2026-08-07` is the protected backup/source branch — this
   merge goes **from** `UX-design-02` **into** it, not the reverse.

```bash
git fetch origin
git checkout -b devin/workspace-redesign-gap-analysis origin/release/deploy-2026-08-07
git merge origin/UX-design-02
```

---

## 2. What shipped

**16 files changed, 980 insertions(+), 201 deletions(-)**, `web-ui` only —
no backend/API changes, no migration.

| Area | What changed |
|---|---|
| **Nav card grid** (gap analysis §3) | New `projectGridItems()` (`nav.ts`) and `<ProjectNavGrid>` component: one persistent row of 12 buttons — Overview, Workspace, Tables, Documents, Dashboards, Data Sources, Project Insights, Project Actions, Reference, Scopes, Knowledge Graph, Chats — on every project page. Replaces the old `ProjectResourceTabs` strip (deleted) and the sidebar's per-page "Project" link group. All routes already existed except Chats; "APIs" is dropped entirely and "Insights & Actions" splits back into its two source items, per the review's corrections. Wired into `project-shell.tsx` (unconditional — it no longer hides on the Workspace page, which is exactly the "two menu bars" duplication the review called out) and `overview-screen.tsx` (which renders its own header inline). |
| **Chats** (gap analysis §3) | New route `/projects/[id]/chats` + `ProjectChatsScreen`, on the **same** `conversational-analytics` API the global `/ai` page uses (`listConversations(projectId)`, `createConversation`, `submitTurn`, `renameConversation`, `deleteConversation`), reusing its `ConversationListPanel`/`TurnBubbles`/`UserBubble`/`MobileConversationDrawer` components. **Deliberately does not reuse** the pre-existing, unrouted `AiAssistantScreen` component (`ai-assistant-screen.tsx`) — that one talks to a separate, non-persisted `askProjectAi` endpoint with no conversation history, and wiring Chats to it would have reintroduced the exact "two disconnected chat pipelines" bug already fixed elsewhere in this codebase. `AiAssistantScreen` is untouched and still orphaned (no route renders it) — out of scope for this change; flagged in §5. |
| **Sidebar restructure** (gap analysis §2) | `sidebar.tsx`'s "Projects" row is now a disclosure toggle (`<ProjectsTree>`), not a `<Link>`. Expands into PRIVATE/SHARED project groups (by `ProjectSummary.visibility`), **uncapped** — the old `otherProjects.slice(0, 6)` in `use-project-shell.ts` is gone, so a tenant with 8+ projects (the review's own example) no longer silently drops any. The **current** project (when inside one) auto-expands a Tables/Documents/Data Sources asset subtree (via the existing `useProjectQueries`/`useProjectDocuments`/`useProjectDataSources` hooks), each item highlighted when it's pinned into the workspace tab strip — reading the same `WorkspaceTab[]` `WorkspaceTabsBar` already writes via `localStorage`, per the review's explicit instruction not to invent a third parallel piece of state. Each asset group carries a "+" linking to the existing project-scoped Data Source Builder (`/projects/{id}/data-source-builder`), and the "Projects" row itself carries a "+" to `/projects?new=1` — both reuse existing flows, no new add logic. The old flat "Other Projects" block is removed outright (not restyled), and the sidebar's core items (Home/Business Insight/AI Assistant) no longer swap per mode — they're now identical between home and project mode, which is the structural point of the review's §2 opening note. |
| **Data Sources header** (gap analysis §4) | **No change needed** — confirmed already implemented against the real `ProjectHeader`/`headerActions` mechanism before this review was even written. |

### Test status

- `tsc --noEmit`: clean
- `eslint .`: 0 errors (22 pre-existing `max-lines` warnings on unrelated files, unchanged by this branch)
- `next build`: succeeds, including the new `/projects/[id]/chats` route
- `vitest run`: **92 files / 552 tests passing**, including 4 new/rewritten test files covering the disclosure toggle, PRIVATE/SHARED grouping and uncapped list, the current-project asset subtree with open-in-workspace highlighting, the 12-card grid, and the project-scoped Chats screen (list scoping, conversation creation scoped to the project)

---

## 3. Deploy steps

1. Merge per §1.
2. No new environment variables, no new dependencies, no config changes, no migration.
3. Rebuild the one changed image:
   ```bash
   docker compose build web-ui
   docker compose up -d web-ui
   ```

### Rollback

Frontend-only, no migration — rollback is redeploying the previous `web-ui` image. Nothing to clear or re-run.

---

## 4. Verify live

- **Nav grid**: open any project page and confirm the 12-button row (Overview → Chats) appears at the top, including on the Workspace page (previously it had no resource-tab row at all). Clicking each button navigates to the matching existing page; there is no "APIs" button and "Project Insights"/"Project Actions" are separate buttons, not merged.
- **Chats**: open a project's Chats tab, start a conversation, refresh the page — the conversation persists and reappears in the left list (this is the real `conversational-analytics` pipeline, not an ephemeral chat). Confirm a conversation started here does **not** appear in the global `/ai` page's "all conversations" list mixed in with other projects' chats in a way that loses its project attribution — it should still carry this project's `project_id`.
- **Sidebar — disclosure**: "Projects" is a toggle, not a navigating link; clicking it expands/collapses without leaving the page.
- **Sidebar — grouping and cap**: on a tenant with more than 6 total projects, confirm every project appears somewhere in PRIVATE or SHARED — none silently missing.
- **Sidebar — asset subtree**: open a project with at least one table/document/data source pinned into its workspace (via the Workspace page's "Add card") — confirm that specific item is highlighted (brand color) in the sidebar's Tables/Documents/Data Sources subtree, and that this subtree only appears for the project you're currently inside, not for every project in the PRIVATE/SHARED lists.
- **Sidebar — add affordances**: the "+" on the Projects row goes to the new-project flow; the "+" on each asset group goes to that project's Data Source Builder.
- **Sidebar — no "Other Projects"**: confirm that block is gone entirely, in both home and project mode, and that Home/Business Insight/AI Assistant appear identically in both modes.

---

## 5. Explicitly out of scope for this increment

Per the gap analysis's own suggested order of operations, items 3–4 are lower-stakes and/or carry open product questions the review recommended confirming before building — not done here:

- **Right panel Info/Add-Context tabs** (§5 remainder). The Chat tab's multi-card grounding (the actual "technical gap" the review flagged — widening a single `active_resource` to a list) was **already implemented** in the earlier Workspace increment (`WorkspaceAssistantPanel`'s `active_resources` array, `workspace-assistant-panel.tsx`) and needed no work here. The Info tab (single-item detail view) and Add Context tab are net-new UI the review called "straightforward and low-risk" but were never built — left for a follow-up increment.
- **Data Sources filter tiles** (§6). The review flagged a real open UX question here — whether the four type tiles (Database/File/SaaS/count) should be mutually exclusive with the existing All/Archive pills (what the prototype's own demo JS actually does) or independently composable (what the plan's prose implies) — and recommended confirming with product before building either way. Deferred rather than guessed.
- **`AiAssistantScreen`** (`ai-assistant-screen.tsx`) remains dead code — a component with no route rendering it, built against the separate `askProjectAi` pipeline. Not touched by this increment since removing it wasn't part of the gap analysis; flagging it here so it isn't mistaken for something this increment forgot to wire up.
