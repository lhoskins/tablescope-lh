# Home, Dashboards & Workspace — Wiring Assessment and Implementation Spec

**Branch:** `UX-design-04` · **Audited at:** `41dec05d` · **Date:** 2026-09-08

Audience: an engineer (or an AI coding agent) picking this up cold. Every item
below carries an exact `file:line`, what the UI promises, what actually happens,
and the change needed. Items are ordered by priority and tagged `P0`–`P3`.

---

## 0. Read this first: the sandbox is not unwired, it is mocked

The single most important finding is not a code defect.

`web-ui/.env.local:3`

```
NEXT_PUBLIC_MOCK_API=1
```

consumed at `web-ui/app/providers.tsx:13`, which installs
`web-ui/lib/dev-mock/mock-api.ts` — a ~1,100-line `window.fetch` monkey-patch
that intercepts `/api/*` and answers from in-memory arrays. In that mode:

| Surface | What the mock does |
|---|---|
| Workspaces | `mock-api.ts:90-116` — two hardcoded workspaces (`Cost review`, `Vendor spend`) with `cards: []`, mutated in memory, **lost on reload** |
| Chat | `mock-api.ts:1018-1022` — `GET /conversations` returns `[]`, so resume can never find a thread; `:1024-1062` answers with a canned `"Mock reply. Grounded on N workspace item(s)…"` |
| Dashboards | `mock-api.ts:775` returns `[]` — the dashboard resource type appears nowhere |
| Projects | `mock-api.ts:380-396` — exactly one project, `is_shared: false` |
| Unmatched routes | `mock-api.ts:1082`, `:1101` fall through to real `fetch` and fail |

**Not mocked at all** (so these surfaces are blank in the sandbox regardless of
code quality): `/api/home-pins`, `/api/projects/actions-home`,
`/api/users/preferences`, `/api/ai/home-intelligence/snapshot`,
`/api/projects/dashboards-all`, `/api/projects/documents-all`.

### Consequence

The Workspace backend is **complete and implemented** — not a stub anywhere:

| Frontend call | Endpoint | Backend | Status |
|---|---|---|---|
| `lib/api/workspaces.ts:55` | `GET /api/projects/{id}/workspaces` | `routes/workspaces.py:307` | Implemented |
| `:62` | `GET …/{wid}` | `workspaces.py:331` | Implemented (never called — §2 A3) |
| `:69` | `POST …/workspaces` | `workspaces.py:272` | Implemented |
| `:77` | `PATCH …/{wid}` | `workspaces.py:345` | Implemented |
| `:84` | `POST …/{wid}/publish` | `workspaces.py:399` | Implemented |
| `:91` | `POST …/{wid}/unpublish` | `workspaces.py:418` | Implemented |
| `:98` | `DELETE …/{wid}` | `workspaces.py:437` | Implemented |
| `lib/api/conversational-analytics.ts:244` | `POST /api/conversational-analytics/canonical-turns` | `conversational_analytics_turns.py:167` | Implemented |
| `:185` | `GET …/conversations?project_id=` | `conversational_analytics_conversations.py:349` | Implemented |
| `:199` | `GET …/conversations/{id}` | `conversational_analytics_conversations.py:461` | Implemented |

Model `platform-api/app/models/workspace.py`; migration
`alembic/versions/0086_workspaces.py` (verified single alembic head across 97
revisions); registered `main.py:121` and `:663`. Project reach and pinned-excerpt
quoting are genuinely built: `conversational_analytics/__init__.py:125`
(`_format_active_resource_prompt`), `:440` (`_find_unpinned_project_matches`),
`:397` (`_format_context_snippets`), assembled after `classify_turn` at `:676`.

**Zero `TODO` / `FIXME` / `HACK` / "not implemented" / "coming soon" markers**
exist anywhere under `components/tablescope/project/workspace/` or in
`routes/workspaces.py`. The only `placeholder` hits are legitimate
`<input placeholder=…>` attributes.

> ### ⚠️ Task 0 — do this before anything else
> Set `NEXT_PUBLIC_MOCK_API=0` (or delete `.env.local`), run a real
> `platform-api`, and re-evaluate. A large share of "nothing is wired" will
> disappear, and several items below will be re-prioritised once you can see
> real data.
>
> If you must keep the mock for design review, add mock routes for the six
> unmocked endpoints listed above, plus a second project with `is_shared: true`
> and a different `owner_id` — otherwise the Shared Projects and Dashboards work
> cannot be reviewed locally at all. Note the mock's single project makes
> `/data-source-builder` take its `list.length === 1` branch, so **the sandbox
> exercises the one redirect path that works and none of the three that don't**
> (§3.3).

---

## 1. What changed in commit `41dec05d`

Purely relocation plus one new screen. No component was rewritten.

| Change | File | Note |
|---|---|---|
| Nav gains a `Dashboards` entry | `components/tablescope/nav.ts:47-52` | Order is now Home / Dashboards / Business Insight / Projects / AI Assistant |
| Nav test updated | `components/tablescope/nav.test.ts:35-42` | Exact-array assertion; passes |
| Briefing moved off `/` | `app/dashboards/page.tsx` | Byte-identical to the old `app/page.tsx` except `activeNav="home"→"dashboards"` (`:52`) and `contextLabel="Personal Home"→"Dashboard"` (`:60`) |
| Old orphan preserved | `app/dashboards/all/page.tsx` | Verbatim copy of the old `/dashboards` table; only the function name (`:44`) and top-bar label (`:87`) differ |
| New Home | `app/page.tsx` | Getting-started screen, 4 starter tiles |
| New Shared Projects | `app/projects/shared/page.tsx` | Card grid |

`tsc --noEmit`, `eslint`, and the 4 relevant vitest files (18 tests) all pass.

### NavKey — no collision

`"dashboards"` was **already** in the `NavKey` union (`lib/ui/types.ts:36`),
declared but unused; the commit only added the nav *item*.
`"project-dashboards"` (`types.ts:59`) is a distinct literal in a different nav
group and shell mode. Matching is exact-string equality in
`sidebar/nav-group-block.tsx:46`. `app/admin/layout.tsx:23-38 activeNavFor` never
returns `"dashboards"`. No ambiguity.

The one behavioural wrinkle: **both** `/dashboards` and `/dashboards/all` pass
`activeNav="dashboards"`, so the sidebar highlights the briefing while you are on
the orphaned table.

---

## 2. Workspace — wiring gaps

### (A) Advertised but dead

