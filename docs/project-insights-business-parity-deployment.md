# Project Insights executive parity: Devin merge and deploy

This branch gives Project Insights the same executive presentation used by
Business Insights: the title and toolbar row, tab navigation, count badges,
Executive Brief, Priority Insights, Key Developments, executive insight cards,
ITSM chart presentation, and full-width Change Summary.

The data scope remains different by design. Business Insights continues to
aggregate the authorized project selection. Project Insights requests and
renders only the project in the current `/projects/{id}/insight` route. Its
Executive Brief and Key Developments are built only from that project's ranked
AI insight cards.

## Repository and branches

- Repository: `https://github.com/lhoskins/tablescope-lh`
- Feature: `codex/project-insights-business-parity`
- Merge target: `release/deploy-2026-08-07`

Do not merge or push this work to `vitruvity33/tablescope`.

## Functional invariants

- Project Insights calls `suggestInsights(granularity, selectedProjectId)` and
  filters the returned collection to the same project ID before rendering.
- The Executive Brief and Key Developments cannot include another project's
  cards, even if an unexpected extra project is present in a response.
- Business Insights keeps its cross-project scope and existing layout.
- Risk, Trend, Opportunity, and Deeper Analysis classifications are unchanged.
- Existing chart data and renderers are unchanged. Value / `% Change`,
  interval, range, tooltip, calculation, and chart-option controls continue to
  use the existing handlers.
- Existing card feedback, Explain, pin, dashboard, action, export, and
  full-analysis handlers are unchanged.
- Change Summary receives one project ID on Project Insights. Its search,
  interval, range, statistics, pagination, and approved colors are unchanged.
- The duplicated inline Ask area is replaced by the existing docked AI
  Assistant. It uses the canonical `project_insights` conversation surface,
  remains collapsed by default, can be resized by width, and can collapse to
  the right.
- No API contract, database schema, worker, or AI prompt changes are included.

## Fetch and validate

```bash
git fetch origin
git checkout codex/project-insights-business-parity
git pull --ff-only origin codex/project-insights-business-parity

cd web-ui
npm ci
npm run typecheck
npm test -- --run \
  components/tablescope/project-insight/project-insight-screen.test.tsx \
  components/tablescope/insights/business-intelligence-workspace.test.tsx \
  components/tablescope/project/workspace/workspace-assistant-panel.test.tsx \
  components/tablescope/project-shell.test.tsx
npm run build
cd ..
```

## Merge

```bash
git fetch origin
git checkout release/deploy-2026-08-07
git pull --ff-only origin release/deploy-2026-08-07
git merge --ff-only codex/project-insights-business-parity
git push origin release/deploy-2026-08-07
```

If the release branch advances and fast-forward is rejected, rebase the
feature branch onto the updated release branch, rerun all validation, and then
merge with `--ff-only`. Do not discard either side of a conflict.

## Deploy the frontend only

No database migration, backend deployment, worker restart, environment change,
or AI-server start is required.

```bash
cd /home/ubuntu/tablescope
git fetch origin
git checkout release/deploy-2026-08-07
git pull --ff-only origin release/deploy-2026-08-07

sudo docker compose build web-ui
sudo docker compose up -d web-ui
sudo docker compose restart nginx
sudo docker compose ps web-ui nginx
sudo docker compose logs --tail=150 web-ui nginx
```

If Devin starts the AI server for an optional live acceptance check, record its
initial state and stop it when the task is complete. Do not stop an AI server
that was already running before this deployment.

## Production smoke test

1. Select project A and open Project Insights. Confirm the page title,
   Project-only Analyze toolbar, Overview, Risks, Trends, Opportunities, Change
   Summary, and any available Deeper Analysis tab match Business Insights.
2. Confirm Risk, Trend, and Opportunity totals render as badge pills and match
   the cards for project A.
3. Confirm the Executive Brief, Priority Insights, and Key Developments mention
   only project A. Switch to project B and confirm all three surfaces update to
   project B without carrying project A content.
4. Open each category. Confirm cards and charts use the Business Insights/ITSM
   presentation and that feedback, Explain, pin, add to dashboard, create
   action, export, and Full Analysis still work.
5. For a time-series insight, switch Value to `% Change` and back, then change
   interval and range. Confirm the existing state, calculation, tooltip, and
   chart behavior are unchanged.
6. Open Change Summary. Confirm it contains only the selected project and that
   search, page size, interval, range, statistics, pagination, and cell colors
   behave as before.
7. Expand the AI Assistant. Confirm it says `Grounded on: Project Insights`,
   sends turns with the current project, preserves the Project Insights
   conversation, resizes horizontally, and collapses to the right.
8. Open Business Insights and verify its cross-project selection, Executive
   Brief, Key Developments, tabs, cards, charts, and Change Summary remain
   unchanged.

## Rollback

Revert the feature commit (or the merge commit if a merge commit was created),
push `release/deploy-2026-08-07`, and repeat the frontend-only deployment. No
schema or data rollback is required.
