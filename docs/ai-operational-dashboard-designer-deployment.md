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

This increment also makes AI-created dashboards use the same shared header and
operational-story shell as ITSM Insights. The dimension type and value are
separate header controls, layout changes are explicitly gated by **Edit
layout**, horizontal rankings cannot become full width, improvement
opportunities default to the bottom-right, and chart display units work like
Excel without changing raw query values.

## Branch and pull request

```bash
git fetch origin
git checkout claude/restore-operational-layout-alignment
git pull --ff-only origin claude/restore-operational-layout-alignment
```

Merge into `release/deploy-2026-08-07` (fast-forwards cleanly from the current
deploy HEAD).

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
npm run test -- \
  components/tablescope/project/ai-dashboard-designer.test.tsx \
  lib/dashboard/operationalLayout.test.ts \
  components/dashboard/EChartsWidget/axis-scale.test.ts
npm run build
cd ..
```

## AI server lifecycle for Devin

Devin has permission to start the AI server when a live dashboard-generation
smoke test requires it. Check and record the server status first. If it is
stopped, start it through the existing admin AI-server control and mark that
the task started it. In a `finally`/cleanup step, stop any AI-server instance
started by this task and confirm the final state is stopped. Do not stop an
instance that was already running before this task.

Unit tests, typechecking, builds, and deterministic rendering checks do not
require starting the AI server. Start it only for the live AI acceptance steps
below, and stop the task-started instance even if validation fails.

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
6. Create the dashboard. Confirm its header is the same shared component as
   ITSM Insights and contains, in order: period, configured dimension type
   (for example Site or Region), dimension value, dashboard selector, **Edit
   layout**, **Edit with AI**, and **Refresh**. Confirm there is no inline
   pencil beside the dimension.
7. Confirm the full-width Operational Brief sits immediately below the header
   with Backing risk, Primary driver and Recommended action; KPI cards are the
   first grid row; and Best Improvement Opportunities is in the bottom-right.
8. Enter **Edit layout**, drag a chart to the first available grid position,
   resize it, select **Done**, reload, and confirm the layout persists. Confirm
   drag/resize is disabled outside Edit layout mode.
9. Confirm every horizontal bar/ranking chart is at most 6 of 12 columns wide,
   including after a resize attempt.
10. Set a numeric chart to **Thousands**. Confirm 37,100,000 renders as 37,100
    on the numeric axis and the axis is labeled **Thousands**; query results and
    tooltips retain the original value.
11. Use **Edit with AI** to restructure the operational story and review the
   full dashboard before applying. Confirm SavedQuery wiring remains governed
   and the dashboard's AI design history increments.
12. Create a dashboard inside an existing group. Confirm it stays in that group
    and does not create a duplicate Custom dashboards group.
13. Open a legacy non-operational dashboard and confirm its existing renderer,
    queries and controls still work.

The expected desktop result is captured in
`docs/mockups/ai-dashboard-itsm-layout.png`; its editable source is the adjacent
SVG and mirrors the implemented 12-column layout contract.

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
