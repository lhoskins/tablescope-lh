# Chart selection best practices

This file is the single source of truth for chart-family selection across
TableScope. The LLM planner receives the prose guidance; the deterministic
visualization engine parses each family's fenced `rules` block to validate and
rank proposals against the actual data shape. **The LLM proposes; the data shape
disposes.** Editing this file is the only step needed to tune chart selection —
never hard-code family names or eligibility in application code.

Rules-block schema (one fenced ```rules block per family):

- `family` — stable id, must match the renderer registry.
- `min_dims` / `max_dims` — categorical (non-period) dimensions required.
- `min_measures` / `max_measures` — numeric measures required.
- `needs` — special shape requirements, comma-separated:
  `time` (ordered period axis), `raw` (unaggregated rows), `flow`
  (source/target pairs), `hierarchy` (parent/child or path), `ohlc`
  (open/high/low/close), `single_row`, `rate` (0..1 or 0..100 measure).
- `excludes` — disqualifiers: `period_only_dimension` (the only dimension is a
  time period), `time` (must NOT be a time series), `negative_values`.
- `roles` — how columns map onto the chart: comma-separated `role=kind` pairs
  (kinds: `dimension`, `dimension2`, `measure`, `measure2`, `size`, `time`,
  `open`, `high`, `low`, `close`, `source`, `target`, `value`, `stage`,
  `parent`, `child`).
- `subtypes` — allowed style variants.
- `score` — base fit score 0..1 when eligible (ranker adds shape bonuses).

---

## kpi

```rules
family: kpi
min_dims: 0
max_dims: 0
min_measures: 1
needs: single_row
roles: value=measure
score: 0.95
```

A single headline number. Use for one-row scalar summaries (a total, a rate, a
latest value). Never use when there is a series or breakdown to show.

## table

```rules
family: table
min_dims: 0
min_measures: 0
roles:
score: 0.10
```

Detail rows. The universal fallback when no chart communicates the shape, when
there is no numeric measure, or when exact values matter more than the pattern.

## line

```rules
family: line
min_dims: 0
min_measures: 1
needs: time
roles: x=time, y=measure
subtypes: smooth_line, step_line, dashed_line, tiny_line, bump
score: 0.90
```

The default for a measure over an ordered time axis. Use `bump` for rank
positions over time. Prefer over bar when periods exceed ~8. Add
confidence/prediction bands from analytical evidence when available.

## area

```rules
family: area
min_dims: 0
min_measures: 1
needs: time
roles: x=time, y=measure
subtypes: stacked_area, gradient_area
score: 0.80
```

Cumulative or volume feel over time. `stacked_area` when several series share a
whole; avoid stacking rates or negative values.

## combo

```rules
family: combo
min_dims: 0
min_measures: 2
needs: time
roles: x=time, y=measure, y2=measure2
subtypes: bar_line, dual_line
score: 0.85
```

Two measures on a shared time axis, especially with different units/scales
(volume as bars + rate as line, `dual_line` for two rates).

## bar

```rules
family: bar
min_dims: 1
min_measures: 1
roles: x=dimension, y=measure
subtypes: column, stacked_bar, grouped_bar, horizontal_bar, stacked_horizontal, positive_negative, population_pyramid
score: 0.85
```

Category comparison. Auto-horizontal when labels are long or categories exceed
~8; rank and cap very long tails. `positive_negative` colors by sign;
`population_pyramid` mirrors two groups. A time axis is not a category —
do not use ranked/stacked category bars on periods.

## waterfall

```rules
family: waterfall
min_dims: 1
min_measures: 1
roles: x=dimension, y=measure
excludes: period_only_dimension
score: 0.60
```

Running cumulative contribution from a start value to an end value (bridge
analysis, contribution-to-change). Categories must be ordered stages or
contributors, not arbitrary labels.

## pictorial_bar

```rules
family: pictorial_bar
min_dims: 1
min_measures: 1
excludes: period_only_dimension
roles: x=dimension, y=measure
score: 0.30
```

Decorative bar variant for small, presentation-oriented category counts. Never
prefer over plain bar for analysis; low base score by design.

## pie

```rules
family: pie
min_dims: 1
min_measures: 1
excludes: period_only_dimension, negative_values
roles: category=dimension, value=measure
subtypes: donut, two_level, rose
score: 0.70
```

Part-of-whole for a *small* number (≤7) of non-negative categories summing to a
meaningful total. Beyond ~7 slices use bar or treemap instead.

## sunburst

```rules
family: sunburst
min_dims: 2
min_measures: 1
needs: hierarchy
excludes: period_only_dimension
roles: parent=dimension, child=dimension2, value=measure
score: 0.65
```

Nested part-of-whole across a two-plus-level hierarchy (region → plant →
line). Prefer treemap when leaf sizes matter more than ring structure.

## treemap

```rules
family: treemap
min_dims: 1
min_measures: 1
excludes: period_only_dimension, negative_values
roles: category=dimension, value=measure
score: 0.65
```

Proportional area for many categories or a hierarchy; the readable alternative
to a pie with a long tail.

## tree

```rules
family: tree
min_dims: 2
min_measures: 0
needs: hierarchy
roles: parent=parent, child=child
score: 0.45
```

Structural hierarchy without a size measure (org chart, BOM structure). Use
treemap/sunburst when a measure sizes the nodes.

## funnel

```rules
family: funnel
min_dims: 1
max_dims: 1
min_measures: 1
needs: stage
excludes: period_only_dimension
roles: stage=stage, value=measure
score: 0.60
```

Strictly ordered stages with monotonically decreasing counts (pipeline,
conversion). Do not use for arbitrary ranked categories.

## sankey

```rules
family: sankey
min_dims: 2
min_measures: 1
needs: flow
roles: source=source, target=target, value=measure
score: 0.65
```

Flow volume between two sets of nodes (material flow, order routing,
source→disposition). Requires genuine source/target pairs with magnitudes.

## graph

```rules
family: graph
min_dims: 2
min_measures: 0
needs: flow
roles: source=source, target=target
score: 0.40
```

Network relationships without flow magnitude (dependencies, associations). Use
sankey when edge volume matters.

## lines

```rules
family: lines
min_dims: 2
min_measures: 0
needs: flow
roles: source=source, target=target
score: 0.20
```

Geo/graph edge overlay (trajectories). Rare; requires coordinate-like data.

## scatter

```rules
family: scatter
min_dims: 0
min_measures: 2
needs: raw
roles: x=measure, y=measure2
score: 0.80
```

Relationship between two measures across records. The workhorse for
correlation questions; pair with a regression line from analytical evidence.

## effect_scatter

```rules
family: effect_scatter
min_dims: 0
min_measures: 2
needs: raw
roles: x=measure, y=measure2
score: 0.30
```

Scatter with ripple emphasis for highlighted points (anomalies, outliers).
Use only when specific points must draw attention; otherwise plain scatter.

## bubble

```rules
family: bubble
min_dims: 0
min_measures: 3
needs: raw
roles: x=measure, y=measure2, size=size
score: 0.70
```

Scatter with a third measure encoded as size. Cap point counts; sizes must be
non-negative.

## candlestick

```rules
family: candlestick
min_dims: 0
min_measures: 4
needs: time, ohlc
roles: x=time, open=open, high=high, low=low, close=close
score: 0.85
```

Open/high/low/close per period (finance, min/avg/max process windows). Requires
all four OHLC roles; never approximate from a single measure.

## boxplot

```rules
family: boxplot
min_dims: 0
min_measures: 1
needs: raw
roles: category=dimension, value=measure
score: 0.75
```

Distribution of a measure (median/IQR/whiskers/outliers), optionally grouped by
one category. Requires raw, unaggregated rows — never pre-aggregated averages.

## histogram

```rules
family: histogram
min_dims: 0
max_dims: 0
min_measures: 1
needs: raw
roles: value=measure
score: 0.75
```

Frequency distribution of one measure via governed binning. Requires raw rows;
choose bin count deterministically from n.

## heatmap

```rules
family: heatmap
min_dims: 2
min_measures: 1
roles: x=dimension, y=dimension2, value=measure
subtypes: calendar
score: 0.80
```

A measure across two categorical dimensions (region × product), or a
correlation matrix. Prefer over grouped bars when both cardinalities exceed ~5.

## calendar_heatmap

```rules
family: calendar_heatmap
min_dims: 0
min_measures: 1
needs: time, raw
roles: x=time, value=measure
score: 0.55
```

Daily values across weeks/months (activity, defects per day). Requires a daily
time grain; use plain line for coarser grains.

## radar

```rules
family: radar
min_dims: 1
min_measures: 3
max_measures: 8
excludes: period_only_dimension
roles: category=dimension, value=measure
score: 0.65
```

3-8 measures compared across a few (≤6) entities — a scorecard shape. Never
use a time period as the entity axis; normalize measures to comparable scales.

## parallel

```rules
family: parallel
min_dims: 0
min_measures: 4
needs: raw
roles: value=measure
score: 0.50
```

Many measures per record across many records (multivariate profiles). The
raw-row sibling of radar; cap rows and highlight selections.

## radial_bar

```rules
family: radial_bar
min_dims: 1
min_measures: 1
needs: rate
excludes: period_only_dimension, negative_values
roles: category=dimension, value=measure
score: 0.55
```

Progress-to-target rates by category on a radial axis. Only for bounded 0-100%
style measures across a small set of categories — never for time series.

## gauge

```rules
family: gauge
min_dims: 0
max_dims: 0
min_measures: 1
needs: single_row
roles: value=measure
score: 0.60
```

One bounded value against a target range. Single-value shapes only — never
collapse a series to its latest point to force a gauge.

## theme_river

```rules
family: theme_river
min_dims: 1
min_measures: 1
needs: time
roles: x=time, category=dimension, value=measure
score: 0.50
```

Composition of several categories flowing over time (stacked-stream). Needs a
time axis plus a category dimension; prefer stacked area for ≤4 categories.

## bump

```rules
family: bump
min_dims: 1
min_measures: 1
needs: time
roles: x=time, category=dimension, value=measure
score: 0.55
```

Rank positions of categories over time (league tables). Values must be
convertible to ranks per period.

## map

```rules
family: map
min_dims: 1
min_measures: 1
needs: geo
excludes: period_only_dimension
roles: category=dimension, value=measure
score: 0.00
```

Choropleth by geographic region. **Gated off by default** (`score: 0.00`) —
requires licensed basemap/geo data configured for the tenant; never assume
geography ships with the app.
