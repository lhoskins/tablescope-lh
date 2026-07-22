# Devin prompt: ECharts default rollout — full renderer migration + authoring (styles & chart options)

Repository: `lhoskins/tablescope-lh`
Base branch: **`devin/r-catalog-activation-ui`** (latest deployed R lineage;
re-verify if merged). Feature branch: `devin/echarts-default-rollout`.

## Objective

Make **Apache ECharts the sole renderer** for every chart surface — dashboards,
Business Insight cards, Home pins — and give the widget/dashboard **authoring UI**
full ECharts style and chart-option controls. **Test mode: no backward
compatibility is required.** Recharts is being retired; once ECharts covers all
types, remove recharts entirely.

Because there is **no recharts fallback**, ECharts must cover **every** widget
type the app can render before recharts is removed, or those widgets blank. Cover
first, verify no blanks, then remove recharts (Workstream 5). Do not remove
recharts before coverage is complete.

## Current state (verified on base)

- One render path: `web-ui/components/dashboard/WidgetRenderer.tsx` is used by the
  dashboard grid, insight cards (`intelligence-card.tsx` `InsightChartView`,
  ~line 127), and Home pins (`home-pins-grid.tsx`, ~line 233).
- ECharts is gated today: `WidgetRenderer.tsx:377` uses ECharts only for
  `["line","bar","pie","area"]` when `shouldRenderEcharts(...)` is true;
  everything else renders recharts. `web-ui/lib/echarts.ts` holds the mode gate;
  `EChartsWidget.tsx` is the current (partial) ECharts renderer.
- The full type universe (`web-ui/components/dashboard/types.ts`): **WidgetType** =
  `kpi, line, bar, area, pie, table, combo, scatter, radar, radial_bar, treemap,
  funnel, sankey`; **ChartSubtype** includes column, stacked_bar, grouped_bar,
  horizontal_bar, stacked_horizontal, positive_negative, waterfall,
  population_pyramid, smooth_line, step_line, dashed_line, biaxial_line, tiny_line,
  animated_line, stacked_area, donut, two_level, gauge, bar_line, dual_line,
  bubble. `VisualizationOptions` includes `renderer`, `stackMode`, `curveType`,
  `lineStyle`, `labelMode`, `barLayout`, `showLegend`, `showGrid`, `innerRadius`,
  reference lines, etc.
- Authoring is two components + a registry: `WidgetConfigPanel.tsx` (chart
  type/subtype picker `CHART_TYPES`, columns, filters, interactions) and
  `ChartOptionsPanel.tsx` (a **registry-driven** editor that renders the option
  fields declared for the active type in `web-ui/lib/visualizations/chartRegistry.ts`).
- `NEXT_PUBLIC_ECHARTS_RENDERER_MODE` is build-time inlined (Dockerfile ARG/ENV +
  compose `build.args`, default `default`); web-ui must be **rebuilt** (not
  restarted) for changes.

## Full chart-surface coverage (verified — this is why one migration suffices)

`WidgetRenderer` is the **single chokepoint** for chart rendering in the entire
app. Migrating it to ECharts covers every surface. Confirmed entry points:

| Surface | Path to WidgetRenderer |
|---|---|
| Dashboards (view) | `web-ui/components/dashboard/DashboardViewer.tsx` → WidgetRenderer |
| Widget authoring **live preview** | `WidgetConfigPanel.tsx` → WidgetRenderer |
| Business Insight / Home cards | `intelligence-card.tsx` `InsightChartView` → WidgetRenderer |
| Home pins | `home-pins-grid.tsx` → WidgetRenderer |
| Ask Anything / AI responses | `ResponsePresenter.tsx` → `ResultChart` (`ai-result-view.tsx`) → `InsightChartBlock` (`intelligence-card.tsx`) → WidgetRenderer |
| Generate-Query preview | `GenerateQueryPreviewModal.tsx` → `ResultChart` → WidgetRenderer |
| Query-suggestion preview | `query-suggestion-preview-modal.tsx` → `ResultChart` → WidgetRenderer |

