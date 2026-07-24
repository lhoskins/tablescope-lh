# Devin prompt: data-shape chart ranking — many best-fit ECharts charts + top-6 suggestions

Repository: `lhoskins/tablescope-lh`
Base: the integrated R/ECharts branch (`devin/r-echarts-integration` or its merged
successor). Feature branch: `devin/chart-selection-data-shape-ranking`.

## Problem (researched — this is why you only see line/bar/kpi/area)

1. **Renderer covers ~13 families, not 31.** `EChartsWidget.tsx` wires Line, Bar,
   Pie, Scatter, Radar, Treemap, Funnel, Sankey, Gauge (+ subtypes). The richer
   ECharts families (heatmap, boxplot, histogram, candlestick, sunburst,
   graph/network, parallel, themeRiver, pictorialBar…) are **not** implemented.
2. **The selector is capped and narrow.** `visualization_engine.py` `ChartType`
   is exactly the 13 `WidgetType` families ("MUST stay in lockstep with
   `WidgetType`"), and `select_visualization` heuristics map almost every shape to
   **line/area/bar/pie/scatter/combo/kpi**. Radar/treemap/funnel/sankey/gauge are
   renderable but rarely or never *selected*.
3. **There is no ranking.** `select_visualization` returns a **single**
   `VizDecision`. There is no `rank_visualizations`, no top-N, no
   suggest-charts path — so "Suggest chart" has no diverse set to offer and
   repeats the same family.
4. **Wrong direction: "planner requests the chart."** `select_visualization`
   takes an `intent_hint` (the LLM/planner's chart request) and snaps it to the 13
   families. Delegating chart choice to the LLM homogenizes output and ignores the
   data shape. The LLM should identify the *question*; the deterministic engine
   should choose the *chart(s)* from the data shape.

## Direction (what to build instead)

Make chart selection a **deterministic, data-shape-driven ranking over the full
ECharts family set**, and drive both the primary chart and the "suggest charts"
feature from the **same** ranking. The LLM identifies the question and explains
the result; it does not pick the chart.

### 1. Rank, don't pick — `rank_visualizations`

In `platform-api/app/services/visualization_engine.py`, add:

```python
def rank_visualizations(columns, rows, *, intent_hint=None, method_envelope=None,
                        limit=6) -> list[ScoredViz]:
    """Score EVERY applicable chart family against the data shape and return the
    best `limit`, ranked. Deterministic and LLM-free."""
```

- `ScoredViz` = `VizDecision` + `score: float` + `reason: str`.
- Keep `select_visualization` as a thin wrapper returning `rank_visualizations(...)[0]`
  so existing callers keep working.
- `intent_hint` and `method_envelope` are **biases/tie-breakers** (nudge scores),
  never hard overrides. A planner hint may raise a family's score; it cannot force
  an ill-fitting chart or bypass the shape rules.

### 2. Expand the family vocabulary (selector + renderer, in lockstep)

Grow `ChartType` and `EChartsWidget` coverage toward the fuller ECharts set, each
with (a) a renderer builder, (b) a data-shape scoring rule, (c) a test. Target
families beyond today's 13:

- **heatmap** (two categoricals + measure / correlation matrix)
- **boxplot** (distribution of a measure, optionally by group)
- **histogram** (distribution of one measure — binning transform + bar)
- **sunburst** (hierarchy / nested part-of-whole)
- **candlestick** (OHLC time series) — when the shape has open/high/low/close
- **graph/network**, **parallel**, **themeRiver**, **pictorialBar** — gate behind
  clear shape rules; only add a family when a real business shape maps to it.

Do not add a family the renderer can't draw. Keep `ChartType`, `WidgetType`,
`chartRegistry`, and `EChartsWidget` synchronized (the existing lockstep contract).

### 3. Data-shape scoring rules (deterministic)

Score each family from the column profile (types, cardinality, time index, #
measures, positivity, hierarchy, matrix-ness) and the analytical method envelope:

| Data shape | High-scoring families |
|---|---|
| ordered time index + measure(s) | line, area (bands/markers when the envelope has them) |
| time + OHLC | candlestick |
| 1 categorical + 1 measure | bar (horizontal when many/long labels), ranked top-N |
| 2 categoricals + measure / matrix | heatmap |
| distribution of 1 measure | histogram, boxplot |
| distribution by group | boxplot |
| part-of-whole | pie/donut, treemap, sunburst |
| hierarchy | treemap, sunburst |
| flow / stages | sankey, funnel |
| 2 measures | scatter, bubble (3rd measure = size) |
| many measures across items | radar, parallel |
| single value / single row | kpi |
| nothing plottable | table |

Each returned `ScoredViz` carries a human reason ("Correlation matrix → heatmap";
"Distribution of one measure → histogram/box"). Ranking is stable and
reproducible for the same input.

### 4. Suggest charts = top-6 of the ranking

- Add a suggestions surface (backend: reuse `rank_visualizations(..., limit=6)`;
  a small `GET`/inline field on the query-preview / widget-config response, or an
  endpoint if cleaner) returning the top-6 scored families with reasons.
- Wire the **"Suggest chart"** control in the widget authoring
  (`WidgetConfigPanel.tsx`) and the AI result surfaces to render these 6 as
  pickable options (each applies its family + subtype/options). They must be
  **diverse** — the same family should not fill all six.
- Insight cards, Ask Anything, and widget authoring all consume the same ranking,
  so the "best chart" is consistent everywhere and reflects the data shape.

### 5. Shrink the LLM's role in chart choice

- The analysis planner / LLM identifies the business question and explains the
  result; it may pass an `intent_hint`, but the deterministic engine ranks and
  chooses. Remove any path where the LLM's requested chart type is used
  **verbatim** without shape validation.

## Tests

- `rank_visualizations` returns a diverse, correctly-ordered set for canonical
  shapes (matrix→heatmap first; distribution→histogram/box; hierarchy→treemap/
  sunburst; flow→sankey; time→line; 2-measure→scatter). Deterministic across runs.
- Each new family renders in `EChartsWidget` and round-trips through authoring +
  Pin/Add-to-Dashboard.
- A planner `intent_hint` biases but never forces an ill-fitting chart.
- "Suggest chart" returns 6 diverse families with reasons; picking one applies it.
- Existing single-decision callers still work via the `select_visualization`
  wrapper.

## Definition of done

- Insight cards and query results show the chart that best fits the data shape,
  drawn from the **full implemented ECharts family set** — not just line/bar/kpi/
  area.
- "Suggest chart" offers the **six best, diverse** charts for the data, from the
  same deterministic ranking, each with a reason.
- The LLM no longer decides the chart; it biases at most. Selection is
  deterministic and reproducible.
- Renderer + selector + registry stay in lockstep; every selectable family is
  renderable and tested.

## Report

The families added (selector + renderer) and their shape rules; the
`rank_visualizations` scoring design; where "Suggest chart" is wired and proof the
six suggestions are diverse; before/after screenshots (a matrix→heatmap, a
distribution→box/histogram, a hierarchy→treemap, a flow→sankey); and confirmation
that the LLM hint is a bias, not an override.
