# Devin plan: deep evaluation — why chart variety never appears, with a test-until-visible protocol

Repository: `lhoskins/tablescope-lh`
Base: current deployed lineage (`devin/r-echarts-e2e-validation` or merged
successor). Feature branch: `devin/chart-variety-deep-eval`.
Complements (does not replace) `docs/devin-plan-chart-suggestion-shape-applicability-fix.md`
and `docs/devin-plan-echarts-chart-intelligence.md`.

## Findings from code evaluation (verified — start from these, don't re-derive)

### Finding A — period columns leak into the category families (the radial_bar bug)

`platform-api/app/services/visualization_engine.py`:
- `derive_shape` (~line 296) includes **period** columns in `dimensions`:
  `c.kind in ("categorical", "text", "period")`. So for a monthly series,
  `_primary_dimension` returns the **month column as `label_col`**.
- The category-family section ("6) Radar / radial bar / treemap for category
  charts", ~line 790) only checks `label_col is not None` — it does **not** call
  the existing `_is_period_dimension(shape, col)` helper (line 462). Result: on
  time-series data the ranker offers radial_bar ("Percentage-to-target metrics by
  category" — the rate role matches any 0-100 measure), ranked horizontal bar
  ("24 categories" = 24 months), funnel, treemap. Yesterday it was gauge; the
  class of bug is the same: **families not gated on the time-ness of the axis**.

### Finding B — the insight data pipeline hard-codes 2-column shapes (why only line/bar/KPI across 50 insights)

`platform-api/app/services/home_intelligence.py` builds every card's chart data
as `{"label": ..., "value": ...}` pairs — verified at lines ~1181, 1348, 1414,
1569, 1667 (`series.append({"label": str(r.get("period")), "value": ...})` etc.).
The planner's SQL aggregates to 1 dimension + 1-2 measures before charting.

**A label/value aggregate can only ever be line/bar/pie/kpi/table.** Heatmap
needs two dimensions + a measure; box/histogram needs raw (unaggregated)
distributions; sankey needs source→target flows; scatter needs two measures per
row. So the absence of variety is structurally guaranteed upstream — the ranker
never *sees* a shape that could produce the richer families. This is the
"hard-coded somewhere" intuition: it is the **insight planner/query layer**, not
the chart picker.

## Task 1 — Fix the period/category leak (surgical)

In `recommend_visualizations`:
- Gate the entire category-families section (radar, radial_bar, funnel, treemap,
  and the ranked/"N categories" horizontal-bar path) with
  `not _is_period_dimension(shape, label_col)`. A time axis is not a category
  axis. (Keep genuinely categorical shapes exactly as they behave today.)
- Re-audit every family append for the same class of bug: each family's predicate
  must consider **time-ness**, row_count, #measures, and cardinality. No family
  may be offered on a shape it misrepresents.
- Extend the applicability tests: monthly/weekly/daily series with a 0-100
  measure → candidates are line/area/combo/bar(time axis)/table only — **no
  radial_bar, no gauge, no funnel/treemap, no ranked-top-N category bar**.

## Task 2 — Test protocol: prove the ranker with correct-shape samples until charts appear

Build a small, repeatable test set (fixtures + a live test project) with one
dataset per target shape, and **iterate until each renders its expected chart**
end-to-end (ranking → card → ECharts render):

| Sample dataset (small, synthetic ok) | Expected primary/candidates |
|---|---|
| month × metric (existing case) | line/area/combo; KPI absent; no category families |
| single aggregate value | **KPI** primary (this is currently missing — verify shape detection) |
| region × product × revenue (2 dims + measure) | **heatmap** |
| raw order-values (1 numeric col, many rows) | **histogram / box plot** |
| plant → line → machine hierarchy w/ measure | **treemap / sunburst** |
| source→target→amount flow rows | **sankey** |
| two measures per row (price vs volume) | **scatter/bubble** |
| category × 3-6 metrics scorecard | **radar** |
| OHLC per period | **candlestick** (if renderer family enabled) |

For each: load the sample as a data source/query in a test project, generate or
hand-trigger an insight over it, and verify (a) `rank_visualizations` output, (b)
the card's chart, (c) the Chart-suggestion modal — until the expected chart is
actually visible in the UI. Fix whatever blocks each one (shape detection,
ranking, renderer, card plumbing) before moving to the next. This is the
"test with correct shapes until you see the charts" loop — do not stop at unit
tests; the exit criterion is pixels.

## Task 3 — Audit the real data sources: can they produce richer shapes at all?

Answer the user's question directly: **do the existing tenant data sources ever
yield shapes beyond label/value?**

- Instrument (temporarily or via logging) the executed result sets feeding the ~50
  live insights: record columns, inferred kinds (period/category/measure),
  row counts, distinct-ness. Produce a small report: how many insights emit
  1-dim+1-measure vs anything richer.
- Inspect the insight planner prompts/SQL builders in `home_intelligence.py` (and
  the ai-server plan prompts): confirm they always aggregate to
  `label/value(/value2)`. That is Finding B's mechanism.
- Deliver a verdict per data source: "this source has columns to support
  heatmap/distribution/flow (e.g. two categorical dims + measures), but the
  planner never asks for that shape" vs "this source genuinely has nothing
  richer." Expectation: the executive-KPI CSVs are wide monthly scorecards —
  rich in *measures* (radar/combo material), poor in second dimensions.

## Task 4 — Unlock richer shapes in the insight planner (the real fix for variety)

Where Task 3 shows a source *can* support richer shapes, extend the insight
generation to request them:

- Teach the planner (analysis templates in `home_intelligence.py` + the ai-server
  plan prompts) additional **shape templates**, used when the source schema
  supports them: two-dimension aggregation (dim × dim × measure → heatmap),
  raw-distribution sampling (bounded row cap → histogram/box), multi-measure per
  entity (→ radar/scorecard), flow pairs where FK-like relationships exist
  (→ sankey), two-measure correlation rows (→ scatter). Keep every query bounded
  (row caps) and deterministic.
- Keep the card contract: the executed result set (not a pre-collapsed
  label/value series) flows to `rank_visualizations` — stop collapsing to
  `{"label","value"}` when the analysis produced a richer frame; build the chart
  payload from the decision's fields instead.
- Do NOT force variety: a source whose only sensible shape is monthly
  label/value should keep producing line/bar/KPI. The goal is that richer shapes
  are *possible* where data supports them, not decorative.

## Deliverables / DoD

1. Time-series suggestions show **no category-family charts** (no radial_bar/
   gauge/funnel/treemap/ranked-category bar on a month axis) — deployed and
   verified on the live Chart-suggestion modal.
2. Every sample-shape row in Task 2 renders its expected chart in the UI
   (screenshots per row).
3. A written audit answering: which existing data sources can/cannot produce
   richer shapes, and why current insights are line/bar/KPI (Finding B confirmed
   quantitatively — N of 50 insights emit 1-dim+1-measure).
4. Planner shape-templates implemented for at least heatmap + distribution +
   multi-measure (where sources support them), with at least one live insight per
   new shape rendering on the Business-Insight page.
5. Caches cleared and insights regenerated after the fixes (use the Clear-cache
   button work if landed, else the script); all tests green; merged into the
   deployed lineage and redeployed — not stranded.

## Report

Findings confirmed/refuted with line references; the category-leak diff; the
Task 2 matrix with per-shape pass status and screenshots; the Task 3 audit table
(insight → emitted shape → why); which planner shape-templates were added and
example live cards using them; cache-clear + redeploy confirmation.
