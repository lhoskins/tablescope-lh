# Devin plan: Project Insight / Home / Dashboard UI fixes + project-scoping + email

Repository: `lhoskins/tablescope-lh`
Base branch: latest integrated branch containing
`feature/sprint-08-knowledge-graph-lifecycle` (NOT `main`).

Every file path and line below was verified against
`feature/sprint-08-knowledge-graph-lifecycle` (HEAD `359367f`). Keep this PR
focused on the items listed; do not refactor unrelated code. Run web-ui tsc +
lint + component tests and platform-api pytest + ruff before finishing.

---

## A. Project Insight page layout (image 1)

File: `web-ui/components/tablescope/project-insight/project-insight-screen.tsx`

1. **Expand the "Insights & Opportunities" panel by default.** It is currently
   collapsed (code comment at line 527: "Insights & Opportunities (collapsed by
   default)"; the collapsible is created at line 529). Change its initial
   open/expanded state to `true` (default-open). Do the same only for this
   panel — leave others as they are unless item A2 removes them.
2. **Remove the inline "Ask a question about this project…" box** (lines
   ~606–631, comment "Ask box — always visible between Questions and
   Recommendations", `placeholder="Ask a question about this project..."`).
   This duplicates the dedicated Ask TableScope screen; delete the block and any
   now-unused handlers/state it introduced.
3. **Remove the "Recommendations" collapsible** on this page (line ~633,
   `title="Recommendations"`). (Note there is a separate `title="Recommendations"`
   at line ~454 inside the Executive Summary block — that is the summary's
   Recommendations card and is NOT what the screenshot flags. Only remove the
   bottom collapsible panel at ~633, not the summary card at ~454.) Remove any
   data fetch/state that existed solely for that panel.

Verify the page still renders Risks/Trends/Opportunities, the Executive Summary
(with its four cards including its own Recommendations card), and the now
default-expanded Insights & Opportunities panel.

## B. Project Insight persistent warning banners (image 3)

Same file, lines ~367–384. Two warning banners currently sit permanently at the
top of the page:
- `data.aiAvailable === false` → "AI insight is temporarily unavailable —
  showing activity only. Try Refresh in a moment."
- the graph limited-mode disclosure → "Executive Insight is available in limited
  mode: the graph is stale or degraded. Results may be incomplete."

Requirement (user's words): "Remove these errors. If there is a problem then
issue a hard error, but should not stay permanently on the page."

Do NOT keep either as a permanent page banner. Instead:
- A **degraded-but-usable** state (`aiAvailable === false` while activity/cards
  still render, or `graphMode === "limited"`/`graphDisclosure` present) must not
  render a persistent banner. At most, show a small, **dismissible** inline note
  that the user can close, or fold the signal into the existing "Last updated"
  area — it must be dismissible and must not reappear on every render of the
  same loaded snapshot.
- A **genuine load/refresh failure** (the query errored, or an explicit Refresh
  attempt failed) should surface as a **transient toast/hard error** (use the
  app's existing toast mechanism — see how other screens report errors) that
  auto-dismisses, not a standing banner.
- Keep the existing transient "Updating project insight to reflect the latest
  data…" spinner (line ~377, `data.stale`) — that one is correct and
  self-clearing; do not touch it.

Confirm: on a normally-loaded project (cards present) neither yellow banner is
permanently visible; a forced backend failure shows a dismissible/transient
error, not a permanent one.

## C. Move "AI-Assisted File Upload" from Projects list → Project Overview (image 2)

- **Remove** the AI-Assisted File Upload dropzone from the top-level Projects
  list page: `web-ui/app/projects/page.tsx` (the "Add a data source" block that
  renders `ai-upload-dropzone.tsx`).
- **Add** the same dropzone to the Project Overview page
  (`web-ui/app/projects/[id]/page.tsx` / its overview screen), placed as the
  screenshot shows (below the tables/data-sources summary, in an "Add a data
  source" section). Reuse the existing
  `web-ui/components/tablescope/data-source-builder/ai-upload-dropzone.tsx`
  component — do not duplicate it.
- On the Project Overview page the upload has a known project context, so pass
  the current `projectId` through so the resulting data source is associated
  with THIS project (confirm the Data Source Builder flow accepts a
  pre-selected project; if the dropzone currently always routes into the
  builder for project assignment, keep that flow but pre-fill the project).
- Other places that render the dropzone (`web-ui/app/data-sources/page.tsx`,
  `web-ui/app/upload/page.tsx`) are out of scope — leave them.

## D. Resize handles: hide the markers, keep resize in all directions (images 4 & 5)

Both the Home pinned-widgets grid and the Dashboards grid use
`ResponsiveGridLayout` from `react-grid-layout@2.2.3` (a custom API — note
`dragConfig`/`resizeConfig`, not stock react-grid-layout):
- Home: `web-ui/components/tablescope/home/home-pins-grid.tsx:344` —
  `resizeConfig={{ enabled: true, handles: ["se", "e", "s"] }}`
- Dashboards: `web-ui/components/dashboard/DashboardViewer.tsx` (same component;
  find its `resizeConfig`).

Two changes on BOTH grids:
1. **Resize in all directions.** Expand `handles` from `["se","e","s"]` to all
   eight: `["s","w","e","n","sw","nw","se","ne"]` (confirm the package accepts
   the full set; if it only supports a subset, use the maximum it allows and
   note it).
2. **Hide the visible markers (the diamond handles) without disabling resize.**
   `node_modules` is not installed in this checkout, so after `npm install`
   inspect the rendered handle element's class (the package renders a handle DOM
   node per direction — likely `.react-resizable-handle` or a package-specific
   class). Then, scoped to these grids, make the handle **visually invisible but
   still interactive**: `opacity: 0` (or no background/border) while keeping its
   hit area and `pointer-events` intact, and remove the diamond `transform`/
   background styling. Prefer a `resizeConfig` option if the package exposes one
   (e.g. a "hide handles"/"invisible handles" flag) — check its types first;
   fall back to scoped CSS in `globals.css` (or a grid-local class) only if no
   prop exists. The user must still be able to grab the edges/corners to resize;
   they just must not SEE the markers.

Verify on both surfaces: hover shows no diamond markers, but dragging any
edge/corner resizes the widget.

## E. Extend the Home pinned-widgets grid to full width (image 4)

The Home content is capped by `app-shell.tsx:70`
(`mx-auto w-full max-w-content px-5 py-6`). The pinned-widgets grid is inside
that cap, so it stops short of the viewport. Let the pinned-widgets grid (and
its "Refresh live widgets" row) use the **full available width** rather than
`max-w-content`:
- Preferred: allow the Home page's widget region to break out of the
  `max-w-content` container (e.g. a full-bleed wrapper for just the pins grid),
  OR widen `max-w-content` only where it constrains this grid.
- Do NOT globally remove `max-w-content` from the app shell — other screens rely
  on it. Scope the change to the Home pinned-widgets area so text-heavy screens
  keep their readable max width.
- After the change, `useContainerWidth`/`width={containerWidth}` in
  `home-pins-grid.tsx` will pick up the wider container automatically; confirm
  the grid re-flows to more columns at the wider width via `getColsForWidth`.

## F. Issue 1 — a widget must not be saveable to another project

The dashboard widget-save/generate flows must confine a widget to its own
project. Backend endpoints already scope by project
(`ai_proxy.py:generate-and-save-dashboard` uses `_check_project_access`;
`home_intelligence.py:save-card-to-dashboard` validates
`dashboard.project_id == project.id`), but the **project is taken from the
request**, so a client can still target a different project it can edit.

Do:
- **Frontend:** in the widget-save UI (`WidgetConfigPanel.tsx` /
  `DashboardViewer.tsx` and any "save widget"/"add to dashboard" control), remove
  any project picker. The widget's project is the dashboard's project
  (`projectId` is already threaded through `WidgetConfigPanel` at line 114/123);
  lock the target to that project and only allow choosing a dashboard within it.
- **Backend:** on the widget-save path, assert the target dashboard's
  `project_id` equals the widget's source project and reject cross-project saves
  with a 400 (the `save-card-to-dashboard` endpoint already has this check for
  existing dashboards — apply the same guard consistently to the widget-save and
  new-dashboard paths so a mismatched `project_id` cannot create a widget under
  another project).
- Add a test that a widget/card whose source project is A cannot be saved to a
  dashboard in project B (expect 400/403), even for a user who can edit both.

## G. Issue 2 — "Save insight to Dashboard" must not let you pick a project

File: `web-ui/components/tablescope/home/save-insight-to-dashboard-modal.tsx`.
The modal already knows the card's project
(`sourceProjectId = String(card.projectId)`, line 41) but ALSO renders an
all-projects selector (`useProjectSummaries()` at line 42; `selectedProjectId`
state at line 44 with a project `<select>`), letting the user retarget to a
different project.

Do:
- **Remove the project selector.** Derive the project solely from the card:
  `selectedProjectId` is always `sourceProjectId`; drop the
  `useProjectSummaries()` dropdown and the ability to change it. Display the
  project name read-only for context (line 51's `selectedProjectName`, but sourced
  only from the card's project).
- Keep the new-vs-existing dashboard choice (`mode` state, line 45) — the user
  may still create a new dashboard or pick an existing one **within the card's
  project** (the dashboards query at line 61 already keys off
  `selectedProjectId`, which will now always be the card's project).
- **Backend guard:** `POST /home/save-card-to-dashboard` should not trust a
  client `project_id` that differs from the card's origin. The request already
  carries the card; assert the request's `project_id` matches the card's source
  project (thread the card's `source_project_id` through and 400 on mismatch),
  mirroring the existing `dashboard.project_id == project.id` check. This is the
  same "project comes from the card, not a picker" contract as the Project
  Actions design.
- Test: saving an insight card whose project is A offers only project A and
  rejects a forged `project_id=B`.

## H. Issue 3 — no email sent when adding a user to a project

File: `platform-api/app/routes/projects.py`, `add_member`
(`POST /{project_id}/members`, line 1326). It creates/reactivates the
`ProjectMember` and returns, but **never sends an email** — unlike the tenant
user-invite path (`routes/tenants.py:755`, which calls
`EmailService().send_transactional_email(..., template="user_invitation")`).

Do:
- After the membership commits (both the new-member branch ~line 1381 and the
  reactivation branch ~line 1369), send a **best-effort** transactional email to
  the added user via `EmailService().send_transactional_email(...)`, following
  the tenants-route pattern (import `from app.services.email_service import
  EmailService`). Wrap it in try/except and log a warning on failure — a mail
  failure must NOT fail the add-member request or roll back the membership.
- Use a suitable template. This endpoint adds an **existing tenant user** to a
  project (the user already exists — line 1360), so it is a "you've been added
  to project X" notification, not a first-time invitation. Add a new
  `project_membership` (or similarly named) template under
  `app/services/email/templates.py` if none fits; include project name, the
  actor who added them, their role, and a deep link to the project. If a
  generic notification template already exists, reuse it rather than adding one.
- Pass `tenant_id` for branding (the email service renders branded mail; see the
  tenants call's arguments).
- Tests: `add_member` triggers a send (assert against a faked `EmailService`,
  as `tests/` already fakes email elsewhere — see `_FakeEmail` usage in the
  tenant/KG lifecycle tests); a mail exception does not fail the request or
  leave the membership uncommitted; reactivating an inactive member also sends.

## Definition of done

- web-ui: `tsc`, lint, component tests green; browser-verify each of A–G on the
  actual screens (Project Insight layout + banners, Projects vs Overview upload,
  Home + Dashboard resize markers hidden with all-direction resize working, Home
  grid full width, widget save confined to project, save-insight modal with no
  project picker).
- platform-api: `pytest` + `ruff` green, including the new F/G/H tests.
- Screenshots: Project Insight with Insights & Opportunities expanded and no
  bottom Ask/Recommendations and no persistent banners; Project Overview with
  the upload dropzone; a Home widget mid-resize with no visible markers; the
  save-insight modal showing only the card's project.
- Final report: changed files; the exact resize-handle approach (prop vs scoped
  CSS) and the confirmed handle class; the email template used and where added;
  the backend project-guard assertions added for F and G; tests + browser checks
  run; any package limitation found (e.g. if `react-grid-layout@2.2.3` cannot do
  all 8 handles or lacks a hide-handles prop).
- Do not bundle unrelated refactors. If the Documents/Dashboards sidebar-restore
  or other pending branch work is already merged into the base, leave it intact.