**A1 · `P1` · The Actions pane's drawer ↗ button is a literal no-op.**
`components/tablescope/project/workspace/workspace-screen.tsx:481` —
`onSendChatToPane: () => undefined`. `workspace-panes.tsx:448` renders the ↗
button on `drawer === "chat" && pane.onSendChatToPane`, and an arrow function is
truthy, so the button renders with tooltip *"Send this conversation to the Chat
pane"* and does nothing. Documents (`:379`) and Preview (`:398`) do it properly
via `sendLastExchangeToChat`.
**Fix:** the Actions drawer's `WorkspaceChat` (`workspace-screen.tsx:473-480`) is
missing an `onTurnsChange` callback. Add
`onTurnsChange: (turns) => { drawerTurns.current.actions = turns }` and wire
`onSendChatToPane: () => sendLastExchangeToChat("Actions", drawerTurns.current.actions ?? [])`.
Local only; no endpoint needed.

**A2 · `P3` · Image snippets are renderable but uncapturable.**
`workspace-snippet-storage.ts:23-24` declares `image?: string`;
`workspace-snippet-list.tsx:157-161` renders `<img src={snippet.image}>`;
`use-workspace-chat.ts:125` filters images out of prompts. **No code path
anywhere sets `image`** — there is no `onPaste`/`clipboardData` handler in the
entire workspace directory. The only snippet producers are
`workspace-screen.tsx:284-310` (text only) and `:316-329`.
**Fix:** add a paste/drop handler on Chat and Notes reading
`clipboardData.files`, **or** delete the field and its render branch.

**A3 · `P3` · `getWorkspace()` is defined and never called.**
`lib/api/workspaces.ts:58-63`. The screen only uses `listWorkspaces`
(`workspace-screen.tsx:132`). Means there is **no single-workspace refresh
path** — if a teammate publishes or edits, you only see it on a full remount.

**A4 · `P3` · `useWorkspaceChat` exports two unused values.**
`use-workspace-chat.ts:149-154` (`clear`) and `:93`/`:156` (`groundable`).
Neither consumer destructures them (`workspace-chat.tsx:49`,
`workspace-actions-pane.tsx:64`). So there is no "clear conversation" affordance
despite the hook providing one, and the `groundable` count that would let the UI
warn *"3 of 5 cards can't be grounded"* is computed and thrown away.

**A5 · `P3` · `WorkspaceChat`'s `emptyHint` prop is never supplied.**
`workspace-chat.tsx:25,38,88` — declared, defaulted to `<GroundingHint>`, and no
call site passes it (four instantiations at `workspace-screen.tsx:368,387,413,473`).

**A6 · `P1` · Dashboards are pinnable but have no preview and no drag source.**
`workspace-preview-pane.tsx:75-88` returns a placeholder: *"can't be previewed in
a pane yet. Open it from the Dashboards screen."* Meanwhile
`workspace-add-card.tsx:42-46` offers every dashboard in "+ Add card", and the
backend resolves dashboard labels (`workspaces.py:35`) and grounds on them
(`workspace_context.py:96-110`). A user can pin a dashboard, see a card, click
it, and hit a dead end. Additionally `sidebar/projects-tree.tsx:196-255` builds
only Tables/Documents/Data Sources groups — **dashboards can never be dragged
in**, only added from the dropdown.
**Fix:** render the existing
`components/tablescope/project/detail-views/dashboard-detail-view.tsx` in the
preview pane's `dashboard` branch, and add a Dashboards `AssetGroup` to
`ProjectAssetTree`.

**A7 · `P2` · `WorkspaceCardInfo` has no branch for `dashboard` or `data_source`.**
`workspace-card-info.tsx:60` → *"No details for this type yet."* for two of the
four supported types, while the Info drawer button still renders for them
(`workspace-panes.tsx:383`, `pane.info` is always supplied).

### (B) Works, but not persisted / wrong source of truth

**B1 · `P0` · `ProjectsTree` still highlights from the old localStorage MRU.**
This is the gap `ux-design/workspace-reference/navigation.md` already records —
**confirmed still true**, with exact lines:

- `components/tablescope/sidebar/projects-tree.tsx:23` —
  `import { loadWorkspaceTabs } from "@/components/tablescope/project/workspace/workspace-tabs-storage";`
- `:168` — `const [openTabKeys, setOpenTabKeys] = useState<Set<string>>(new Set());`
- `:170-173` — `useEffect(() => { const tabs = loadWorkspaceTabs(projectId); setOpenTabKeys(new Set(tabs.map((t) => \`${t.type}:${t.id}\`))); }, [projectId]);`
- passed down at `:215`, `:231`, `:254`, `:321`, `:324`, `:394`, `:425`
- consumed at `:357` — `openTabKeys.has(item.key) ? "font-medium text-brand-500" : …`

`loadWorkspaceTabs` reads `localStorage` (`workspace-tabs-storage.ts:36`),
written only by `use-workspace-tabs.ts:29,59`, used only by
`workspace-tabs-bar.tsx` — the MRU strip that `WorkspaceScreen` **explicitly
disables** (`workspace-screen.tsx:489`, `showResourceTabs={false}`). So on the
Workspace page the highlight source is a store nothing on that page writes to. A
card pinned into the active workspace is never highlighted in the sidebar.

Two wrinkles the existing doc does **not** record:

1. The effect at `:170` depends only on `[projectId]`, so even the MRU
   highlighting is read **once on mount** — no `storage` event listener, no
   re-read on navigation within a project.
2. The key shapes already agree (`${type}:${id}` vs `${resource_type}:${resource_id}`),
   so this is a source swap, not a reshape.

**Fix:** the active workspace's `cards` live only in `WorkspaceScreen`'s local
state (`workspace-screen.tsx:84-85`). Lift it — either a small Zustand store
under `lib/stores/` holding `{projectId, activeWorkspaceId, cards}` written by
`WorkspaceScreen` and read by `ProjectAssetTree`, or have `ProjectAssetTree` call
`listWorkspaces(projectId)` itself plus a shared active-workspace-id value.
**No new endpoint required** — `GET /api/projects/{id}/workspaces` already
returns cards for every visible workspace.

**B2 · `P1` · Pinned Context (Chat + Notes snippets) is localStorage-only.**
`workspace-snippet-storage.ts:54` (read) / `:73` (write), key
`tablescope-workspace-{target}-snippets-{projectId}-{workspaceId}`. Called from
`workspace-screen.tsx:112-113, 307, 339, 425, 450`. A workspace is a server
object that can be **published to the project**, but its notes and pinned
excerpts never leave the browser: another device, another browser, or a teammate
opening the published workspace sees an empty Notes pane. No table, no endpoint.
**Fix:** new table
`workspace_snippets (id, workspace_id FK CASCADE, target enum('chat','notes'), label, text, position, created_at, owner_user_id)`
plus `GET/POST/DELETE /api/projects/{id}/workspaces/{wid}/snippets` in
`routes/workspaces.py`, mirroring the card CRUD.
`SNIPPET_MAX_CHARS = 2000` (`workspace-snippet-storage.ts:31`) already matches
the backend's `ContextSnippet` ceiling, so `String(2000)` is the right column.

