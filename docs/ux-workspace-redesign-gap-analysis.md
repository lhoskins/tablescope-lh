# Tablescope Workspace UX Redesign — Review of Devin's Integration Plan

**Reviewed:** Devin plan "Tablescope — Workspace UX: Nav cards + Asset tree + Canvas + Right panel tabs" (session `muddy-plate`, created 2026-08-25)
**Source branch (prototype):** `UX-design-01` (HEAD `db08210` — 2026-08-27)
**Target branch (production):** `release/deploy-2026-08-07` (HEAD `7ed3469` — 2026-08-26)
**Reviewed against:** actual repo contents on both branches, not just the plan text.

## Confirmed design intent (sidebar + nav grid)

Worth stating plainly since it resolves several of the sections below at once: the nav card grid isn't new pages or new routes. It's the old sidebar's "Project" links (Project Insights, Project Actions, Goals, Scopes, Knowledge Graph — all existing pages) combined with the existing tab strip (Overview, Data Sources, Tables, Documents, Dashboards — also existing pages), all relocated into one row at the top and restyled as buttons. No code rewrites for those ten; it's link relocation, not new functionality. ("Workspace" and "APIs" are the two genuinely new/different cards — see §1 and §3.)

The reason this matters architecturally: it's specifically what frees the **left sidebar** to stop switching its link set per page and instead stay locked to one persistent thing — the project's asset tree (Tables/Documents/Data Sources) — all the time, on every project screen. Today the sidebar's content changes depending which page you're on (it shows the "Project" nav group); after this change it doesn't need to, because that navigation moved to the top row. That's the causal link between §2 (sidebar) and §3 (nav grid) below — they're one change, not two independent ones.

## Bottom line

The plan's five phases are the right shape and most of the file-level claims about production code check out. But there is one gap big enough to block Phase 3 as scoped, plus several smaller route/interaction ambiguities that Devin's document presents as settled ("read directly from the prototype") when the prototype actually leaves them open. I'd resolve the items below with product/design before Devin starts building, especially #1.

---

## 1. Blocking gap: "named workspaces" don't exist as a data model yet

This is the most consequential finding. The prototype's workspace tab strip — `Tokens_Input_Output | Costs by LLM Provider | Servers_Infrastructure | + | + New Workspace` — depicts **named, user-created canvases that each hold a curated set of multiple cards** (e.g. one workspace has both "OpenAI Export Invoice" and "Google Cloud Gemini" pinned into it at once, per the chat bubble: *"Workspace: Tokens_Input_Output — OpenAI Export Invoice (minimized) + Google Cloud Gemini are in scope."*).

What actually exists today (`workspace-tabs-storage.ts`, `use-workspace-tabs.ts`, `WorkspaceTabsBar`) is a completely different, much simpler thing: a flat, per-project, `localStorage`-only, MRU-capped-at-12 list of **individually opened single resources**. Each tab is one table/dashboard/document/data source; clicking a tab does `router.push(tab.href)` to that resource's own page. There is no concept of a name, no concept of a set of resources grouped together, and no persistence beyond one browser's localStorage.

Devin's plan treats this as a minor "enhancement" — *"The existing WorkspaceTabsBar is already rendered in ProjectShell. On the workspace page, add the + New Workspace button to the right end of that bar."* That undersells it substantially. Building the real thing requires:

- A new persisted shape: `Workspace { id, projectId, name, cards: [{ resourceType, resourceId, viewMode }], createdBy, ... }` — and a decision on whether this lives in `localStorage` (cheap, but not shareable/team-visible, and contradicts the Private/Shared surface the rest of this redesign leans on) or is a real backend entity (new API endpoints, migration, ownership/sharing rules).
- New create/rename/delete/switch flows for the `+ New Workspace` button and the tab strip itself — none of which exist against the current `WorkspaceTab` model.
- A way for the canvas to add/remove/reorder multiple cards within one workspace and persist that arrangement across reloads.
- Reconciling this with the *existing* `WorkspaceTabsBar` (single-resource MRU strip), which today already renders in `project-shell.tsx`'s `subHeader` on **every** project page as "recently opened items." Are there now two different tab strips (recently-opened-items vs. named-workspaces), or does one replace the other? The plan doesn't say, and the current component can't just be repurposed in place — its whole data model and click behavior (navigate to a dedicated page) is wrong for "switch the canvas to a different named set of cards without navigating away."

