# Devin-ready plan: 6 UI/navigation/knowledge-graph fixes

All findings below were verified directly against `origin/devin/r-echarts-e2e-validation`
(tip `f295cac`, which now includes PR #120). File paths and line references are
exact as of that commit. Screenshots referenced are the ones attached to the
request (IT project → Documents → Knowledge Graph on `it_assets`, and the
Sales → Data Sources `airtravel_CSV` table).

---

## 1. Data sources should archive-then-delete, like Tables

**Good news: the backend already fully implements this, mirroring the exact
Tables/SavedQuery pattern.** This is a frontend wiring gap for file/database
sources, plus a genuine backend gap for SaaS sources.

**Reference pattern (Tables / `SavedQuery`)** — `platform-api/app/routes/projects.py`:
- `POST /{project_id}/queries/{query_id}/archive` (line ~1780) — sets `is_archived`.
- `POST /{project_id}/queries/{query_id}/restore` (line ~1801).
- `_query_dependencies()` (line ~1824) — blocks delete while Scopes or
  Dashboard widgets reference the query.
- `DELETE /{project_id}/queries/{query_id}` (line ~1891) — 409 if not archived
  yet; 409 with the specific dependency list if any exist; only then hard-deletes.
- Frontend: `web-ui/components/tablescope/project/queries-screen.tsx` has an
  "Archive" filter tab (`ArchiveCard`), an `archiveMutation`, and a
  `deleteMutation` that calls `DELETE .../queries/{id}` from inside that
  archive view, with a native confirm ("Permanently delete... cannot be undone").

**Current state per data-source type:**

| Source type | Backend archive | Backend preflight+delete | Frontend UI |
|---|---|---|---|
| Uploaded file (`FileSourceMeta`) | ✅ `PATCH /datasources/{view_name}/archive` (`upload.py` ~L407) | ✅ `GET .../preflight-delete` (~L458) + `DELETE /datasources/{view_name}` (~L508), archived-first + `find_query_dependencies()` check | ❌ none |
| Database table (`DatabaseDataSource`) | ✅ `PATCH /{source_id}/archive` (`database_sources.py` ~L694) | ✅ `DELETE /{source_id}` (~L714), archived-first check | ❌ none |
| SaaS object | ❌ none | ❌ none (only credential-level `DELETE /credentials/{id}` exists) | ❌ none |

`web-ui/components/tablescope/project/data-sources-screen.tsx` currently only
filters archived sources OUT of the list (`.filter((s) => !s.archived)`, line
77) and supports the versioned "Update" flow — it has no Archive tab, no
Archive action, no Delete action at all.

### Steps
1. **Frontend**: add an "Archive" filter/tab to `data-sources-screen.tsx`,
   mirroring `queries-screen.tsx`'s `ArchiveCard` — list archived sources
   (call the same list endpoint with `include_archived=true`, already
   supported per `upload.py`'s listing logic), with Restore and Delete
   actions. From the active list, add an "Archive" row action calling
   `PATCH /datasources/{view_name}/archive` (file) or `PATCH
   /database-sources/{source_id}/archive` (database), branching on source type.
   Before showing the delete confirm, call the existing preflight endpoint
   (`GET /datasources/{view_name}/preflight-delete`) and render its
   `blockers`/`active_query_dependencies` the same way `queries-screen.tsx`
   surfaces dependency names, rather than a generic confirm dialog.
2. **Backend**: add the missing SaaS-source archive + delete pair in
   `saas_sources.py`, matching `database_sources.py`'s exact shape
   (`PATCH /{saas_source_id}/archive`, `DELETE /{saas_source_id}` with an
   archived-first + dependency check reusing `find_query_dependencies`).
3. Add tests mirroring the existing `test_upload_intake.py`/
   `test_file_source_versions.py` coverage for the new SaaS endpoints, plus
   a frontend test for the new Archive tab following
   `queries-screen.test.tsx`'s pattern if one exists.

---

## 2. Sidebar navigation is trapped behind a full-screen backdrop

**Root cause found.** Multiple detail views render as a full-viewport modal
with a click-outside-to-close backdrop that sits *on top of the sidebar*:

- `web-ui/components/tablescope/reference-library/detail-drawer.tsx` line 128:
  ```tsx
  <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
    <div className="absolute inset-0 bg-black/30" />
    <div ... onClick={(e) => e.stopPropagation()}>  {/* the actual drawer panel */}
  ```
- `web-ui/components/tablescope/project/detail-views.tsx` line 496 (inside
  `DataSourceResultView`, shared by the Data Sources and Tables detail/edit
  panels) uses the identical `fixed inset-0 z-50 ... onClick={onClose}`
  pattern.

Because the backdrop is `inset-0` (the *entire* viewport, not just the
content area to the right of the sidebar) and sits at `z-50`, a click on any
sidebar nav item while a drawer/detail view is open lands on this backdrop
`div` first. The backdrop's own `onClick={onClose}` fires (just closing the
drawer) instead of the sidebar's `<Link>` navigating — matching exactly the
reported behavior (have to close the panel first, then click again).

### Steps
1. In both files, scope the backdrop so it doesn't cover the sidebar: either
   (a) render the drawer/modal inside a container that starts after the
   sidebar's width (the app shell already has this width as a CSS variable/
   fixed value — reuse it, e.g. `fixed inset-y-0 right-0 left-[var(--sidebar-w)] z-50`
   instead of `inset-0`), or (b) simpler and more robust: don't use a
   viewport-covering backdrop for these two specific panels at all — render
   them as an in-content-area overlay confined to the `<AppShell>`'s main
   content region (a `relative` ancestor there, `absolute inset-0` on the
   panel), so the sidebar `<Link>`s are structurally outside the panel's DOM
   subtree and never receive its clicks.