**B3 · `P2` · Draft Actions are localStorage-only, with no promotion path.**
`workspace-actions-storage.ts:36` / `:52`, key
`tablescope-workspace-actions-{projectId}-{workspaceId}`; used at
`workspace-actions-pane.tsx:74,79`. The file header (`:7-9`) calls this
deliberate. But `lib/api/project-actions.ts` and
`platform-api/app/routes/project_actions_crud.py` both exist and are **never
imported** by anything under `components/tablescope/project/workspace/`. So the
"promote to the project action board" step the docs describe as not-yet-built has
**no UI entry point at all** — no button, no menu item, not even a disabled one.
**Fix:** a per-action "Promote" button calling `createProjectAction`.

**B4 · `P3` · Pane layout is per-project localStorage, not per-user server state.**
`workspace-pane-storage.ts:155` / `:182`, key
`tablescope:workspace-panes:{projectId}`, hydrated `use-pane-layout.ts:47-50`,
committed `:53-56`. A user's five-pane arrangement does not follow them to
another machine, and is shared across every workspace tab in the project. The
latter is documented as intended; the former is not stated anywhere.
**Fix if wanted:** `routes/user_preferences.py` already exists — store the
`PaneLayout` blob keyed `workspace_panes:{project_id}`.

**B5 · `P3` · Pinned-panel height is a global localStorage key.**
`workspace-snippet-list.tsx:23` / `:111`, key
`tablescope-pinned-height-{surface}`. Documented as intentional; listed for
completeness.

**B6 · `P3` · Pinned-context show/hide is not persisted.**
`workspace-screen.tsx:101-102` — `chatPinnedHidden` / `notesPinnedHidden` are
plain `useState`, reset on reload. Documented as intended.

**B7 · `P2` · Which workspace tab is active is not persisted.**
`workspace-screen.tsx:135` — `setActiveId((current) => current ?? list[0]?.id ?? null)`.
Every reload lands you on the **oldest** workspace (list ordered by `created_at`,
`workspaces.py:326`), regardless of what you were working in.

### (C) Partially wired / edge cases missing

**C1 · `P0` · Chat resume swallows every error silently.**
`use-workspace-chat.ts:80-83`:

```ts
} catch {
  // Nothing to resume -- start fresh rather than showing an error…
}
```

This covers both `listConversations` and `getConversation`. A 401, a 500, or a
network failure is indistinguishable from *"you've never chatted here"* — the
Chat pane just opens empty. **Combined with the mock returning `[]` for
conversations, this is very likely what reads as "chat isn't wired."**
**Fix:** distinguish 404/empty-list (silent) from transport/5xx (surface via the
existing `error` state, already rendered at `workspace-chat.tsx:116-123`).

**C2 · `P1` · "Suggest actions" fails silently when the reply isn't a list.**
`workspace-actions-pane.tsx:118-130`. `parseSuggestedActions` (`:24-41`) keeps
only lines matching `/^([-*•]|\d+[.)])\s+/`. If the model replies in prose,
`suggestions.length === 0`, nothing is appended, `context` is not cleared
(`:125`), and no message is shown. The button returns to "Suggest actions" and
the user has no idea whether anything happened.
**Fix:** when `turns` grew but `suggestions.length === 0`, show *"The assistant
didn't reply with a list — try rephrasing"* in the existing `role="alert"` slot
at `:237-241`.

**C3 · `P0` · The error banner is stranded in one pane and never clears.**
`workspace-screen.tsx:87` declares `error`; written by six handlers (`:138`,
`:163`, `:181`, `:224`, `:236`, `:248`, `:270`) but rendered in exactly one
place — passed to `WorkspaceFilesPane` at `:359`, shown at
`workspace-files-pane.tsx:81-88`. Two consequences:

- **(a)** If the Documents pane is hidden via the Pane Views bar (legal —
  `use-pane-layout.ts` only refuses to hide the *last* pane), a failed
  publish/rename/delete produces **no visible feedback whatsoever**.
- **(b)** `setError(null)` appears only at `:155` (inside `onCreate`), so a stale
  error from a failed publish sits in the Documents pane until the user creates a
  new workspace.

**Fix:** move the banner to a page-level toast (`components/ui/toast.tsx`
exists), and clear on every successful mutation.

**C4 · `P1` · Role mismatch — the UI offers actions a VIEWER cannot perform.**
Backend gates: create `require_role(Role.EDITOR)` (`workspaces.py:277`), patch
`:351`, publish `:404`, unpublish `:423`, delete `:442`; only list `:311` and get
`:336` accept `Role.VIEWER`. The frontend gates on **ownership only** — `isOwner`
at `workspace-screen.tsx:151`, `canManage` at `workspace-tab-bar.tsx:63`. The
"+ New workspace" button (`workspace-tab-bar.tsx:71-80`) is shown to **everyone**;
there is no role check anywhere in the workspace directory. A VIEWER clicking it
gets a 403 surfaced as a raw message string via `friendlyError`
(`workspace-screen.tsx:46-52`).
**Fix:** read `getUserMeta()?.role`, hide/disable `+ New workspace` and card
editing for VIEWER.

**C5 · `P2` · Data-source cards break for tenant-level sources.**
`workspaces.py:180-183` resolves labels with `model.project_id == project_id`.
`DatabaseDataSource.project_id` is **nullable**
(`models/database_data_source.py:38`). A source with `project_id IS NULL` is
deliberately hidden from project listings (`projects_datasources.py:82-84`), so
it can't normally be pinned — but a card pinned *before* a source is detached, or
a source re-scoped to another project, resolves `label = None`. The UI renders
`workspace-card.tsx:147` → *"This resource is no longer available in the
project."* while the card is still clickable and still sent for grounding, where
`workspace_context.py:125-127` also returns `None`. No cleanup, no "remove broken
card" prompt.

**C6 · `P2` · Preview selection isn't reset when switching workspace tabs.**
`workspace-screen.tsx:95` (`selectedKey`) is never cleared in the `onSelect` path
of `WorkspaceTabBar` (`:504`, `setActiveId` directly). If the same resource is
pinned in two workspaces, switching tabs silently keeps the old selection
focused; if not, `selectedCard` (`:274-277`) resolves to `null` and Preview
reverts to its placeholder — which reads as a bug.

**C7 · `P1` · Card list is a full-array PATCH on every micro-interaction.**
`workspace-screen.tsx:169-185` fires `updateWorkspace` on **every** view-mode
toggle (`workspace-canvas.tsx:49-51`), every ←/→ move (`:57-64`), and every
removal (`:53-55`), with no debounce. Rapidly reordering five cards issues five
sequential PATCHes each replacing the full list; there is no request
cancellation, so an out-of-order response can clobber newer optimistic state (the
handler unconditionally does `setWorkspaces(… saved)` at `:178`).
**Fix:** debounce ~400ms, and drop responses whose request was superseded.