Recommend: scope this as its own spec/phase (data model + API + migration) before Phase 3 UI work starts, not as a file-count line item next to `workspace-canvas.tsx`.

### Resolved: sharing model, and a real precedent to build it on

Confirmed with the project owner: workspaces are **private by default**, with an explicit user-triggered **"publish to project"** action that makes a workspace visible to the rest of the project's members. That's a real backend entity, not client-only state — but it doesn't need to be invented from scratch. `platform-api` already has this exact pattern for `project_asset` (uploaded documents): a `visibility` column (`"private" | "shared_project"`), an `owner_user_id`, and a read-access check in `project_assets.py`:

```python
def _check_asset_read_access(asset: ProjectAsset, context: RequestContext) -> None:
    """... a document with visibility="private" is readable only by its [owner] ..."""
    if asset.visibility == "private" and asset.owner_user_id != context.user_id:
        ...
```

A `Workspace` table (`id`, `project_id`, `owner_user_id`, `name`, `visibility`, `cards: [{resourceType, resourceId, viewMode}]`, `created_at`, `updated_at`) following the same `visibility`/`owner_user_id`/access-check shape is a reasonable, low-risk model — point Devin at `project_asset.py` / `project_assets.py` as the pattern to replicate rather than designing sharing semantics from zero.

One gap even in that precedent, though: `project_asset`'s visibility is set once, at upload, and there's no endpoint that changes it afterward. "Publish" is an explicit *post-creation* mutation (private → shared, after the workspace already exists with cards in it) — that specific endpoint (`PATCH /workspaces/{id}` or a dedicated `/publish` action) doesn't exist yet anywhere in the codebase and will need to be built new, even though the underlying visibility model it writes to can copy the existing pattern. Confirmed: publishing is reversible — a user can un-publish a workspace back to private. The mental model driving this: every project member has their own private workspace by default (their "desk" to work in), and publishing is a personal choice about whether to show *your own* work to the rest of the project. So the access rule follows directly from that — this isn't a project-level permission (e.g. gated by a "can manage project" role); it's gated by **ownership of that specific workspace**. Only the user who created a given workspace can publish or un-publish it. The endpoint needs to support both directions (`private → shared_project` and back), with the access check simply `workspace.owner_user_id == context.user_id` — the same ownership check `project_asset` already uses for private-visibility reads, just applied to the write/publish path instead.

---

## 2. Sidebar: several concrete implementation gaps beyond "swap the ternary"

**Current code is simpler than Phase 1's description implies.** `sidebar.tsx` doesn't have two `NavGroupBlock`s to reconcile — it has one: `const groups = mode === "project" && project ? projectNavGroups(...) : homeNavGroups(user)`. So "remove the second NavGroupBlock for projectNavGroups" isn't quite accurate; it's just flipping which function feeds the single `groups.map(...)` loop. Minor, but worth correcting so whoever implements doesn't go looking for a second block that isn't there.

**The old "Other Projects" flat section goes away entirely — confirmed.** Today's sidebar has a separate "Other Projects" block below the main nav (`otherProjects.map(...)`, with a "+ New project" link). That's being removed outright, not restyled: every project the user can see — current and otherwise — now lists inside the single PRIVATE/SHARED tree, so a second, separate "other projects" list would just be a duplicate. That simplifies the component surface (one list to build, not two), but doesn't remove the underlying data gap: `useProjectShell()` still computes `otherProjects = all.filter(p => p.id !== projectId).slice(0, 6)` — and that cap now needs to come out (or be replaced with real pagination) regardless of which UI it feeds, since the PRIVATE/SHARED tree needs the *complete* project list, not a 6-item slice, to avoid silently dropping projects the same way the old section would have. The prototype's own demo data already has 8 total (1 private + 7 shared) — more than the cap allows.

**Private/Shared grouping is buildable but not free.** The good news: `ProjectSummary.visibility: "private" | "shared"` already exists on the data model, so grouping `otherProjects` (plus the current project) by visibility is realistic. But today's sidebar renders one flat "Other Projects" list with no grouping at all — the PRIVATE/SHARED headers, counts, and section collapse state are new UI, not a restyle of something existing.

