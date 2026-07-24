# Devin plan: ECharts chart intelligence — full family registry, data-shape ranking, top-6 suggestions

Repository: `lhoskins/tablescope-lh`

> **This plan supersedes `docs/devin-prompt-chart-selection-data-shape-ranking.md`.**
> Implement this one; it is the single authoritative version. It is **purely
> additive** — it extends the visualization engine and the ECharts renderer, and
> does not replace or delete existing working code.

## Base branch & no-overwrite / no-strand rules (read first)

- **Base:** the integrated R/ECharts branch `devin/r-echarts-integration` (or its
  merged successor if it has landed). Confirm it has the ECharts-only
  `WidgetRenderer` + `EChartsWidget` and `visualization_engine.py` before starting.
- Feature branch: `devin/echarts-chart-intelligence`.
- **Additive only.** Extend `EChartsWidget`, `visualization_engine.py`, and the
  chart registry. Do **not** rewrite the existing renderer, remove working
  families, or change unrelated behavior. Every existing chart must keep
  rendering.
- **Lockstep contract (do not break it):** a chart family may be *selected* only
  if it is *registered in the renderer* and *declared in the registry*. Keep
  `ChartType` (backend), the ECharts family registry (frontend), and
  `EChartsWidget` builders synchronized — add all three together for each family.
- **Land it so it isn't lost:** after verification, open a PR and **merge into the
  deployed lineage**, then rebuild web-ui and redeploy (see Deploy). Do not leave
  this on an unmerged sibling branch — that is why prior work never showed.

## Current state (verified)

- `web-ui/package.json`: **`echarts` ^6.1.0** — the full package; **all** chart
  families are already installed and importable from `echarts/charts`.
- `EChartsWidget.tsx` registers only **9** via `echarts.use([...])`: Line, Bar,
  Pie, Scatter, Radar, Treemap, Funnel, Sankey, Gauge. The rest are installed but
  **not registered**, so they cannot render.
- `visualization_engine.py` `ChartType` is capped to the 13 `WidgetType` families
  and `select_visualization` returns a **single** decision biased to
  line/area/bar/pie/scatter/combo/kpi. There is **no ranking** and **no
  suggestion** path; an `intent_hint` lets the LLM request a chart (snapped to the
  13) — the wrong direction.

## Goal

1. **Register the full installed ECharts family set** and expose it as one
   declarative **capability registry** that both the renderer and the planner/
   selector read — so the planner has access to *all installed ECharts*.
2. Replace single-pick selection with a **deterministic, data-shape-driven
   ranking** over that full set; the primary chart is the top-1 and **"Suggest
   chart" is the diverse top-6**.
3. The LLM identifies the question and may bias; it does **not** pick the chart.

---

## 1. Single source of truth — the ECharts capability registry

Create one declarative registry (e.g. `web-ui/lib/visualizations/echarts/families.ts`
+ a mirrored backend catalog the selector reads, or a generated shared JSON) that
lists **every governed ECharts family**, each with:

- `family` id (stable, e.g. `heatmap`), ECharts **series type**, required ECharts
  **components** (e.g. heatmap → `VisualMapComponent`; themeRiver → `SingleAxis`;
  calendar heatmap → `CalendarComponent`);
- **data-shape fit rule** (the shapes it suits) and a **fit-scoring** function;
- a **renderer builder** reference in `EChartsWidget`;
- flags: `enabled`, `gated` (e.g. geo maps need basemap data/licensing → default
  off), `analyticalLayers` it supports (bands/markers).

This registry is the contract: **the planner/selector iterates it to know every
available chart**, and the renderer uses it to register + build. Adding a family =
one registry entry + one builder + one scoring rule + one test. Nothing else is
hard-coded per family.

## 2. Register the full family set in the renderer

Extend `EChartsWidget`'s `echarts.use([...])` to the governed full set from
`echarts/charts` + required `echarts/components`. Target families (echarts 6.x):

- **Cartesian:** Line, Bar, Scatter, EffectScatter, Candlestick, Boxplot,
  Heatmap, PictorialBar, ThemeRiver
- **Part-to-whole / hierarchy:** Pie/Donut, Sunburst, Treemap, Tree
- **Flow / relationship:** Sankey, Funnel, Graph (network), Parallel, Lines
- **Radial / indicator:** Radar, Gauge
- **Analytical layers via** Custom + MarkLine/MarkPoint/MarkArea (bands, control
  limits, anomaly/change-point markers)
- **Geo maps:** MapChart — **gated/off by default** (needs approved basemap/geo
  data + licensing; never ship keys in specs)

Add the components each requires (VisualMap, Dataset, DataZoom, SingleAxis,
Calendar, Polar, Toolbox, Brush, Aria) — tree-shaken, only what the enabled
families need. Keep `CanvasRenderer` default. Each family gets a **builder** that
honors the existing `VisualizationOptions` (colors/theme, legend, labels, axis
format, stacking, tooltip) and degrades to the nearest supported family if data is
missing — never blank.