**C8 · `P2` · Optimistic card ids collide by construction.**
`workspace-screen.tsx:201` — `id: -Date.now()`. Two cards added within the same
millisecond share a key; `WorkspaceCanvas` keys on `card.id`
(`workspace-canvas.tsx:81`) and `remove`/`setViewMode`/`move` all match on
`c.id === card.id` (`:50`, `:54`, `:58`).
**Fix:** a monotonic counter or `crypto.randomUUID()`.

**C9 · `P2` · New workspaces are named by list length, so names collide.**
`workspace-screen.tsx:158` — `` `Workspace ${workspaces.length + 1}` ``. Delete
workspace 2 of 3, create a new one → two named "Workspace 3". The backend imposes
no uniqueness (`workspaces.py:74`).

**C10 · `P3` · `WorkspaceCard.added_at` is fetched and never displayed.**
Declared `lib/api/workspaces.ts:15`, returned by the backend
(`workspaces.py:49`, `:202`), rendered nowhere.

### (D) Cosmetic / polish

- **D1 · `P2` · "+ Add card" dropdown has no dismissal.**
  `workspace-add-card.tsx:86` — `open` toggles only via the trigger (`:96`) or an
  item pick (`:122`). No click-outside overlay (contrast `workspace-tab-bar.tsx:194-200`,
  which does it right), no Escape handler. Clicking elsewhere leaves a floating
  panel over the pane.
- **D2 · `P3` · Card body's subtitle is a static string.**
  `workspace-card.tsx:144-148` — every healthy card reads *"Open in Preview"*. No
  row count, no last-run time, despite `WorkspaceCardInfo` proving the data is
  available (`workspace-card-info.tsx:48-55`).
- **D3 · `P3` · `view_mode` is persisted but barely expressed.**
  `workspace-card.tsx:66-68` maps `card`/`row`/`full` to `col-span` + `min-h`
  only. A "full" card is a taller empty box; the mode round-trips to the server
  (`workspaces.py:385`) for no visible payoff.
- **D4 · `P3` · Collapsed-pane strips and Pane Views swatches both use
  `title.charAt(0)`.** `workspace-panes.tsx:148` and `:355`. Fine today
  (D/P/C/N/A), breaks for any future pane sharing a first letter.
- **D5 · `P3` · `WorkspaceTabBar` trailing group uses a magic `mr-20`.**
  `workspace-tab-bar.tsx:83`, to clear the pane row's scrollbar gutter.

---

## 3. Home (`/`) — wiring gaps

### 3.1 · `P0` · The "Shared with the team" checkbox is a backend no-op

`components/tablescope/project/new-project-dialog.tsx:86-93` renders the
checkbox; `:29-46` POSTs `{name, description, is_shared}` to `/api/projects`.

`platform-api/app/routes/projects_crud.py:87-93`:

```python
    project = Project(
        tenant_id=context.tenant_id,
        owner_id=context.user_id,
        name=payload.name,
        description=payload.description,
        type=payload.type,
        is_shared=False,          # <-- payload.is_shared ignored
    )
```

`ProjectCreate` **does** carry the field (`schemas/project.py:10-15`), and the
PUT path honours it (`projects_crud.py:155-156`). So a project created from the
Home tile is **always private** and can never appear on `/projects/shared` — the
two new tiles cannot be chained. No backend test covers this.

**Fix:** `projects_crud.py:93` → `is_shared=payload.is_shared`. Add a test in
`platform-api/tests/test_project_summaries.py` (or a new `test_projects_crud.py`).

### 3.2 · `P0` · `/data-source-builder` drops `intent` in 2 of 3 cases and shows a notice nobody renders

`app/page.tsx:154` links `/data-source-builder?intent=upload`; `:163`
`?intent=database`.

`app/data-source-builder/page.tsx:21-44` is the whole redirect:

```tsx
  if (requestedProjectId && accessibleIds.has(requestedProjectId)) {
    router.replace(`/projects/${requestedProjectId}/data-source-builder${query}`);
    return;
  }
  const list = projects ?? [];
  if (list.length === 1) {
    router.replace(`/projects/${list[0].id}/data-source-builder${query}`);
    return;
  }
  router.replace(
    `/projects${list.length === 0 ? "" : "?notice=Select a project to open Data Source Builder."}`,
  );
```

| projects | outcome | `intent` preserved? |
|---|---|---|
| **0** | bare `router.replace("/projects")` — empty list, **no message at all** | **No** |
| **1** | `/projects/{id}/data-source-builder?intent=upload` | Yes |
| **many** | `/projects?notice=Select a project…` | **No** |

There is **no project picker** — it is a bare redirect for both the 0 and many
cases. And **`?notice` is never read anywhere**: grepping `notice` across
`app/`, `components/`, `lib/` returns only the two producers
(`app/data-source-builder/page.tsx:41`, `app/database-connectors/page.tsx:37`)
and unrelated local state. `app/projects/page.tsx` reads `?new` (`:58-60`) but
**not** `?notice`. The promised explanation is invisible.

**Render during redirect:** `return null` (`:46`) inside
`<Suspense fallback={null}>` (`:51`). While `useProjectSummaries` is pending the
user sees a **completely blank white page** — no shell, no spinner. If
`/api/projects/summaries` *errors*, `isLoading` goes false with
`data === undefined` → `list = []` → the 0-project branch → the user is dumped on
`/projects` with no error surfaced.

**Fix:**
1. Render `?notice` on `app/projects/page.tsx` (a banner above the accordions).
2. Carry `intent` through both fallback branches:
   `/projects?notice=…&intent=upload`, and have the projects page pass it into
   the chosen project's builder link.
3. For the 0-project case, redirect to `/projects?new=1` (that deep link already
   opens `NewProjectDialog`, `app/projects/page.tsx:58-60`) with a notice
   explaining why.
4. Replace `return null` with a centered spinner inside `AppShell`.
5. Surface a real error state when the summaries query fails.

`app/database-connectors/page.tsx:20-41` is the same shim with the same two bugs —
fix both together.

### 3.3 · `P2` · Once `intent` arrives, tab selection is right but fragile

`app/projects/[id]/data-source-builder/page.tsx:13-25` maps
`sourceTab`/`intent` → `initialSourceTab` → `workspace.tsx:131-133`
`useState<SourceTab>(initialSourceTab ?? "upload")`. Covered by a passing test:
`components/tablescope/project/project-tool-routes.test.tsx:71-79`.

