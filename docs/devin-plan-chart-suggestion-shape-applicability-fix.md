# Devin plan: fix chart-suggestion shape applicability (no gauge for time series, restore KPI, regenerate)

Repository: `lhoskins/tablescope-lh`
Base: current deployed lineage (`devin/r-echarts-e2e-validation` / the integrated
branch — confirm it has `visualization_engine.rank_visualizations`). Feature
branch: `devin/chart-suggestion-shape-fix`. Additive/surgical; complements
`docs/devin-plan-echarts-chart-intelligence.md` (do not regress it).

## What's actually happening (researched — it is NOT hard-coded)

The ranking is real and data-shape-driven: `home_intelligence.py:1031` calls
`rank_visualizations` → `recommend_visualizations` in
`platform-api/app/services/visualization_engine.py`, and the frontend
`chart-suggestion-dialog.tsx` shows `card.chartCandidates` (falling back to a
`FALLBACK_CANDIDATES` list only when the backend sends none). The problem is
**shape-applicability bugs in the ranker**, plus stale cached cards:

1. **Gauge is deliberately offered for time series.** `visualization_engine.py`
   lines ~722-733:
   ```python
   # 4a) Gauge: latest value from a time series.
   if shape.measures and is_time:
       candidates.append(_candidate(ChartType.GAUGE, 0.55, ...,
           reason="Latest value shown as a radial gauge."))
   ```
   A gauge collapses a multi-point series to one number — it does **not** match a
   time-series shape and must not be suggested for it. (The correct gauge/KPI gate
   already exists at lines ~610-634 for single-row scalar data.)
2. **Other ungated families:** audit the `RADIAL_BAR` appends (~798/896/989) and
   the explicit `hint == "gauge"` path (~1005) the same way — a family may be a
   candidate only if the data shape genuinely supports it.
3. **75 existing insights are cached** and were generated before/around these
   changes, so they keep old candidates and chart types (why you still see mostly
   line/bar and stale menus).

## Fix

### 1. Enforce hard shape-applicability per family (deterministic, not hard-coded)

In `recommend_visualizations`, every candidate must pass an **applicability
predicate** derived from `shape` (row_count, time index, # measures, dimension
cardinality, positivity, matrix-ness). A family that fails its predicate is
**excluded** — never added to reach `limit`, never padded in.

- **Remove the "4a) Gauge: latest value from a time series" branch** (722-733).
  Gauge is eligible **only** for single-value/single-row scalar data (the
  existing 610-634 branch). Same for KPI.
- Audit and gate the `RADIAL_BAR` appends and any other family added outside a
  shape-checked branch.