**Only recharts import outside `WidgetRenderer`:**
`web-ui/components/charts/SimpleLineChart.tsx` — and it is **unused dead code**
(no importers). Delete it as part of the recharts removal; nothing else needs
migrating. After `WidgetRenderer` is migrated and `SimpleLineChart.tsx` is
deleted, a repo-wide `grep -r "recharts"` must return **zero** matches (outside
`package.json` removal) — that is the coverage proof.

---

## Workstream 1 — ECharts renders every widget type + subtype

Implement complete ECharts coverage in `EChartsWidget.tsx` (split into per-family
builder modules if it grows large). Each must honor the relevant
`VisualizationOptions`/`chartSubtype`:

- **kpi / kpi_grid** → route to the existing KPI component (not a canvas chart).
- **table** → route to the existing table component.
- **line**: `smooth_line`, `step_line`, `dashed_line`, `biaxial_line`(dual axis),
  `tiny_line`(sparkline), `animated_line`; honor `curveType`, `lineStyle`.
- **bar**: `column`, `stacked_bar`, `grouped_bar`, `horizontal_bar`,
  `stacked_horizontal`, `positive_negative`(color by sign), `waterfall`(running
  cumulative), `population_pyramid`(mirrored); honor `stackMode`, `barLayout`.
- **area**: `stacked_area`; honor stacking + opacity.
- **pie**: `donut`(innerRadius), `two_level`(nested ring), `gauge`(semi-circle).
- **combo**: `bar_line`, `dual_line` (bars/line + secondary y-axis).
- **scatter**: plain + `bubble` (size dimension).
- **radar**, **radial_bar**, **treemap**, **funnel**, **sankey**.

For each type: honor `showLegend`, `showGrid`, data labels (`labelMode`), axis
config, and existing **reference lines**. Preserve click→filter/drilldown via the
current TableScope event adapter (`normalizeCartesianClick`/`normalizePieClick`
equivalents). No type may render blank — if data is missing, show the existing
no-data state.

## Workstream 2 — Make ECharts the sole renderer

- In `WidgetRenderer.tsx`, route **all** chart types to the ECharts path (kpi and
  table to their components). Remove the per-type recharts branches once
  Workstream 1 covers every type.
- Simplify the gate: since ECharts is universal, drop the
  `shouldRenderEcharts`/`NEXT_PUBLIC_ECHARTS_RENDERER_MODE` mode logic and the
  `renderer` conditional (test mode — no dual renderer). Either remove the
  `visualizationOptions.renderer` field or make it always resolve to echarts.
- **Retire recharts**: remove `recharts` imports from `WidgetRenderer.tsx`,
  **delete the unused `web-ui/components/charts/SimpleLineChart.tsx`** (the only
  other recharts importer — dead code), drop `web-ui/lib/echarts.ts` mode gating,
  and remove `recharts` from `web-ui/package.json`. Do this **last**, after
  Workstreams 1 & 3 verify no widget blanks. Proof: repo-wide `grep -r "recharts"`
  returns zero matches.

## Workstream 3 — Authoring: ECharts styles & chart options (required)

The authoring UI must drive ECharts, and expose the styles/options ECharts
enables.

1. **Honor every existing option in ECharts.** Every field `ChartOptionsPanel`
   can set (from `chartRegistry.ts` `def.options`) must actually affect the
   `EChartsWidget` render: `stackMode`, `curveType`, `lineStyle`, `labelMode`,
   `barLayout`, `showLegend`, `showGrid`, `innerRadius`, reference lines, etc. An
   authoring control that does nothing is a bug.
2. **Extend `chartRegistry.ts`** with ECharts-capable style/option definitions so
   they appear automatically in the registry-driven `ChartOptionsPanel`
   (grouped). Add, per applicable type: color **palette/theme** selection and
   per-series color; **data labels** (show/position/format); **axis** controls
   (min/max, number vs currency vs percent, precision, label rotation); **legend**
   position; **tooltip** on/off/shared; **smoothing**/area opacity; **stacking**;
   **dataZoom**; and the analytical **layers** (reference line, confidence /
   prediction band, regression line, anomaly / change-point / control-limit
   markers) as reviewed, first-party option templates — never free-form
   ECharts-option or JS/HTML input.