Two residual issues:

- **`?intent=upload` is a no-op** — `upload` is already the default
  (`workspace.tsx:132`). The Upload File and Data Sources tiles therefore differ
  only in that one of them actually does something.
- **`intent` outranks `sourceTab` on reload.** `workspace.tsx:135-140`
  `setSourceTab` writes `sourceTab` into the URL via `history.replaceState` but
  never clears `intent`. Hard-reloading `?intent=upload&sourceTab=database` hits
  the first ternary branch and lands on the wrong tab. `workspace.tsx:143-157`'s
  `popstate` handler reads **only** `sourceTab`, so Back to the original
  intent-only URL restores nothing.
  **Fix:** in the page, read `sourceTab` first and fall back to `intent` only
  when `sourceTab` is absent; in `setSourceTab`, `url.searchParams.delete("intent")`.

### 3.4 · `P1` · Home has no loading state

`app/page.tsx:109-114` destructures only `data`; no `isLoading` is read.

| Pending query | What renders |
|---|---|
| `useCurrentUser` | `FALLBACK_USER` (`:31-37`, `name: ""`) → `:201` renders the literal **`"Home"`**, then snaps to "Good morning, X" |
| `useProjectSummaries` | `counts={{projects: undefined}}` (`:173`) → sidebar badge blank, then pops in |
| `getPreferences` | `normalizeHomePersona(undefined)` → `"executive"` (`home-persona.ts:128-132`) → header renders **"Executive perspective…"**, then re-renders to the real persona |

Auth (`:117-119`) runs *after* paint, so a logged-out user briefly sees the full
shell — consistent with every other page; not new.

### 3.5 · Smaller Home defects

- **`P2` · `/help` does not exist.** `app/page.tsx:186` `router.push("/help")` →
  404. No `app/help` directory, no rewrite. Same dead button at
  `app/dashboards/page.tsx:72`, `app/business-insight/page.tsx:154`,
  `components/tablescope/project-insight/project-insight-screen.tsx:311`.
  Pre-existing, but the new Home ships it too.
- **`P2` · Leftover briefing chrome on a screen with no briefing.**
  `app/page.tsx:196-199` renders *"{profile.label} perspective · Personal
  business briefing"*, and `:111-114` fires a whole `GET /api/users/preferences`
  request **solely** to produce that label — on a page where the briefing has
  moved to `/dashboards`. Either drop the query and the line, or make the line a
  link to `/dashboards`.
- **`P3` · Double horizontal padding.** `AppShell` applies `px-5 py-5`
  (`app-shell.tsx:108`); `app/page.tsx:194` adds `px-6` → 44px of gutter vs 20px
  everywhere else. *(This was a deliberate design request — noted so it isn't
  "fixed" by accident.)*
- **`P3` · Raw `bg-white` instead of a token.** `app/page.tsx:81` — the rest of
  the codebase uses `bg-bg-primary`. Breaks under a dark/branded theme.