2. Audit the other `fixed inset-0 z-50` occurrences found in this codebase
   (`new-project-dialog.tsx`, `data-source-update-dialog.tsx`,
   `ai-dashboard-suggestions-modal.tsx`, `project-row-actions.tsx`,
   `members-dialog.tsx`) — these are genuine modal dialogs (create/confirm
   actions), where blocking the whole screen including the sidebar is
   probably correct/intentional (you're mid-action, e.g. naming a new
   project). Only the two *browsing* panels above (drawer/detail view you
   navigate away from casually) need the fix; don't change true confirmation
   modals.
3. Add a regression test (Playwright/RTL) that opens a data source or table
   detail view, then clicks a sidebar item, and asserts navigation actually
   occurs.

---

## 3. Add a "Create Knowledge Graph" sidebar link under Scopes

`web-ui/components/tablescope/nav.ts`, `projectNavGroups()`: the "Project"
heading currently has Project Home, Project Insights, Project Actions, Goals,
Scopes (`${base}/scopes`) — no Knowledge Graph entry in this group. The only
existing KG entry is "Graph Lifecycle" (`${base}/knowledge-graph`) under the
separate "Intelligence" heading further down, which is where the existing
"Rebuild" button and build/version history already live
(`knowledge-graph-lifecycle-screen.tsx`, lines ~84-108).

### Steps
1. Add a new `NavItem` immediately after the `project-scopes` entry in the
   "Project" group:
   ```ts
   {
     key: "project-create-knowledge-graph",
     label: "Create Knowledge Graph",
     href: `${base}/knowledge-graph`,
     icon: IconTopologyStar3, // already imported, otherwise pick a distinct icon from IconBinaryTree
   },
   ```
   It points at the same route as "Graph Lifecycle" — that page already has
   the Rebuild action; this just makes the entry point discoverable right
   after Scopes, since Scopes define what feeds the graph.
2. Decide whether "Graph Lifecycle" under Intelligence should stay as a
   second link to the same page (for build-history/version browsing) or be
   removed now that there's a more prominent entry point — recommend keeping
   both, since "Graph Lifecycle" communicates "view history" and "Create
   Knowledge Graph" communicates "take the create/rebuild action," and
   removing it would break any deep links already in use.
3. Confirm `NavKey` type (in `lib/ui/types.ts`) is extended with the new key
   so `activeNav` highlighting works correctly on that route.

---

## 4. Quick Actions: "Create datasource" (no dropdown) + "Create Database connection"

