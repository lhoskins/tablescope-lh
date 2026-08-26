# Business Insights executive brief: Devin merge and deploy

This branch changes only the Business Insights presentation layer. It adds the
executive briefing layout, section tabs, executive insight-card treatment, the
ITSM chart presentation for supported Value charts, and the approved Change
Summary colors. The Executive Brief now presents the highest-ranked AI insight
as the most pressing matter; analysis-run status and scope text are not shown
in the brief. Risk, Trend, and Opportunity totals are displayed as tab badges.

It does not change an API contract, query, data model, authorization rule,
insight classification, card action, chart option, or time-series control.

## Branches

- Feature: `codex/business-insights-executive-brief-style`
- Merge target: `release/deploy-2026-08-07`

## Functional invariants

- Existing project selection, depth, Analyze, cache, card action, feedback,
  pinning, export, and drill-through handlers are passed through unchanged.
- Analyze continues to populate the existing insight feed. Its deterministic
  project/insight count status is intentionally not rendered as the Executive
  Brief.
- The Executive Brief uses the title and summary from the highest-ranked AI
  insight already returned by the feed, prioritizing Risk, then Opportunity,
  Trend, and deeper Analysis. It does not issue an additional AI request.
- Risk, Trend, and Opportunity tab badges display their current counts,
  including zero, and update from the existing filtered insight collections.
- Existing Value / `% Change`, interval, and range state remains in
  `InsightTimeSeriesChart`.
- Supported Value charts use the existing ITSM operational renderer.
- `% Change` stays on the existing signed-percent renderer so its zero
  baseline, signed behavior, tooltip semantics, and calculation disclosure do
  not change.
- Unsupported chart types fall back to the existing chart renderer.
- Project Insights and pinned Home cards retain their existing presentation.
- Change Summary colors are exactly Positive `#74C990`, Negative `#EA7975`,
  and No change `#626365`.

## Fetch and validate

```bash
git fetch origin
git checkout codex/business-insights-executive-brief-style
git pull --ff-only origin codex/business-insights-executive-brief-style

cd web-ui
npm ci
npm run typecheck
npm test -- --run \
  components/tablescope/home/intelligence-card.test.tsx \
  components/tablescope/home/percent-change-summary-table.test.tsx \
  components/tablescope/insights/business-intelligence-workspace.test.tsx \
  components/tablescope/insights/insight-time-series-chart.test.tsx
npm run build
cd ..
```

## Merge

```bash
git fetch origin
git checkout release/deploy-2026-08-07
git pull --ff-only origin release/deploy-2026-08-07
git merge --ff-only codex/business-insights-executive-brief-style
git push origin release/deploy-2026-08-07
```

If fast-forward is rejected because the release branch advanced, rebase the
feature branch onto the updated release branch and rerun all validation. Do not
resolve a conflict by discarding either side's behavior.

## Deploy the frontend only

No database migration, API deployment, worker restart, environment change, or
AI-server start is required.

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
initial state and stop it when the task finishes. Do not stop a server that was
already running before this task.

## Production smoke test

1. Open Business Insights and confirm Overview, Risks, Trends, Opportunities,
   and Change summary render. Confirm Risk, Trend, and Opportunity counts use
   pill badges, including a zero badge when a category is empty.
2. Confirm the Executive Brief summarizes the highest-ranked pressing AI
   insight and does not display the `AI analyzed N projects...` run-status
   result.
3. Change project selection and depth, then Analyze. Confirm the same insight
   data populate the new layout, the Executive Brief and badges update, and no
   additional AI request is made solely for the brief.
4. Confirm feedback, Explain, pin, dashboard, action, export, full-analysis,
   chart options, and other existing card actions still work.
5. Switch Value to `% Change` and back; change interval and range. Confirm the
   controls behave as before and `% Change` retains its zero baseline, signed
   coloring, tooltip values, and Calculation details.
6. Confirm supported Value charts have ITSM styling and unsupported types still
   render through the previous fallback.
7. Confirm Change summary search, page size, interval, range, statistics, and
   pagination work. Verify `#74C990`, `#EA7975`, and `#626365` cells.
8. Open Project Insights and Personal Home and confirm their layout and card
   presentation did not change.

## Rollback

Revert the merge commit (or feature commit after a fast-forward), push the
release branch, and repeat the frontend-only deployment. There is no schema or
data rollback.
