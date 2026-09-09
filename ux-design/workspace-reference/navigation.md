# Navigation

Where the Workspace page sits in the app, and the two other pieces touched alongside it this session: the left sidebar's Data Source Builder entry, and a known gap in the sidebar's asset-tree highlighting worth closing next.

Source of truth: `components/tablescope/project-shell.tsx`, `components/tablescope/nav.ts`, `components/tablescope/sidebar.tsx`, `components/tablescope/sidebar/projects-tree.tsx`.

## Top nav grid

Every project page, including Workspace, renders `ProjectNavGrid` (`project-nav-grid.tsx`) as a row of buttons just under the breadcrumb — Overview, Data Sources, Workspace, Tables, Documents, Dashboards, Project Insights, Project Actions, Reference, Scopes, Knowledge Graph, Chats — built from `projectGridItems(projectId)` in `nav.ts`. This consolidated what used to be two separate things (the old sidebar's "Project" link group, and a `ProjectResourceTabs` strip) into one persistent row, which is *why* the sidebar can stay locked to the project's asset tree instead of switching its link set per page — see `docs/ux-workspace-redesign-gap-analysis.md` for the original rationale.

## Left sidebar

`Sidebar` (`sidebar.tsx`) renders the same core nav — Home, Dashboards, Business Insight, Projects, AI Assistant — in both Home and Project mode; only the selector pill at the top (tenant vs. active project) and what appears below the core nav differ:

- **Home mode**: an "Administration" group (Settings, and Users for platform admins).
- **Project mode**: `ProjectsTree` auto-expands the active project's own Tables/Documents/Data Sources asset subtree beneath it.

### Data Source Builder

As of this session, the **Tools** group (currently just Data Source Builder) renders in **both** modes, not only inside a project:

- **Inside a project**: links straight to `/projects/{id}/data-source-builder`.
- **From Home**: links to `/data-source-builder` — an existing compatibility route (`app/data-source-builder/page.tsx`) that redirects to the caller's one accessible project's builder if they have exactly one, or to `/projects` with a "Select a project" notice if they have several (or none). This route already existed for legacy links; the change was making the sidebar actually offer it outside a project, not building new redirect logic.

See `components/tablescope/sidebar.tsx`'s Tools `NavGroupBlock` for the exact href logic.

## Known gap: sidebar asset-tree highlighting is stale

`docs/workspace-feature-spec.md` §4 called for the sidebar's "open in workspace" highlighting on Tables/Documents items to reflect membership in the **active named workspace's cards** (the `workspaces`/`workspace_cards` model described in `data-model-and-api.md`) once that model existed. It doesn't yet: `ProjectsTree` (`sidebar/projects-tree.tsx`, line ~23/171) still calls `loadWorkspaceTabs(projectId)` — the **old**, single-resource, `localStorage`-backed MRU strip (`workspace-tabs-storage.ts`) — to decide which sidebar items to highlight, not the new backend-persisted workspace cards. Concretely: an item pinned into a named workspace (visible as a card in the Documents pane) will *not* show as highlighted in the sidebar tree unless it also happens to be in the old MRU strip's recent-items list, which is a materially different, page-agnostic thing.

This is a real, verified inconsistency, not a stylistic nitpick — it's the one piece of the original spec's frontend wiring (§4) that the rest of the Workspace build didn't carry through. Fixing it means switching `ProjectsTree`'s highlighting source from `loadWorkspaceTabs` to whichever workspace is active on the Workspace page (`listWorkspaces`/the active workspace's `cards`), which in turn means the sidebar needs to know the *active named workspace*, not just the active project — currently a value that only `WorkspaceScreen` holds locally.

## Home-mode surfaces added after this folder was written

Commit `41dec05d` (2026-09-08) added a **Dashboards** entry between Home and
Business Insight and moved the personal business briefing off `/` onto
`/dashboards`; `/` became a getting-started screen with four starter tiles, and
`/projects/shared` is a new card grid. See
`docs/devin-home-dashboards-workspace-wiring-spec.md` for the full wiring
assessment of those surfaces, and for a re-verification of the ProjectsTree gap
recorded above (still open, with exact line numbers).
