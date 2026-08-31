# Nav Card Grid + Project Header — Why the Live Build Doesn't Match the Prototype

**Checked against:** `UX-design-01` (HEAD `87b667e7`), same code inherited by `release/deploy-2026-08-07` — verified by reading the actual component source, not the plan text.

## Bottom line

This isn't a styling regression in new code. **The nav-card-grid redesign from the gap-analysis (`docs/ux-workspace-redesign-gap-analysis.md` §2–3) was never built.** What landed on this branch (`0f9c46fd`, `4e8df9e3`) is only the *backend* Workspace data model and API from `workspace-feature-spec.md` §2–3. The screens you're looking at are still running the **pre-existing** `ProjectResourceTabs` and `ProjectHeader` components — the ones that existed before this redesign started — which is why:

- Every button except the active one looks like plain text: `ProjectResourceTabs` (`web-ui/components/tablescope/project/project-resource-tabs.tsx`) has no border, no background, no rounded corners on any tab, active or not. It's an underline-indicator tab strip, not a button grid. The prototype's `.nav-card` class gives *every* card a `border:1px solid` + `border-radius:var(--radius-lg)` baseline regardless of state — that treatment was never ported over.
- It only has 5 items — Overview, Data Sources, Tables, Documents, Dashboards. The other 7 cards the redesign calls for (Workspace, Project Insights, Project Actions, Reference, Scopes, Knowledge Graph, Chats) were never added to it.
- The title/Shared-Private-toggle/Members header row (`ProjectHeader`) only renders on pages that explicitly opt in via `ProjectShell`'s `showProjectHeader` prop — and that opt-in is inconsistent:

| Page | `showProjectHeader` |
|---|---|
| Data Sources | `!inDetail` (on in list view, **off** when viewing one source) |
| Documents | always on |
| Dashboards | `!viewing` (on in list view, **off** when viewing one dashboard) |
| Tables (queries) | `listMode` only |
| Project Actions, Project Insights, Scopes, Goals/Business Context, Knowledge Graph, **Workspace** | never passed → **off** |

So on Actions, Insights, Scopes, Goals, Knowledge Graph, and even the flagship new **Workspace** page itself, there is no title/badge/Share/Members row at all — just the bare 5-item tab strip. That's the "half the button half the white section below, inconsistently" you're seeing: it's not rendering inconsistently by accident, it's simply not there on most pages because those pages never turned it on.

## The fix

1. **Make `ProjectResourceTabs` the full 12-card nav grid**, styled off the prototype's actual CSS (every card gets the baseline border + radius; `.active` only changes background/border-color/text-color/weight, it doesn't add the border):
   ```css
   .nav-card{border:1px solid var(--border-secondary); border-radius:var(--radius-lg); padding:8px 10px; ...}
   .nav-card.active{background:var(--brand-50); border-color:var(--brand-500); color:var(--brand-500); font-weight:600;}
   ```
   Card list and target routes (confirmed in the gap-analysis, §3): Overview (`/projects/[id]`), Workspace (`/workspace` — new), Data Sources (`/data-sources`), Tables (`/queries`), Documents (`/documents`), Dashboards (`/dashboards`), Project Insights (`/insight`), Project Actions (`/actions`), Reference (`/business-context`, renamed from "Goals"), Scopes (`/scopes`), Knowledge Graph (`/relationship-map`), Chats (project-scoped `/ai`, per gap-analysis §3).

2. **Make the header row unconditional on every project page**, not a per-screen opt-in. Concretely: default `showProjectHeader` to `true` in `ProjectShell` (or drop the prop and always render `ProjectPageHeader`) so Title + Active badge + subtitle + Share toggle + Members appears identically on all 12 destinations, including the current detail-view exceptions (viewing a single data source/dashboard) and the Workspace page.

3. Once (1) covers all 12 routes, retire the now-redundant `activeNav !== "overview"` / `showResourceTabs` special-casing in `project-shell.tsx` so Overview renders through the same single path as every other card instead of its own branch.

## Prompt for Devin

> On `release/deploy-2026-08-07` (mirror of the current `UX-design-01` head), fix `web-ui/components/tablescope/project/project-resource-tabs.tsx` and `web-ui/components/tablescope/project-shell.tsx` per `docs/nav-header-gap-report.md`: (1) restyle `ProjectResourceTabs` into the full 12-card bordered/rounded button grid matching `prototype-ux.html`'s `.nav-card`/`.nav-card.active` CSS, adding the 7 missing cards (Workspace, Project Insights, Project Actions, Reference, Scopes, Knowledge Graph, Chats) alongside the existing 5; (2) make `ProjectHeader` (title/badge/Share-Private toggle/Members) render unconditionally on every project page instead of the current per-screen `showProjectHeader` opt-in, including the Workspace page and the data-source/dashboard detail views where it's currently suppressed. Reference `docs/ux-workspace-redesign-gap-analysis.md` §2–3 for the confirmed card-to-route mapping.