- The `intent_hint`/`hint == "gauge"` path must also be **shape-validated** — an
  explicit gauge request is honored only when the shape is single-value; otherwise
  ignored (the data wins, per the engine's own docstring).
- Diversity padding (`_diverse_top_n`) must only reorder **eligible** candidates;
  it must never introduce an ineligible family to fill the six slots.

Result: for a monthly single-metric series the suggestions are the families that
actually fit — line, area, combo, bar, table — and **no gauge**. Richer families
(heatmap, box/histogram, treemap, sankey, radar, candlestick) appear only when the
data shape warrants them (matrix / distribution / hierarchy / flow / OHLC), per
the chart-intelligence plan.

### 2. Restore KPI selection

"No KPI across 75 insights" — verify `derive_shape` correctly identifies
single-value / single-row-scalar insights and that such insights select **KPI**
as the primary (score 0.95 already). Add a test: a single-aggregate insight →
primary `kpi`, and gauge offered as its only alt (single value), never for a
series. If single-value insights are being misclassified as multi-row, fix the
shape detection.

### 3. Frontend: stop showing a generic hard-coded menu

In `chart-suggestion-dialog.tsx`, the `FALLBACK_CANDIDATES` list is a hard-coded
menu shown when the backend sends no candidates. Since the backend now always
ranks, either remove `FALLBACK_CANDIDATES` or reduce it to a **safe, shape-neutral
minimum (table only)** — never present a fixed menu that can include a
shape-inappropriate chart. The dialog should render exactly the backend's
shape-ranked `chartCandidates`.

### 4. Regenerate the cached insights

The corrected ranker only affects **newly generated** cards. Clear the insight
caches so the 75 existing insights rebuild with the fixed candidates + primary
charts: truncate/delete `business_insight_results` and the project-insight
snapshots (existing `scripts/delete_insight_caches.py` path), then let them
regenerate.

### 5. "Clear cache" button on the Business Insight and Project Insight pages

Add a user-facing **Clear cache** button on each insight page so a user can empty
the cached cards on demand; **all cards disappear** after clearing (empty state),
and cards rebuild on the next generate/refresh.

The clear logic already exists but only as an **unscoped script**
(`scripts/delete_insight_caches.py` `delete_insight_caches()` deletes all
`BusinessInsightResult` + `ProjectIntelligenceSnapshot` rows). The button needs
**scoped** endpoints:

- **Backend — Business Insight:** an endpoint that deletes
  `BusinessInsightResult` rows for **`context.tenant_id` only** (not all tenants).
- **Backend — Project Insight:** an endpoint that deletes
  `ProjectIntelligenceSnapshot` rows for the **specific `project_id`** (enforce
  project access), reusing the existing sequence-reset safety from the script.
- Gate both appropriately (ADMIN / project-manage role), audit the action, and
  keep tenant/project isolation strict — a clear must never touch another
  tenant's or project's cache.
- **Frontend:** add a **Clear cache** button to
  `web-ui/app/business-insight/page.tsx` (tenant scope) and the Project Insight
  page/screen `web-ui/components/tablescope/project-insight/project-insight-screen.tsx`
  (current project scope). On click: a confirm dialog, call the endpoint, then
  **invalidate the insights query** so the card list immediately empties to the
  existing empty state. Do not auto-regenerate — clearing just empties; the
  normal generate/refresh rebuilds with the corrected ranking.
- Place it near the existing page header actions; disable while the request is in
  flight; show a brief success confirmation.

Tests: clearing empties only the caller's tenant (business) / project (project)
cache and leaves others intact; the page shows zero cards after clear; a
subsequent refresh regenerates; non-authorized roles are forbidden.

## Expectation-setting (honest)

"More variety" is bounded by the data shape — a simple monthly single-metric trend
*correctly* suggests line/area/combo/bar/table, not heatmap/sankey. Variety shows
up when the underlying insight data has the shape for it (two categoricals →
heatmap, a distribution → box/histogram, a hierarchy → treemap, a flow → sankey).
So the win here is: (a) no shape-inappropriate suggestions (no gauge on a series),
(b) KPI restored for single-value insights, and (c) the richer families surface
whenever an insight's data actually supports them.

## Tests

- Time-series result → candidates are line/area/combo/bar/table; **gauge and KPI
  are absent**; primary is line/combo.
- Single-scalar result → primary **kpi**; gauge offered as the alt; no series
  families.
- Two-categoricals+measure → heatmap eligible; distribution → box/histogram;
  hierarchy → treemap/sunburst; flow → sankey (only when shape supports).
- `_diverse_top_n` never returns an ineligible family; `hint=="gauge"` on a series
  is ignored.
- Frontend renders only backend candidates; no hard-coded menu appears when the
  backend returns candidates.
- After cache clear, a regenerated time-series insight shows no gauge suggestion.

## Deploy & land

Merge into the deployed lineage, redeploy (rebuild web-ui if the dialog changed),
run the cache-clear, and verify on the live app that a time-series insight's
Chart-suggestion modal no longer offers gauge and that single-value insights show
KPI. Do not leave on an unmerged branch.

## Report

The exact branches/predicates changed (esp. removing the time-series gauge at
722-733 and any ungated RADIAL_BAR); the KPI-detection fix; the frontend fallback
change; confirmation the cache was cleared and insights regenerated; and
before/after screenshots of a time-series Chart-suggestion modal (no gauge) and a
single-value insight (KPI).