## 3. Data-shape ranking (deterministic) — `rank_visualizations`

In `platform-api/app/services/visualization_engine.py`:

```python
def rank_visualizations(columns, rows, *, intent_hint=None, method_envelope=None,
                        limit=6) -> list[ScoredViz]:
    """Score EVERY registered family against the data shape; return top `limit`,
    ranked, each with score + reason. Deterministic and LLM-free."""
```

- Extend `ChartType` to the full registered set (in lockstep with §1/§2).
- Keep `select_visualization(...)` as a wrapper → `rank_visualizations(...)[0]` so
  existing callers are unchanged.
- Score from the column profile (types, cardinality, time index, # measures,
  positivity, hierarchy, matrix-ness) and the analytical `method_envelope`.
  `intent_hint`/`method_envelope` **bias** scores (tie-breakers) — they never
  force an ill-fitting chart or bypass shape rules.

Scoring guide (each family's rule lives in its registry entry):

| Data shape | High-scoring families |
|---|---|
| time index + measure(s) | line, area (+bands/markers from envelope) |
| time + OHLC | candlestick |
| 1 categorical + measure | bar (horizontal when many/long labels), ranked top-N |
| 2 categoricals + measure / matrix | heatmap |
| distribution of a measure (± by group) | histogram, boxplot |
| part-of-whole | pie/donut, treemap, sunburst |
| hierarchy | treemap, sunburst, tree |
| flow / stages | sankey, funnel |
| relationships / network | graph |
| 2 measures (+3rd = size) | scatter, bubble |
| many measures across items | radar, parallel |
| single value / row | kpi |
| nothing plottable | table |

## 4. Planner access to all installed ECharts

- The analysis planner / selector receives the **full registry** (all enabled
  families + their fit rules), not a hard-coded shortlist — this is the concrete
  meaning of "planner has access to all ECharts installed."
- The deterministic ranker chooses; the LLM planner may pass an `intent_hint`
  that biases scores. Remove any path that uses the LLM's requested chart type
  **verbatim** without shape validation.

## 5. "Suggest chart" = the diverse top-6

- Surface `rank_visualizations(..., limit=6)` to the clients (a field on the
  query-preview / widget-config response, or a small endpoint).
- Wire the **"Suggest chart"** control in `WidgetConfigPanel.tsx` and the AI result
  surfaces to render the 6 as pickable options, each with its reason; picking one
  applies its family + subtype/options. Enforce **diversity** — the same family
  must not fill all six.
- Insight cards, Ask Anything, and authoring all consume the same ranking, so the
  best chart is consistent and data-shape-driven everywhere.

## 6. Tests

- `rank_visualizations` returns correctly-ordered, diverse results for canonical
  shapes (matrix→heatmap; distribution→histogram/box; hierarchy→treemap/sunburst;
  flow→sankey; time→line; OHLC→candlestick; 2-measure→scatter; multi-measure→
  radar/parallel). Deterministic across runs and row-order.
- Every enabled family renders in `EChartsWidget`, honors options, and round-trips
  through authoring + Pin/Add-to-Dashboard.
- A planner `intent_hint` biases but never forces an ill-fitting chart.
- "Suggest chart" returns 6 diverse families with reasons; selecting applies it.
- Registry lockstep test: every `ChartType` the selector can emit is registered
  and buildable (no selectable-but-unrenderable family); gated families (map) are
  off by default.
- Existing single-decision callers still work via the wrapper; existing charts
  unchanged.
- web-ui `typecheck`/`test --run`/`build`; platform-api `pytest`/`ruff`/`mypy`.

## 7. Deploy (so it shows) & land (so it isn't lost)

1. Merge this branch into the deployed lineage (PR + merge) — do not strand it.
2. **Rebuild** web-ui (`docker compose build web-ui`) — new ECharts modules are
   bundled at build time; a restart won't include them.
3. Redeploy web-ui + platform-api; clear any cached insight/widget specs so cards
   rebuild with the new ranking.
4. Verify on the live app (see DoD).

## Definition of done

- The planner/selector can choose from **all installed ECharts families** via the
  capability registry; the renderer draws every enabled family.
- Insight cards and query results show the chart that **best fits the data shape**
  (heatmaps, box/histograms, treemaps/sunbursts, sankey, radar, candlestick — not
  just line/bar/kpi/area).
- **"Suggest chart" offers the six best, diverse charts** from the same
  deterministic ranking, each with a reason.
- The LLM biases at most; selection is deterministic and reproducible.
- Renderer + selector + registry stay in lockstep; nothing existing is
  overwritten or removed; the branch is merged into the deployed lineage and
  redeployed.

## Report

The capability registry design; the families registered (with required
components) and their shape rules; the `rank_visualizations` scoring; where
"Suggest chart" is wired and proof the six are diverse; before/after screenshots
(matrix→heatmap, distribution→box/histogram, hierarchy→treemap, flow→sankey,
OHLC→candlestick); confirmation the LLM hint is a bias not an override; and
confirmation the branch is merged + redeployed (not stranded).