**The core of this item is already built and tested — just not merged.**
Commit `8763e33` on branch `devin/quick-actions-through-data-source-builder`
(NOT an ancestor of `devin/r-echarts-e2e-validation` — confirmed via
`git merge-base --is-ancestor`) already did exactly this for "Add data
source": removed the `ConnectorsMenu` dropdown, routes straight to
`/data-source-builder?projectId={id}` (full flow: files, connectors, SaaS,
then project assignment), and added an `intent=upload` builder mode for
"Upload file" that hides the connector sections. It has its own tests
(`quick-actions-card.test.tsx`, `workspace.test.tsx`).

Today, without that merge, `quick-actions-card.tsx` still renders
`<ConnectorsMenu>` as an inline dropdown for "Add data source" — the
regression the request is describing.

### Steps
1. **Merge `devin/quick-actions-through-data-source-builder` into
   `devin/r-echarts-e2e-validation`.** Check for conflicts against anything
   that's landed on `r-echarts-e2e-validation` since this branch's base
   (`b0b6af5`) touching `quick-actions-card.tsx`, `overview-screen.tsx`, or
   `data-source-builder/workspace.tsx` — resolve by combining intent as done
   for the PR #120 merges earlier, not by blindly picking one side.
2. On top of that merge, apply the two refinements the request adds beyond
   what `8763e33` already does:
   - Rename the label from "Add data source" to "Create datasource" (both
     the button text and, if surfaced anywhere else, e.g. a tooltip).
   - Add a new action "Create Database connection". Rather than retrofitting
     the standalone `/database-connectors` page (which, per direct check,
     doesn't currently accept a `projectId` param at all — a new connection
     made from there wouldn't get pre-assigned to the originating project),
     extend the *same* Data Source Builder `intent` mechanism `8763e33`
     already introduced with a third mode: `intent=database`, showing only
     the "Connected Databases" section (hiding `FileAcquisitionPanel` and
     `ConnectedSaaS`), following the exact same pattern as the existing
     `intent === "upload"` branch in `workspace.tsx`. Route:
     `/data-source-builder?projectId={id}&intent=database`. This reuses the
     already-working project pre-selection instead of adding a second,
     parallel code path.
3. Confirm `ConnectorsMenu` and `UnifiedUploadDialog` (dropped from
   `quick-actions-card.tsx` by `8763e33`) are still used elsewhere (per that
   commit's own note — Data Sources page, Documents page) so nothing else
   breaks from the merge.

---

## 5. Knowledge Graph connector styles don't match the Relationship Evidence legend

**Likely the same class of bug as everything else found this session: the
correct logic already exists in the code, but what's live may not be running
it, or the cached graph predates the fix.** This needs live verification,
not a blind rewrite — the classification logic itself, read directly, looks
correct:

- `platform-api/app/services/knowledge_graph_builder.py`, `_classify_relationship()`
  (~L440-512) derives `relationshipStrength` and `connectorStyle` **together,
  from the same evidence signals, in one `_result()` call** — e.g.
  `"recommended"` always pairs with `"dashed"` (L498-499), `"inferred"` always
  pairs with `"dotted"` (L500-503). There's no separate/independent path that
  could set one without the other.
- The frontend (`knowledge-graph-canvas.tsx`, `connectorStroke()` ~L79-100)
  correctly renders whatever `connectorStyle` it's given: solid → no dash,
  `"dashed"` → `strokeDasharray="8 6"`, `"dotted"`/default → `"4 4"`.
- There's already a **version-gated cache-invalidation mechanism** for
  exactly this class of bug: `SNAPSHOT_PIPELINE_VERSION =
  "knowledge_graph_connector_styles_v3"` (L39) and, in
  `get_project_graph_data()` (~L1619-1635), a cached snapshot whose
  `pipelineVersion` doesn't match the current constant is automatically
  discarded and rebuilt on next read — no manual refresh needed. Git history
  shows this exact area (`connector-style policy`) has already been touched
  by at least two prior fix commits (`4d32b40`, `df29bb4`), consistent with
  it being a recurring pain point.
- The screenshots show the graph labeled **"Cached"** with a specific
  timestamp — i.e., the auto-invalidation path is the first thing to verify
  live, since a graph built under an older pipeline version, on a deployment
  that hasn't picked up `v3`, would show exactly the reported mismatch
  (Recommended rendering solid, Inferred rendering solid instead of dotted).

### Steps
1. **First, verify what's actually deployed** — same check as the 2FA and
   demo-refresh issues earlier this session: confirm the live app server's
   checkout includes the current `knowledge_graph_builder.py` (specifically
   that `SNAPSHOT_PIPELINE_VERSION` reads `"knowledge_graph_connector_styles_v3"`).
   If it's on an older commit, that alone likely explains the whole
   discrepancy — redeploy per the pattern in
   `docs/devin-2fa-enforcement-deploy-fix-validated-plan.md` (same repo,
   same branch) rather than touching this code.
2. If the deployed code is confirmed current and the mismatch still
   reproduces, force a hard rebuild for the affected project (`refresh=true`
   on the graph-fetch call, bypassing the cache entirely) and see if the
   freshly-built graph is correct. If it is, the bug is purely a stale
   snapshot that the pipeline-version check somehow didn't catch — check
   whether `snapshot.get("pipelineVersion")` is actually being persisted on
   write (`rebuild_project_graph_snapshot`, ~L1400-1420) for graphs built via
   whatever code path produced the one in the screenshot.
3. If a freshly-forced rebuild *still* shows the wrong styles, trace
   `build_node_centric_graph_from_snapshot()` specifically (the function that
   takes the cached snapshot and re-filters/re-centers it per request) to
   confirm it passes through each edge's already-classified
   `connectorStyle`/`relationshipStrength` unchanged rather than recomputing
   or dropping them — that would be the first genuine code bug found in this
   pipeline, as opposed to a staleness/deploy issue.

---

## 6. Knowledge Graph architecture review — supporting Business/Project Insights and document AI processing

This is a review-and-recommend task, not a specific bug fix — treat the
findings below as a starting brief, not a complete audit.

**What's already confirmed working well:**
- Business Insight and Project Insight refresh are genuinely
  background/async (arq jobs, not inline in a request — confirmed earlier
  this session): a successful KG build enqueues
  `refresh_business_insight_result` and `rebuild_project_insight` via
  `enqueue_*` helpers in `app/tasks/workflows.py`, gated by
  `business_insight_event_refresh_enabled`/`project_insight_event_rebuild_enabled`
  (both `True` by default as of `8014a2d`).
- There's already a version-gated snapshot-invalidation mechanism
  (`SNAPSHOT_PIPELINE_VERSION`) so classification-policy changes propagate
  without requiring every tenant to manually refresh.

**What stands out as worth Devin's attention in a real review:**
- `knowledge_graph_builder.py` is 1,653 lines and has had 14 commits on this
  branch alone, several explicitly titled "fix" for connector-style policy,
  canvas/arrow rendering, and snapshot persistence — a lot of churn
  concentrated in one file/module is itself a signal worth addressing
  structurally (e.g., splitting evidence-classification, snapshot
  persistence, and node-centric-view derivation into separately-testable
  units) rather than continuing to patch it in place.
- The KG build is the upstream trigger for *both* Business Insight refresh
  and Project Insight rebuild (via `mark_project_insight_stale` +
  `enqueue_rebuild_project_insight`/`enqueue_refresh_business_insight_result`
  in `workflows.py`) — meaning a slow or failed KG build silently starves
  both downstream features. Worth explicitly measuring: current KG build
  p50/p95 latency per project size, and whether build failures are
  surfaced anywhere the user would see them (vs. insights just staying
  stale with no visible error).
  Review whether Teiid schema introspection, AI evidence classification, and
  document-family resolution happen serially within one build or are
  parallelized where independent.
- Document profiling/AI processing (`reference_library_processing.py`,
  `document_processing_service.py`) writes `ai_metadata` that the KG then
  consumes as node properties — confirm there's no double-classification
  work happening (the KG's own evidence classifier re-deriving something the
  document profiler already computed) and that a document re-profile
  correctly marks any KG snapshots that reference it as stale, the same way
  a KG rebuild marks Project Insight stale.
- Given items 1-5 above surfaced multiple cases this session of "the fix is
  correct in the repo but wasn't deployed," treat that as a standing risk
  specifically for `SNAPSHOT_PIPELINE_VERSION`-gated logic: a bump to that
  constant without a corresponding deploy leaves the auto-invalidation
  silently doing nothing (old snapshots keep matching an old constant that
  itself doesn't reflect current code). Recommend adding this file's
  deployed-vs-repo commit check to whatever pre/post-deploy verification
  process comes out of the broader branch-consolidation work from earlier
  this session (PR #120).
