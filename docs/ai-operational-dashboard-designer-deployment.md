# AI Operational Dashboard Designer: Devin deployment runbook

This update replaces the end-user widget-building path for new Operational
Insight dashboards with one AI-guided workflow:

1. Describe the operational decisions the dashboard must support.
2. Review AI questions, datasource readiness, missing fields and chart types
   compatible with the detected data shape.
3. Preview the complete ServiceNow-style dashboard and create or update it.

The same workflow powers **Edit dashboard**, **Add insight**, and per-insight
**Modify with AI**. Users never configure SQL, metric aggregations or chart
widgets. Existing non-operational dashboards and their query wiring remain
unchanged.

## Branch and pull request

```bash
git fetch origin
git checkout codex/operational-template-bindings
git pull --ff-only origin codex/operational-template-bindings
```

Review and deploy the updated PR #191 into
`devin/servicenow-itsm-dashboards-v2`.

## Pre-deployment validation

Backend:

```bash
cd platform-api
python -m compileall -q app tests
pytest -q \
  tests/test_ai_dashboard_designer.py \
  tests/test_ai_dashboard_pipeline.py \
  tests/test_operational_insight_dashboards.py
cd ..
```

Frontend:

```bash
cd web-ui
npm ci
npm run typecheck
npm run test -- components/tablescope/project/ai-dashboard-designer.test.tsx
npm run build
cd ..
```

## Release sequence

No new environment variable or database migration is introduced by this
increment. Keep the existing Operational Insight migration state from PR #191.

```bash
docker compose build platform-api web-ui
docker compose up -d platform-api platform-api-worker web-ui
docker compose ps platform-api platform-api-worker web-ui
docker compose logs --tail=150 platform-api platform-api-worker web-ui
```

The dashboard designer reuses the existing AI service route,
`/ai/dashboard/suggest-multi`, and the existing governed SavedQuery creation,
validation, binding and dashboard hydration pipeline.

## Required acceptance checks

1. Open a project's Dashboard overview and select **Create with AI** or
   **Create dashboard with AI**.
2. Describe an operational decision. Confirm periods include 30, 60 and 90
   days, 6 months, 1 year and 2 years, and that audience, emphasis and primary
   dimension are available.
3. With complete data, confirm **Fully supported**, compatible chart
   recommendations, grounded datasource names and a complete Operational
   Insight preview appear before creation.
4. With one requested field absent, confirm **Partially supported** identifies
   the missing field and requires explicit approval before previewing the
   supported subset.
5. In a project without supporting data, confirm **Not supported** prevents
   dashboard creation and **Upload or connect data** opens project datasource
   onboarding.
6. Create the dashboard. Confirm it uses the complete ServiceNow-style
   Operational Insight background, cards, skinny bars, Operational Brief and
   Best Improvement Opportunities—not the legacy dashboard shell.
7. Confirm the header contains **Edit dashboard** and **+ Add insight**, and no
   **+ Add Widget** button or legacy widget configuration screen.
8. Use **+ Add insight** to add one KPI card or chart. Confirm existing insights
   are unchanged. Use a chart pencil to replace only that insight through AI.
9. Use **Edit dashboard** to restructure the operational story and review the
   full dashboard before applying. Confirm SavedQuery wiring remains governed
   and the dashboard's AI design history increments.
10. Drag a chart above KPI cards and resize it. Reload and confirm the grid
    layout persists and remaining cards reflow.
11. Create a dashboard inside an existing group. Confirm it stays in that group
    and does not create a duplicate Custom dashboards group.
12. Open a legacy non-operational dashboard and confirm its existing renderer,
    queries and controls still work.

## API smoke checks

Authenticated editor requests should use:

- `POST /api/ai/actions/dashboard-designer/review`
- `POST /api/ai/actions/dashboard-designer/apply`

The review response must return exactly one of `fully_supported`,
`partially_supported`, or `not_supported`. The apply route must reject
`not_supported`, reject an unapproved partial design, and reject a design with
no validated query-backed insight.

## Rollback

Deploy the previous application SHA for both `platform-api` and `web-ui`. This
increment has no schema rollback. Dashboards already created by the designer
remain ordinary Operational Insight dashboards backed by SavedQueries, so they
remain readable after application rollback.
