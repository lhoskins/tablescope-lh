# Devin: merge and deploy the Insight chart-picker confidence repair

**Repository:** `lhoskins/tablescope-lh`

**Feature branch:** `codex/insight-chart-picker-confidence-fix`

**Merge target:** `UX-design-03`

**Feature implementation commit:** `8ae40bcf6570a71272c4d5972872b2a4de0b50ca`

**Feature base / UX-design-03 at implementation time:** `7b84c0236ed9b9b1ab786f6105ffc40099b1b8ce`

**Scope:** `platform-api` + `platform-api-worker` + `web-ui`; no database migration, AI-server change, or environment-variable change.

Do not merge to or modify `release/deploy-2026-08-07` as part of this task.

## What was wrong

This was a rules/pipeline defect, not merely an unavoidable data-shape limit:

1. The recommender created a valid period bar for `time + measure`, but the
   catalog's second hard gate rejected it because bars required a non-time
   dimension. A common monthly series was therefore reduced to line, area,
   and table.
2. `calendar_heatmap` required both `time` and `raw`, while the shape adapter
   intentionally refused to mark a time-only result as `raw`. The declared
   chart could never qualify.
3. Catalog subtype families were deduplicated by their parent renderer type.
   Waterfall was discarded when bar existed; bubble when scatter existed;
   bump when line existed; and calendar heatmap when heatmap existed.
4. Catalog-promoted candidates had no grounded `xField`/`yField`/`y2Field`.
   The Insight preview then retained the currently selected chart's roles,
   which could show the wrong axes or an empty preview.
5. Card candidate-generation failures were logged only at debug level, and
   ECharts swallowed option/render exceptions. A real failure looked like a
   legitimately narrow set of options.
6. Insight cards stored their candidates in cached snapshots. Without a live
   re-rank when the picker opened, a corrected backend could still appear
   broken until every insight cache was regenerated.

## Repair behavior

- The catalog now supports an explicit `needs_any` rule. Bar accepts a genuine
  category or ordered time axis without making arbitrary numeric data eligible.
- Daily grain is detected independently, and calendar heatmap has a real
  ECharts calendar renderer.
- Compatibility and confidence are separate: compatibility decides whether a
  chart is safe; confidence ranks the safe choices and selects the default.
  A fixed `0.5` promotion cutoff no longer silently hides compatible options.
- Semantic subtypes remain distinct choices even when they share a renderer.
- Every promoted candidate receives fields grounded in the result columns.
- The Insight picker re-ranks against the card's actual rows whenever it opens,
  so existing cached cards receive the repaired choices immediately. If that
  request fails, the UI explicitly says it is showing saved choices and offers
  Retry.
- Backend ranking failures now include project/columns/row count at exception
  level, and ECharts render failures are visible in the browser console.

Expected representative option sets:

| Result shape | Compatible options |
|---|---|
| Monthly period + one metric | line, area, bar, table |
| Daily date + one metric (28+ rows) | line, area, calendar heatmap, bar, table |
| Category + one positive metric | bar, pie, waterfall, treemap, pictorial bar, table |

These are examples, not quotas. Data shape remains authoritative; unsupported
charts must not be padded into the picker merely to reach a target count.

## Merge procedure

```bash
git fetch origin --prune

# Confirm the reviewed feature commit is present.
git rev-parse origin/codex/insight-chart-picker-confidence-fix
git show --stat --oneline origin/codex/insight-chart-picker-confidence-fix

# Start from the current integration branch and preserve a rollback pointer.
git checkout UX-design-03
git pull --ff-only origin UX-design-03
git branch backup/UX-design-03-before-chart-picker-fix-20260903
git push origin backup/UX-design-03-before-chart-picker-fix-20260903

# Merge the feature. Do not squash: preserve the diagnostic implementation and
# this handoff document together.
git merge --no-ff origin/codex/insight-chart-picker-confidence-fix \
  -m "Merge insight chart-picker confidence repair into UX-design-03"
```

If `UX-design-03` moved after the base SHA above, inspect the delta before
continuing. Resolve conflicts by preserving the current UX-design-03 UI plus
the feature's catalog eligibility, candidate field mapping, live re-rank, and
calendar renderer. Do not take an entire-file side for the visualization engine.

## Validate before push

```bash
cd platform-api
python -m pytest -q tests/test_chart_catalog.py tests/test_visualization_engine.py
python -m pytest -q tests/test_home_intelligence.py \
  -k 'build_chart or shape or chart_candidate'
python -m pytest -q tests/test_ai_dashboard_designer.py \
  -k 'chart_recommendations or grounded_chart_selection or chart_overrides'
python -m ruff check \
  app/services/chart_catalog.py \
  app/services/visualization_engine/catalog.py \
  app/services/visualization_engine/recommend.py \
  app/services/home_intelligence/card_builder.py
python -m mypy \
  app/services/chart_catalog.py \
  app/services/visualization_engine/catalog.py \
  app/services/visualization_engine/recommend.py \
  app/services/home_intelligence/card_builder.py

cd ../web-ui
npm ci --no-audit --no-fund
npm test -- --run \
  lib/insights/chart-candidate.test.ts \
  components/tablescope/home/intelligence-card/build-multi-dim-widget.test.ts \
  components/dashboard/EChartsWidget.test.tsx \
  lib/visualizations/chartRegistry.test.ts \
  lib/visualizations/chartCatalogLockstep.test.ts
npm run typecheck
```

Then push the reviewed merge:

```bash
cd ..
git push origin UX-design-03
```

## Deploy

Deploy backend and frontend together because the API emits the repaired
candidates and the UI applies their field mappings and renders calendar heatmap.

```bash
git checkout UX-design-03
git pull --ff-only origin UX-design-03

sudo docker compose build platform-api web-ui
sudo docker compose up -d platform-api platform-api-worker web-ui
sudo docker compose restart nginx

sudo docker compose ps platform-api platform-api-worker web-ui nginx
sudo docker compose logs --tail=200 platform-api platform-api-worker web-ui nginx
```

No migration command is required.

## Live acceptance checks

1. Open an existing monthly Insight card and click **Chart options**. Do not
   regenerate the insight first: this validates the new live re-rank bypasses
   stale cached candidates. Confirm line, area, bar, and table appear.
2. Select bar, apply it, refresh the page, and confirm the selection persists.
3. Open a daily Insight with at least 28 daily rows. Confirm calendar heatmap is
   offered and its preview shows calendar cells rather than the matrix "needs X
   and Y dimensions" message.
4. Open a category + metric Insight. Confirm bar and waterfall are both present
   and visually different; confirm their previews use the correct category and
   metric fields.
5. Confirm a one-row scalar still offers KPI/gauge/table and a no-measure result
   still offers table only. This proves variety did not override shape safety.
6. Check the browser console and service logs. There should be no `ECharts option
   rendering failed` or `chart candidate generation failed` entries.

## Rollback

Redeploy the backup branch created above, or revert the merge commit on
`UX-design-03`, then rebuild/restart `platform-api`, `platform-api-worker`, and
`web-ui`. There is no schema rollback and no data migration to reverse.

Report back the merge SHA, deployed SHA, validation counts, and the option lists
observed for monthly, daily, category, scalar, and no-measure acceptance cases.