- **`P2` · Design deviation vs the prototype.**
  `prototype-home-empty.html:344-405` specifies a **2-step New Project wizard**
  (Step 1 name/description/**colour swatch picker**, Step 2 visibility as two
  radio cards). The implementation reuses the compact `NewProjectDialog` (name +
  description + checkbox). Note there is **no `color` column on `Project`** —
  accent is derived client-side from the id (`accentFor`, used at
  `app/projects/shared/page.tsx:59`), so the prototype's colour picker has no
  backing field. Decide: add the column, or drop the picker from the prototype.

---

## 4. Dashboards (`/dashboards`) — wiring gaps

Relocation is faithful (§1). Neither `PersonalizedHome` nor `HomePinsGrid` was
touched. All four endpoints exist and are mounted:

| Client | Endpoint | Backend | Mounted |
|---|---|---|---|
| `getHomeActionSummary` (`lib/api/home-actions.ts:30-32`) | `GET /api/projects/actions-home` | `projects_aggregates.py:81` | `main.py:612` |
| `getPreferences` | `GET /api/users/preferences` | `user_preferences.py:54` | `main.py:696` |
| `getIntelligenceSnapshot` | `GET /api/ai/home-intelligence/snapshot` | `home_intelligence_snapshot.py:207` | `main.py:678` |
| `useAllDocuments` (`use-shell-data.ts:162-168`) | `GET /api/projects/documents-all` | `projects_aggregates.py:515` | `main.py:612` |

### 4.1 · `P1` · The briefing is permanently empty until someone triggers a run elsewhere

`home_intelligence_snapshot.py:218-243`: with no persisted `IntelligenceSnapshot`
and no active run, it returns `{"snapshot": None}` — the whole page falls back to
placeholder copy (`personalized-home.tsx:178`, `:182`).

**Nothing on `/dashboards` calls `POST /api/ai/home-intelligence/refresh`.**
`refreshHomeIntelligence` exists in `lib/api/home-intelligence/` but is imported
by neither `personalized-home.tsx` nor `home-pins-grid.tsx`. A brand-new user's
Dashboards page is empty until they happen to visit Business Insight.

**Fix:** add a "Generate briefing" CTA to the empty state that calls
`refreshHomeIntelligence` and polls the snapshot.

### 4.2 · `P1` · Metric tiles are mislabelled — labels are persona-specific, values are not

`personalized-home.tsx:205-210`:

```tsx
  const metricValues = [
    projectCount,
    risks.length,
    opportunities.length,
    highlights.due_this_week,
  ];
```

rendered against `profile.metricLabels` at `:251-263`. But CFO's labels are
`["Projects monitored","Financial risks","Opportunities","Approvals due"]`
(`home-persona.ts:40`), CDO's are `"Data risks"/"Approvals due"` (`:52`), Business
Analyst's `"Open findings"/"Analyses due"` (`:82`).

Slot 1 is always the same generic severity-set count (no financial/data filter at
all), and slot 3 is always `actions-home.highlights.due_this_week` — i.e.
**"Approvals due" and "Analyses due" both literally render the count of project
actions due in the next 7 days.**

**Fix:** derive per-persona values, or make the labels honest.

Related: `highlights.needs_attention` and `highlights.recently_completed`
(`home-actions.ts:18-20`, computed server-side at `projects_aggregates.py:107+`)
are destructured at `:200-204` and **dropped**.

### 4.3 · What is real vs derived vs hardcoded

**Derived client-side, no server involvement:**

- Ranking / persona weighting — `home-persona.ts:159-181 rankHomeInsights`: pure
  client sort by `SEVERITY_WEIGHT` (`:92-102`, a hardcoded table) + `priorityScore`
  + substring keyword hits + focus-term hits. It **sorts, it never filters**.
- Risk / opportunity buckets — `personalized-home.tsx:89-90` `RISK_SEVERITIES` /
  `OPPORTUNITY_SEVERITIES`, hardcoded string sets, filtered at `:172-175`.
- Key developments merge — `home-persona.ts:216-250 buildHomeDevelopments`: top-3
  insights spliced with the single top-ranked document, client-side.
- Company-performance chart selection — `:160-167` + `home-persona.ts:187-192`:
  *"first ranked card that has a chart and isn't a `kpi_grid`."*

**Hardcoded / sample data:**

- `personalized-home.tsx:83-87` —
  `DEFAULT_FOCUS = ["Revenue vs backlog", "ITSM SLA risk", "Actions due this week"]`,
  shown as the user's focus when preferences are empty and **indistinguishable in
  the UI from real saved focus**.
- `home-persona.ts:29-90 PROFILES` — all ten personas' `purpose`, `keywords`,
  `metricLabels` are static copy.
- `personalized-home.tsx:254` `bg-[#DBE4F2]`, `:287` `bg-[#F1F1F2]`,
  `:302/:356/:376/:398` `bg-[#FCFCFC]` — five raw hex values bypassing the token
  system.

**Loading / error states are inconsistent:** `:260` shows `"—"` for slot 3 only
while `actionsLoading`; slots 0–2 render `0` during load (indistinguishable from
a real zero). The chart (`:292-293`) and developments (`:340-345`) do have
skeletons. **No error state anywhere** — a failed `getIntelligenceSnapshot`
renders as the "no insights yet" empty copy at `:296` and `:348`.

### 4.4 · `P1` · `HomePinsGrid` layout persistence is `lg`-only, and drags below `lg` visibly snap back

Core wiring is real: `GET /api/home-pins` (`lib/api/home-pins.ts:48-50` →
`home_pins.py:181`), `PATCH /api/home-pins/layout` (`:60-64` →
`home_pins.py:254-291`), delete/refresh (`:240`, `:368`, `:389`), all mounted
(`main.py:681`). Drag handle `.widget-drag-handle` (`lib/ui/grid-layout.ts:32`)
is present at `home-pins-grid/pin-card.tsx:83` and `:111`.

`home-pins-grid.tsx:264-270`:

```tsx
  const persistLayout = useCallback(
    (lg: LayoutItem[] | undefined) => {
      if (!lg || currentBreakpoint !== "lg") return;
      layoutMutation.mutate([...lg]);
    },
    [currentBreakpoint, layoutMutation],
  );
```

A drag at `md`/`sm`/`xs`/`xxs` doesn't merely fail to save — **it visibly snaps
back within a render or two.** Chain: `handleDragStop` (`:289-297`) calls
`updateOptimisticLayouts` (`:272-280`), which sets
`localLayouts = {...savedLayouts, md: [...]}` — so `localLayouts.lg` is present
and unchanged. `displayLayouts` (`:201-206`) accepts it. Then the reconcile
effect (`:233-253`) compares **only the `lg` arrays**, finds them identical, and
calls `setLocalLayouts(null)` — discarding the `md` edit. No error, no toast.

At the storage layer, `HomePin.layout` is a single JSON blob
`{x,y,w,h,position}` (`models/home_pin.py:58`, written `home_pins.py:278-285`).
There is **one** stored layout; `buildResponsiveHomeLayouts`
(`lib/ui/grid-layout.ts:194-233`) re-packs those coords into every breakpoint via
`packGridItems`. **Per-breakpoint layouts are architecturally impossible without
a schema change.**

**Fix (pick one):** (a) lock dragging below `lg` with a visible hint, or (b) add
a per-breakpoint layout column and persist each.

Same code path, more issues:

- **`P1` · `currentBreakpoint` can be wrong at mount.** `:114-116` initialises to
  `"lg"`; corrected only by `onBreakpointChange` (`:373-375`). If that callback
  doesn't fire on the initial measurement for a sub-1200px container, a first
  drag at `md` is persisted **as if it were `lg`**, corrupting the desktop
  layout. **Fix:** derive the breakpoint from `containerWidth` —
  `getColsForWidth`/`getBreakpointFromWidth` are already imported in
  `grid-layout.ts:1-7`.
- **`P3` · `position` hardcodes 12 columns.** `:183` `position: l.y * 12 + l.x` —
  correct only for `GRID_COLS.lg` (`grid-layout.ts:22`).
- **`P2` · Server sorts `position` lexicographically.** `home_pins.py:196`
  `.order_by(HomePin.layout["position"].as_string(), HomePin.id)` — a JSON→text
  cast, so `"10" < "2"` and `"100" < "12"`. Positions from `y*12+x` routinely
  exceed 9. Harmless visually (RGL positions by `x`/`y`) but wrong, and it will
  bite anything consuming pin order. **Fix:** cast to int, or store `position` in
  a real column.
- **`P2` · Failure UX is a bare string.** `:190-193` `onError` sets
  `"Could not save layout"` (`:348`), nulls the optimistic layout, no retry.
- **`P2` · No error state on the pins query.** `:48-51` — a failed
  `GET /api/home-pins` renders the "Your pinned workspace is ready" empty state
  (`:350-357`) as if the user simply has no pins.

**Layout note:** `home-pins-grid.tsx:328` uses `-mx-5 w-[calc(100%+2.5rem)]` to
cancel the shell's `px-5`. `app/dashboards/page.tsx:80` wraps in
`space-y-6 pb-8` with no extra padding, so this still lines up — the relocation
didn't break it.

---

## 5. `/dashboards/all` — the orphan

Verbatim copy of the old `/dashboards` (§1). Backend is real:
`useAllDashboards` (`use-shell-data.ts:154-160`) →
`GET /api/projects/dashboards-all` → `projects_aggregates.py:315-352`, mounted
`main.py:612`. Returns exactly the `HomeDashboardRow` shape the client declares
(`use-shell-data.ts:117-127`), with `ownerName` resolved via `_owner()`
(`projects_shared.py:128-141`) and `sharedBy` via `_shared_by()` (`:105-125`).
Delete → `dashboards_crud.py:301`. Exists.

- **`P1` · Confirmed orphaned.** Grepping `"/dashboards"` across `app/`,
  `components/`, `lib/` returns exactly one hit:
  `components/tablescope/nav.ts:50` — the *new* briefing page. **Nothing links to
  `/dashboards/all`.** It was orphaned before this commit and still is; the
  commit moved it without adding an entry point.
  **Decide:** add a "View all dashboards →" link from `/dashboards`, or delete
  the page.
- **`P2` · No error state.** `:48` destructures `{data, isLoading}` only. A
  failed fetch → `rows = []` → `:116-127` renders **"No dashboards yet."** — a
  backend outage presented as an empty workspace.
- **`P2` · No backend test:** `grep -rl "dashboards-all" platform-api/tests/`
  returns nothing.

**Sibling orphans, same family, worth resolving together:** `/data-sources`
(`useAllDataSources`) is linked only from
`data-source-builder/confirmation-modal.tsx:221`; `/documents` is linked from
**nowhere**. Same "cross-project rollup with no nav entry" problem, same three
endpoints (`dashboards-all` / `datasources-all` / `documents-all` —
`projects_aggregates.py:315/355/515`).

---

## 6. `/projects/shared` — the copy over-promises in two independent ways

### 6.1 · Confirmed: `visibility` is derived from `is_shared` and there is no owner field

`app/projects/shared/page.tsx:111-114`:

```tsx
  const shared = useMemo(
    () => (allProjects ?? []).filter((p) => p.visibility === "shared"),
    [allProjects],
  );
```

`lib/ui/use-shell-data.ts:101-115 mapProjectSummary` → `visibility: p.is_shared ? "shared" : "private"`.

`ProjectSummary` (`lib/ui/types.ts:7-19`) is
`id, name, visibility, updatedLabel, documentCount, queryCount, dashboardCount, actionCount?, aiStatus, accent?`.

**There is no `owner`, `ownerId`, `ownerName`, `sharedBy`, `createdBy`, `team`,
or `role` field — on the type or on the API response.** Contrast
`HomeDashboardRow` / `HomeDocumentRow` / `HomeDataSourceRow`
(`use-shell-data.ts:117-152`), which **all** carry `sharedBy` + `ownerId` +
`ownerName`. The project summary is the odd one out.

Backend schema (`platform-api/app/schemas/project.py:40-55`):

```python
class ProjectSummaryRead(BaseModel):
    """Project plus rollup counts and AI status for list/home cards."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_shared: bool
    updated_at: datetime
    document_count: int = 0
    query_count: int = 0
    dashboard_count: int = 0
    action_count: int = 0
    member_count: int = 0
    data_source_count: int = 0
    ai_status: str = "idle"
```

No owner. Note `ProjectRead` (`schemas/project.py:25-37`) **does** expose
`owner_id: int | None` — the summary schema is the only one missing it.

### 6.2 · `P0` · Problem 1 — it cannot exclude projects you own

`is_shared` means "this project is shared", not "shared *with me*". A project you
created and shared appears in your own Shared Projects list, labelled as a
teammate's.

### 6.3 · `P0` · Problem 2 — it is not org-wide at all

`platform-api/app/routes/projects_aggregates.py:214-228`:

```python
    member_sub = select(ProjectMember.project_id).where(
        ProjectMember.user_id == context.user_id,
        ProjectMember.is_active.is_(True),
    )
    project_query = (
        select(Project)
        .where(
            Project.tenant_id == context.tenant_id,
            or_(
                Project.owner_id == context.user_id,
                Project.id.in_(member_sub),
            ),
        )
```

`/summaries` returns **only projects you own or are an active member of**.
`projects_crud.py:35-63` applies the identical predicate, and `projects_crud.py:4-5`
documents the intent: *"Private projects (is_shared=False) are visible only to
the owner and assigned members. Shared projects are visible to all active
members."* — i.e. **members**, not the organization.

A colleague's org-shared project you were never added to will never appear here.
The Home tile says *"Access projects your teammates have shared with the
organization"* (`app/page.tsx:142-143`). **That access does not exist anywhere in
the API.** This one is *not* mentioned in the commit message.

### 6.4 · The DB already has everything needed — no migration required

`platform-api/app/models/project.py:15-66`:

```python
class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    ...
    owner: Mapped[User | None] = relationship(back_populates="owned_projects", foreign_keys=[owner_id])
    members: Mapped[list[ProjectMember]] = relationship(back_populates="project", cascade="all, delete-orphan")


class ProjectMember(Base):
    __tablename__ = "project_members"

    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(50), default="member", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
```

`owner_id`, `ProjectMember.role`, and `Project.type` (for the prototype's "Team"
column) all exist. **This is serialization work, not a schema change.**

### 6.5 · Exact change set for true "shared with me"

**Backend**

1. `schemas/project.py:40-55` — add to `ProjectSummaryRead`:
   `owner_id: int | None = None`, `owner_name: str = ""`,
   `type: str | None = None` (Team column + filter pills),
   `my_role: str = ""` (Access column).
2. `routes/projects_aggregates.py:200-312 list_project_summaries` — the only
   handler to change:
   - After `projects = list(await session.scalars(project_query))` (`:233`),
     build a name map via `_user_label` (`routes/projects_shared.py:51-56`,
     already imported-from in this module at `:27-33`) — or just call the
     existing `_home_context()` helper (`projects_shared.py:68-102`), which
     returns `(project_meta, user_names)` from the identical visibility query.
   - Fetch the caller's memberships once:
     `select(ProjectMember.project_id, ProjectMember.role).where(user_id == context.user_id, is_active)` → `{pid: role}`.
   - In the `ProjectSummaryRead(...)` call at `:297-311`, add
     `owner_id=p.owner_id`, `owner_name=names.get(p.owner_id, "—")`,
     `type=p.type`,
     `my_role=("owner" if p.owner_id == context.user_id else membership.get(p.id, ""))`.
3. **Decide the scope question.** If "Shared Projects" is to mean *org-wide*,
   `:220-227` must become
   `or_(owner_id == me, id.in_(member_sub), Project.is_shared.is_(True))` — that
   is a **visibility/authorization change**, and the same predicate is duplicated
   in `projects_crud.py:55-60` and `projects_shared.py:83-89`. **All three must
   move together or they will disagree.** If it is to mean
   *shared-with-me-among-my-projects*, leave the filter alone and fix the page
   copy instead.
4. Add `platform-api/tests/test_project_summaries.py` coverage: owner-vs-member
   sees the right `my_role` / `owner_name`.

**Frontend**

5. `lib/ui/use-shell-data.ts:28-40` — add
   `owner_id: number | null; owner_name: string; type: string | null; my_role: string`
   to `ProjectSummaryResponse`; map at `:101-115` to `ownerId`, `ownerName`,
   `team`, `myRole`.
6. `lib/ui/types.ts:7-19` — add
   `ownerId?: number | null; ownerName?: string; team?: string | null; myRole?: string`
   to `ProjectSummary`.
7. `app/projects/shared/page.tsx:111-114` —
   `filter(p => p.visibility === "shared" && p.ownerId !== identity?.user.id)`.
   `identity` is already in scope at `:102`; `CurrentUser.id` exists at
   `types.ts:96`.
8. Switch the card grid to the prototype's table (§6.6), or keep cards and add
   Owner / Access to them.
9. **Add the missing entry point.** `grep "projects/shared"` returns only
   `app/page.tsx:145` — the Home tile is the sole link. Add one from
   `app/projects/page.tsx` or a sidebar child under Projects.

### 6.6 · `P2` · Design deviation vs the prototype

`prototype-home-empty.html:437-462` specifies a **table**:
`Project | Team | Owner | Last updated | Access`, with `Access` values
`View` / `Edit` / **`Owner`** — so the prototype explicitly distinguishes
projects you own. Plus type filter pills (`All (7)`, `Finance`, `Engineering`,
`Operations`) and a `+ New Project` button in the top bar. Sub-header:
*"Projects shared with Simplicit, Inc that you have access to."*

The implementation ships a **card grid** with document/table/dashboard count
chips (`:79-95`) and none of Owner, Team, Access, the filter pills, or the New
Project button. Three of those four missing columns require §6.5's backend
change.

### 6.7 · Smaller defects

- **`P2` · No error state.** `:104` reads `{data, isLoading}`; a failed
  `/summaries` renders *"No projects have been shared with your organization
  yet."* (`:169-170`) — indistinguishable from success-with-zero-rows.
- **`P3` · `timeAgo` can render a dangling label.** `:77`
  `Updated {timeAgo(project.updatedLabel)}`; `lib/ui/format.ts:10-12` returns
  `""` for an unparseable date → the card shows a bare `"Updated "`.
- **`P3` · Dead `data-testid`.** `:64` `shared-project-${id}` — no test
  references it, nor `starter-*` from `app/page.tsx:89`/`:100`.

---

## 7. Test coverage

**Existing, passing, still valid** (4 files, 18 tests, all green):

| File | Covers |
|---|---|
| `components/tablescope/nav.test.ts` | Updated in this commit for the new key/order |
| `components/tablescope/sidebar.test.tsx` | 5 tests; Projects renders as a disclosure toggle, Home is a link (`:124`). Doesn't enumerate nav items, so the new entry neither broke nor is covered by it |
| `components/tablescope/project/project-tool-routes.test.tsx` | The only `?intent=` → tab test (`:71-79`, `intent=database`) — **project-scoped page only** |
| `components/tablescope/home/personalized-home.test.tsx` | Persona briefing + metrics + chart + mixed developments (`:137-153`); Home-settings save round-trip (`:155-175`) |
| `components/tablescope/data-source-builder/workspace.test.tsx:61-70` | `initialSourceTab` → correct panel |

**Missing entirely — no test file exists for any of the four changed surfaces:**

- `app/page.tsx` — nothing asserts the four tile destinations, the dialog
  opening, or the loading fallbacks.
- `app/dashboards/page.tsx`, `app/dashboards/all/page.tsx`,
  `app/projects/shared/page.tsx` — no tests.
- **`app/data-source-builder/page.tsx` — the 0/1/many redirect branching, the
  single thing most likely to regress, is untested.** Only the destination page
  is covered.
- `home-pins-grid.tsx` — the `lg`-only persistence and the optimistic-revert bug
  (§4.4) are uncovered.
- Backend: no test for `GET /api/projects/dashboards-all`; no test asserting
  `POST /api/projects` honours `is_shared`.

**Stale:** none. Nothing referenced `/` as the briefing route, so the relocation
broke no assertion. The single e2e spec
(`web-ui/e2e/data-source-builder-network-import.spec.ts`) is unrelated.

---

## 8. Doc maintenance

`ux-design/workspace-reference/navigation.md` is now **stale in one line**: it
says the sidebar renders *"Home, Business Insight, Projects, AI Assistant"* in
both modes. As of `41dec05d` that is *Home, Dashboards, Business Insight,
Projects, AI Assistant*. Update that sentence when you touch the file.

Everything else in `ux-design/workspace-reference/` was verified accurate against
the code during this audit, including the B1 gap it already records.

---

## 9. Suggested implementation order

Ordered so that each step makes the next one easier to judge.

| # | Item | Why here |
|---|---|---|
| **0** | Turn off `NEXT_PUBLIC_MOCK_API`, run real `platform-api` (§0) | **Prerequisite for judging everything else.** Re-triage after this. |
| **1** | §3.1 `is_shared` create bug | One line; unblocks testing the whole shared-projects flow |
| **2** | §2 C1 + C3 + C2 (error visibility) | Three small changes converting "silently broken" into "tells you what failed" — likely the second-largest contributor to the "nothing is wired" impression |
| **3** | §2 B1 (ProjectsTree source swap) | The one documented gap; cheap; needs an active-workspace store |
| **4** | §6.5 shared-with-me serialization + the scope decision | Unblocks the Shared Projects tile's actual promise |
| **5** | §3.2 data-source-builder redirect (picker + notice + intent) | Two of four Home tiles currently mislead for any multi-project user |
| **6** | §2 A1, A6, A7 (dead ↗, dashboard preview, info branches) | Visible dead ends |
| **7** | §4.1 briefing refresh CTA, §4.2 metric labels | Makes `/dashboards` non-empty and honest |
| **8** | §4.4 pin-grid breakpoint fixes | Data-corruption risk (`currentBreakpoint` at mount) |
| **9** | §2 B2 (server-persist snippets) | The only Workspace gap needing a new table; what makes a *published* workspace useful to a teammate |
| **10** | §2 C4 role gating, C7–C9 hardening | Correctness |
| **11** | §5 orphan decision, §3.5 `/help`, §7 tests | Cleanup |
| **12** | §2 B3 promote-to-actions, A2 image capture | Feature completions |

---

## 10. One-line summary of every `P0`

| # | File:line | Promised | Actual |
|---|---|---|---|
| §0 | `web-ui/.env.local:3` | A working app | `NEXT_PUBLIC_MOCK_API=1` serves hardcoded arrays; the real backend is complete |
| §3.1 | `platform-api/app/routes/projects_crud.py:93` | "Shared with the team" checkbox shares the project | `is_shared=False` hardcoded; payload ignored |
| §6.2/6.3 | `app/projects/shared/page.tsx:112` + `projects_aggregates.py:220-227` | "Projects your teammates shared with the organization" | Only projects you own or are a member of — and it includes your own |
| §3.2 | `app/data-source-builder/page.tsx:39-43` | Deep-link to the right builder tab | 0 or many projects → bare `/projects`, `intent` dropped, `?notice` never rendered |
| §2 B1 | `sidebar/projects-tree.tsx:170-173` | Sidebar highlights items pinned to the workspace | Reads the disabled localStorage MRU strip instead |
| §2 C1 | `use-workspace-chat.ts:80-83` | Chat resumes the workspace conversation | Bare `catch {}` — a 500 looks identical to "no history" |
| §2 C3 | `workspace-screen.tsx:87` + `:359` | Errors are surfaced | Banner lives in one pane that can be hidden, and never clears |