3. **`WidgetConfigPanel` `CHART_TYPES`**: keep the type/subtype picker; ensure
   every `WidgetType` (including `sankey`, `radial_bar`, `treemap`, `funnel`) and
   every subtype is present and maps to a working ECharts render. Add any missing
   entries.
4. **Theme**: use TableScope design tokens for color/typography/grid, positive-
   negative polarity, warning/severity; support light/dark without reload.
5. **Round-trip**: options set in the panel persist in
   `visualizationOptions`, are honored by `EChartsWidget`, and survive
   save / Pin to Home / Add to Dashboard. Keep the sanitized-spec discipline —
   the panel selects from typed controls; no raw ECharts option, function, or
   HTML is ever accepted or persisted.

## Workstream 4 — Pin to Home & Add to Dashboard

- **Pin to Home** (`home-pins-grid.tsx` + `web-ui/lib/api/home-pins.ts`
  `createHomePin`, `pin_type:"live_widget"`) and **Add to Dashboard**
  (`save-insight-to-dashboard-modal.tsx`, widget payload ~lines 100-102 posting to
  `/api/projects/{id}/dashboards`): persist the full widget config including its
  `visualizationOptions` (styles/options) so the pinned/added widget renders
  identically in ECharts on reload. With recharts gone the `renderer` field is
  moot; do not gate on it.
- Confirm the backend dashboard/home-pin persistence round-trips
  `visualizationOptions` (stored in the widget JSON) and does not drop unknown
  keys.

## Workstream 5 — Behavior, performance, accessibility, tests

- Lifecycle: init/dispose once per container, update options without recreating,
  `ResizeObserver` resize (debounced during drag), remove listeners on cleanup,
  no instance/listener leaks on move/resize/unpin/replace.
- Accessibility: ECharts ARIA description + an accessible data-table fallback;
  never encode meaning by color alone; keyboard-accessible controls for the
  actions you enable.
- Performance: bundle only approved tree-shaken ECharts modules (no
  `import * as echarts`); budgets for initial render / update / resize / memory on
  dashboards of 4/12/24 widgets.
- **Sequencing gate:** do not remove recharts until an inventory test confirms
  every `WidgetType` + subtype renders in ECharts with no blanks.
- Tests: every type + subtype renders (snapshot/interaction); each authoring
  option measurably changes the ECharts option; authoring round-trips through
  save/pin/add; Pin/Add persist styles; resize/tooltip/theme/cleanup;
  click→filter/drilldown; and a "recharts fully removed" check (repo-wide
  `grep -r "recharts"` returns zero, dependency dropped from `package.json`).
- **Every-surface smoke check** (from the coverage table): a chart renders in
  ECharts on a dashboard (`DashboardViewer`), the authoring live-preview
  (`WidgetConfigPanel`), an insight card, a Home pin, an Ask Anything response,
  and a Generate-Query preview — none blank.

## Definition of done

- Every dashboard, insight card, and Home pin renders via ECharts; no chart type
  blanks; recharts is removed from the codebase and `package.json`.
- The authoring UI (`WidgetConfigPanel` + `ChartOptionsPanel` + `chartRegistry`)
  lets a user pick any chart type/subtype and set styles/options that visibly
  affect the ECharts render, using typed controls only (no raw option/JS/HTML).
- Pin to Home and Add to Dashboard persist the full ECharts widget config
  (type + styles + options) and reload identically.
- Resize, theme (light/dark), tooltip, cleanup, click→filter/drilldown, a11y, and
  performance budgets pass. web-ui `typecheck` / `test --run` / `build` green.

## PR summary must include

Base/branch; the full type+subtype coverage matrix (what renders in ECharts);
the recharts-removal diff (imports + `package.json`); the `chartRegistry` option
additions and how they map to ECharts; screenshots of the authoring panel driving
several chart types with styles applied, and of a dashboard, an insight card, and
a pinned widget rendered in ECharts; test results including the no-blank inventory
and the recharts-removed check.
```