**The two `+` affordances — resolved, and both reuse existing flows:**
- The `+` at the "Projects" row level creates a new project — the standard behavior already in the app today (the old sidebar's "+ New project" link), just relocated onto the row itself.
- The `+` on each asset-group header (Tables / Documents / Data Sources) inside the tree opens the app's existing add-a-table / upload-a-document / connect-a-source flow — the same functionality that already exists in Data Source Builder — just **scoped to the current project** when triggered from inside a project's tree. Concretely: `web-ui/app/projects/[id]/data-source-builder/page.tsx` already exists as a project-scoped variant of the builder (distinct from the global `/data-source-builder` — see §3), so this `+` most likely just links there rather than needing new backend scoping logic. Confirm against what that page currently does before assuming it's a drop-in target, but the plumbing to reuse is already in the repo.
- Empty state (a project with zero tables/documents/data sources): same answer — route to whatever the standard upload/connect flow already is elsewhere in the app, project-scoped the same way. Not a new flow to design.

**"Open in workspace" highlighting needs to be wired to existing state, not invented fresh.** In the prototype, two of the four asset-tree items carry an `open-in-ws` class (the ones currently pinned in the open workspace); the other two don't. The plan's spec ("Open/active items shown with brand-500 highlight") conflates "currently the active *page*" with "currently open as a tab/card somewhere" — two different states today. The second one should almost certainly reuse the same `WorkspaceTab[]` (or its named-workspace successor, see #1) that already drives `WorkspaceTabsBar`, so opening from the tree and opening from elsewhere stay in sync bidirectionally. Worth calling out explicitly so it isn't reimplemented as a third parallel piece of state.

**"Projects" click behavior — resolved: expand/collapse, standard disclosure pattern.** Clicking "Projects" toggles the tree open, matching the prototype's `<button class="proj-trigger">` behavior exactly. Today's `homeNavGroups` "projects" item is currently a plain `<Link href="/projects">` instead — that needs to change from a navigation link to a disclosure toggle as part of Phase 1.

**The prototype itself is inconsistent across screens — treat screens 1–4 as canonical.** Screen 5 (Data Sources) ships a stripped-down sidebar with no Projects-tree, no PRIVATE/SHARED grouping, and no asset tree at all — just flat Home / Business Insight / Projects (link) / AI Assistant. That's very likely a prototyping shortcut (the designer didn't re-embed the full sidebar markup on that one screen) rather than an intentional "Data Sources hides the tree" rule, but it's worth a two-second confirmation with design rather than assuming.

---

## 3. Nav card grid — resolved: link relocation, "Workspace" is the only genuinely new button

**Confirmed: the nav card grid is the existing tab strip and existing sidebar links, relocated into one row and restyled as buttons.** `Overview | Data Sources | Tables | Documents | Dashboards` (today's `ProjectResourceTabs`) plus the old sidebar's "Project" group (Project Insights, Project Actions, Goals, Scopes, Knowledge Graph) account for eleven of the twelve cards, all pointing at routes that already exist today — no new pages, no new routing for those eleven. **`Workspace` is the only genuinely new button/page** (see §1). Two corrections to the prototype's own card list, confirmed directly:

- **APIs is dropped entirely** — not built, not included even as a disabled/coming-soon card. It just isn't one of the twelve.
- **"Insights & Actions" was a bad merge in the prototype — it splits back into the two links it came from:** "Project Insights" (existing route `/insight`) and "Project Actions" (existing route `/actions`), each its own card, matching the two separate items already in the old sidebar.

With those two corrections, all twelve cards map cleanly onto what exists today, confirmed by elimination — laying out Overview (a duplicate of the old sidebar's "Project Home," which is exactly why the current app has "two menu bars" pointing at the same page — see the screenshot in §2), Workspace (new), Tables/Documents/Dashboards/Data Sources (old tabs), Project Insights/Project Actions/Scopes/Knowledge Graphs (old sidebar), and Chats (below) accounts for eleven of the twelve old items with nothing left over — except **Goals**, which is the only old-sidebar item not otherwise placed. So **"Reference" = "Goals" (`/business-context`), renamed** — worth one quick confirm since it's inferred by elimination rather than stated outright, but it's the only slot left, so it's very likely right.

**"Chats" isn't a new page either — it's the existing global AI Assistant screen, pointed at a project.** The real chat UI already exists at `/ai` (`web-ui/app/ai/page.tsx` + `ConversationListPanel`/`ConversationRow`/`AssistantHeader`/`TurnBubbles`) — it just isn't scoped to one project today; it lists every conversation across every project in one flat list (the messy mixed IT/Supplier-Risk/Business-Insights list visible in the current UI). The fix is thin: point the project's Chats card at a route that renders those same existing components with the conversation-list query changed from `listConversations()` to `listConversations(projectId)` — the API already supports that exact filter (`GET /api/conversational-analytics/conversations?project_id=...`, already implemented in `conversational_analytics_conversations.py`), it's just never been called with a project id from a project-scoped screen. New-conversation creation there should default `project_id` to the current project. One real follow-on, separate from the button itself: the global `/ai` page needs to stop showing everything mixed together once project-level Chats exists — outside a project, AI Assistant should scope to "the higher level" per the product direction. The backend has no "project_id IS NULL only" filter today (omitting `project_id` returns unfiltered, not unscoped-only), so this needs either a small backend addition or a client-side filter on the `ConversationSummary.project_id` field each summary already carries — the latter needs no backend change.

One more thing worth flagging while we're here, unrelated to the mapping itself: three redirect-stub routes exist that aren't part of the 12-card list at all — `/projects/[id]/knowledge-graph`, `/metadata-catalog`, `/audit-log`, each just `redirect()`-ing to `/admin/settings/project-intelligence/[id]/...`. Nothing to do about these; just flagging so nobody "cleans them up" as orphaned by the nav changes — they still work fine as redirects regardless.

**Data Source Builder is explicitly not one of the twelve cards.** It stays outside the project tab/button set entirely — reachable the way it already is today (the old sidebar's separate "Tools" item), plus whatever page-specific shortcut a given page adds on its own (e.g. the one on the Data Sources page, per §4).

---

## 4. Topbar / Data Sources header — resolved

Initial read of the prototype suggested Data Sources might *swap out* Private/Shared + Members for `↻ Sync all` / `+ Connect Source`-style buttons. **Confirmed against the real app: it's additive, not a swap.** Production already renders Private/Shared + Members inside the `ProjectHeader` row (title + Active badge + "Shared project · N members · Updated ..."), not a separate sticky topbar the way the prototype draws it — and that row already has a `headerActions` slot for extra page-specific buttons. "Sync all" and "Data Source Builder" (a plain link to the existing `data-source-builder` page — no new logic) simply join that same row alongside Shared/Members via `headerActions`, exactly the mechanism `project-shell.tsx` already exposes. No new override plumbing needed here — this one's a non-issue once you're working from the real `ProjectHeader` component instead of the prototype's simplified single-topbar mockup.

---

## 5. Right panel (Chat/Info/Add Context) — resolved

**Confirmed scope model, and it's simpler than "a knowledge graph per workspace" — it isn't one.** Knowledge Graph is a separate, existing, project-wide feature (its own nav card, `/relationship-map`, about relationships across a whole project's data). What the workspace's Chat tab needs is much lighter: not a graph, just a **list**.

- **Chat tab default scope = every card currently pinned to the active workspace**, not just one. Confirmed directly: "everything within that workspace, it needs to scope its view to all those docs."
- **The AI Assistant is not walled off to the workspace** — it already has full project-level access today (per the existing docked panel's behavior), and a user can still ask it about anything else in the project. The workspace only narrows its *default* focus; it doesn't restrict what it's capable of answering.
- **Info tab behaves differently on purpose, and this is a separate, simpler thing:** it shows one item's details when a specific card is clicked — a single-item detail view, not the multi-item chat scope. That part of Phase 4 was already right in the plan and needs no change.

**The technical gap that's still real:** `WorkspaceAssistantPanel` currently grounds on exactly one resource at a time — `activeItem: WorkspaceTab | null`, sent to the backend as a single `active_resource_type` / `active_resource_id` pair via `submitCanonicalTurn`. Supporting "use all N pinned cards" needs that widened to a list (an array of `{type, id}` pairs, not a single pair) — a small backend contract change to `submitCanonicalTurn`/`ai_proxy`, plus the frontend passing the workspace's full card list instead of just `activeItem`. Straightforward once the `Workspace` data model exists (§1) — the card list it needs to send is exactly the same list the workspace itself already tracks, so there's no separate state to invent here, just read from the same source.

Separately, one small thing still worth a confirm: the panel defaults to **collapsed** (a 54px icon strip) on every project page today, only expanding on demand. Nothing in the prototype's four workspace screens shows a collapsed/icon-only state — the panel is always shown open there. Confirm whether that collapse behavior goes away specifically on the Workspace page (prototype implies always-open) or stays (current behavior).

The Info-tab and Add-Context-tab additions themselves (Phase 4) look straightforward and low-risk — the metadata the prototype's Info tab shows (source, origin, columns, row count, last run, SQL) is plausibly already available from existing `SavedQuery`/data-source types, as the plan states.

---

## 6. Data Sources filter tiles: the underlying `Filter` type is narrower than the plan assumes, and the prototype's own interaction model contradicts "compose independently"

`filter.tsx` today is `export type Filter = "all" | "archive";` — that's the *entire* union. There's no "database"/"file"/"saas" filter value anywhere in the current type system; `isDatabase()`/`isSaas()` exist as row-level predicates only, not as a filter dimension. Adding the four stat tiles is doable (the plan's approach — a separate `typeFilter` state alongside the existing `Filter` — is reasonable), but two things to check before building:

- **The prototype's own demo JS treats type and all/archive as one mutually exclusive selector, not two composable filters.** `setDsF(f)` — the single handler behind both the stat tiles and the All/Archive pills — deactivates the All/Archive pills whenever a type tile is clicked, and vice versa. That contradicts the plan's implied model of "typeFilter narrows the list independently of the existing all/archive filter" (which would let you view, say, archived File sources). Worth a quick confirm on the intended UX: mutually exclusive single selector (matches what's literally coded in the prototype) vs. two independently composable dimensions (matches the plan's prose).
- **There's already a reusable `StatBar` component** (`overview-screen/stat-bar.tsx`) with an `items` override prop that Phase 5 could extend rather than hand-rolling new stat-tile markup — worth pointing Devin at it for consistency. One caveat: `StatBar`'s items are `Link`-based (navigate on click), while the prototype's tiles are stateful toggle buttons (`onClick` sets active filter, no navigation) — so it needs a toggle-button variant, not verbatim reuse.

---

## 7. Small factual corrections

- Branches are `UX-design-01` (lowercase "design") and `release/deploy-2026-08-07` — not `Ux-Design-01` / `depoy-08-07-2026` as written in the request. Just so the PR/branch names match exactly when this gets handed to Devin.
- `web-ui/lib/ui/types.ts`'s `NavKey` union already has a comment flagging `project-knowledge-graph`, `project-metadata-catalog`, `project-reference-library`, `project-audit-log` as **"Deprecated project Intelligence nav keys — kept for redirect compatibility."** That's a useful confirmation that those four concepts were already migrated to `/admin/settings/project-intelligence/...` in an earlier pass — consistent with what the redirect-stub pages show, and consistent with §3's read that "Reference" (the nav card) is unrelated to `reference-library` (the redirect stub) — it's Goals, renamed.

---

## Suggested order of operations

1. Nav card grid (§3), Chats (§3), and the Data Sources header (§4) are fully resolved — link relocation against existing routes, no open product questions left there. `Workspace` (§1) is confirmed as the one genuinely new piece.
2. Spec the `Workspace` data model/API explicitly (owner, `visibility`, `cards[]`, publish/un-publish endpoint — see §1) and size it as its own phase before `workspace-canvas.tsx`/`workspace-card.tsx` get written against it.
3. Still open, lower-stakes: the sidebar's `otherProjects` cap of 6 (§2), the undefined `+ Add` / per-group `+` targets in the asset tree (§2), and whether the AI Assistant's grounding needs to support multiple resources per workspace turn (§5).
4. Everything else in Devin's plan (sidebar restructure, Info/Add Context tabs, filter tiles) is a reasonable shape and checks out against the real code.
