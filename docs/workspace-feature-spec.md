# Workspace Feature — Spec for Devin

This spec covers exactly one thing: the **Workspace** feature (named, multi-card canvases) referenced in Phase 3 of the original "Tablescope — Workspace UX" plan (session `muddy-plate`). It replaces that plan's treatment of Phase 3, which assumed the existing `WorkspaceTab` system already supported this — it doesn't (see rationale below). Everything else in the original five-phase plan (sidebar restructure, nav card grid, right-panel Info/Add Context tabs, Data Sources filter tiles) is covered separately in `docs/ux-workspace-redesign-gap-analysis.md`, already in this repo — read that first for the corrected version of those phases. This doc is additive to it, not a replacement.

---

## Prompt for Devin

> Implement the **Workspace** feature on top of `release/deploy-2026-08-07`, per this spec. A Workspace is a named, user-created canvas that holds an arbitrary number of tables/documents/dashboards/data sources pinned together (e.g. a workspace called "Tokens_Input_Output" holding two specific tables at once) — distinct from the existing `WorkspaceTab` system (`workspace-tabs-storage.ts`), which is a flat, single-resource, MRU-capped strip and does not model this. Before starting, read `docs/ux-workspace-redesign-gap-analysis.md` in this repo for the corrected version of the rest of the original plan (sidebar, nav grid, Chats page, Data Sources header) — this spec covers only the Workspace data model, its API, and its frontend/AI-grounding wiring.
>
> Build: (1) the `workspaces` + `workspace_cards` backend model and endpoints in §2–3 below, modeled on the existing `project_asset` visibility/ownership pattern (`platform-api/app/models/project_asset.py`, `platform-api/app/routes/project_assets.py`); (2) the workspace tab bar and canvas frontend wiring in §4; (3) the AI Assistant multi-resource grounding change in §5. Confirm the three open questions in §6 before finalizing card-edit permissions and the relationship to the existing `WorkspaceTabsBar` — everything else in this spec is settled and can be built as written.

---

## 1. What a Workspace is (confirmed)

- A **named** canvas (user picks the name — "Tokens_Input_Output" is just an example, not a fixed label).
- Holds **any number** of cards, each pointing at an existing table, document, dashboard, or data source (same four resource types `WorkspaceTab` already models: `table | dashboard | document | data_source`).
- **Private by default.** Visible only to the user who created it.
- **Owner can publish it** to make it visible to the rest of the project. **Owner can also un-publish it** back to private (confirmed reversible).
- Publish/un-publish is gated by **ownership of that specific workspace**, not a project-level role — every member has their own private workspaces ("their own desk"), and it's each person's call whether to show their own work, not something a project admin controls on their behalf.
- The AI Assistant's Chat tab, when a workspace is open, is grounded on **every card currently in that workspace** by default — not just the last-clicked one — while still retaining full project-level access if the user asks about something outside the workspace (see §5).

## 2. Data model

Model this on the existing `project_asset` pattern (`visibility` + `owner_user_id` + an access-check function) rather than inventing new sharing semantics — that pattern already exists and is already proven in this codebase.

```
workspaces
  id                  PK
  tenant_id           FK
  project_id          FK
  owner_user_id       FK (the creator — governs publish/un-publish and, pending §6, edit rights)
  name                string
  visibility           string  -- "private" | "shared_project"   (same two values as project_asset.visibility)
  created_at           timestamp
  updated_at           timestamp
  published_at         timestamp, nullable  -- set on publish, cleared on un-publish

workspace_cards
  id                  PK
  workspace_id        FK -> workspaces.id
  resource_type       string  -- "table" | "dashboard" | "document" | "data_source"  (matches WorkspaceResourceType)
  resource_id         string  -- same id shape WorkspaceTab.id already uses
  view_mode           string  -- "card" | "row" | "full"
  position            integer -- ordering within the canvas
  added_at            timestamp
```

Two tables rather than a JSON column on `workspaces` — makes ordering, adding, and removing individual cards straightforward without read-modify-write races on a blob column, and mirrors how `project_asset` rows are already modeled as first-class rows rather than embedded JSON.

## 3. API endpoints

New router, e.g. `platform-api/app/routes/workspaces.py`, prefixed `/projects/{project_id}/workspaces`, following the same access-check shape as `project_assets.py`:

- `POST /projects/{project_id}/workspaces` — create. Body: `{name, cards?: [{resource_type, resource_id}]}`. `visibility` always starts `"private"`, `owner_user_id` = caller.
- `GET /projects/{project_id}/workspaces` — list workspaces visible to the caller: their own (`private`, `owner_user_id == caller`) plus all `shared_project` ones for this project. This is the query that feeds the workspace tab bar (§4).
- `GET /projects/{project_id}/workspaces/{id}` — detail, including resolved card metadata (table name, doc title, etc. — same resolution the existing `WorkspaceTab` label/href already needs, just for a list instead of one item).
- `PATCH /projects/{project_id}/workspaces/{id}` — rename, add/remove/reorder cards, update a card's `view_mode`. Owner-only for now (see §6).
- `POST /projects/{project_id}/workspaces/{id}/publish` — sets `visibility = "shared_project"`, `published_at = now()`. Owner-only, checked the same way `_check_asset_read_access` checks ownership today.
- `POST /projects/{project_id}/workspaces/{id}/unpublish` — sets `visibility = "private"`, `published_at = null`. Owner-only.
- `DELETE /projects/{project_id}/workspaces/{id}` — owner-only.

Read access on `GET .../{id}` follows the exact same rule as `project_asset._check_asset_read_access`: `shared_project` readable by any project member; `private` readable only by `owner_user_id`.

## 4. Frontend wiring

- **Workspace tab bar** (the `Tokens_Input_Output | Costs by LLM Provider | Servers_Infrastructure | + | + New Workspace` strip): a new component on the Workspace page, backed by `GET .../workspaces`. `+ New Workspace` calls the create endpoint and switches to it. Clicking a tab switches the active workspace client-side — it does **not** navigate away, since all workspaces render on the same Workspace page.
- **Open question to resolve before building this:** does this new tab bar replace the existing `WorkspaceTabsBar` (the single-resource MRU strip already rendered in `project-shell.tsx`'s `subHeader` on every project page) — or do the two coexist as separate things (a general "recently opened items" strip everywhere, and this new named-workspace strip only on the Workspace page)? See §6.
- **Canvas** renders the active workspace's `cards`, each in its persisted `view_mode` (`card`/`row`/`full`), matching the prototype's per-card Card/Row/Full toggle — `PATCH` the card's `view_mode` on toggle.
- **Sidebar asset-tree "open in workspace" highlighting** (the `open-in-ws` styling on Tables/Documents items in the sidebar tree, from `docs/ux-workspace-redesign-gap-analysis.md` §2) should now reflect membership in the **active workspace's `cards`**, not the old single-resource tab strip — so opening an item from the tree adds it as a card to the current workspace, and the tree stays in sync with what's actually pinned.

## 5. AI Assistant grounding (multi-resource)

- `WorkspaceAssistantPanel`'s Chat tab, when a workspace is active, should send **all of that workspace's cards** as grounding context, not just a single `activeItem`. This means widening `submitCanonicalTurn`'s `active_resource_type`/`active_resource_id` (currently one pair) to accept a list of `{resource_type, resource_id}` pairs — a backend contract change in the conversational-analytics turn-submission path, mirrored on the frontend by passing the workspace's card list instead of a single `WorkspaceTab`.
- This is **not** a knowledge graph and doesn't need one — it's a scope list, not a relationship model. Knowledge Graph stays what it already is: a separate, existing, project-wide feature (its own nav card, `/relationship-map`).
- The assistant keeps its existing full project-level access — the workspace only narrows its *default* focus, it doesn't restrict what it can be asked about.
- The **Info tab** is unrelated to this and needs no change here — it already shows one clicked item's details at a time, which is correct and separate from the Chat tab's multi-item scope.

## 6. Open questions — confirm before finalizing

1. **Does the new named-workspace tab bar replace `WorkspaceTabsBar` entirely, or do they coexist?** (§4) If they coexist, decide where each shows — e.g. the MRU strip stays on non-Workspace pages, the named-workspace strip only appears on the Workspace page itself.
2. **Card-edit permissions on a `shared_project` workspace:** owner-only for renaming/adding/removing cards (matching the publish/un-publish rule), or can any project member with edit access modify a shared workspace's contents once it's published? The publish/un-publish rule itself is confirmed owner-only; this is specifically about editing a workspace's cards after it's shared.
3. **AI panel collapse behavior on the Workspace page:** stays collapsed-by-default like every other project page today, or defaults open on Workspace specifically (as every prototype screenshot shows it)? (Carried over from `docs/ux-workspace-redesign-gap-analysis.md` §5.)
