# Devin fix: shape-template cards are generated but silently invisible (feed bucket filter)

Repository: `lhoskins/tablescope-lh`
Base: `devin/r-echarts-e2e-validation` (contains merged PR #89 shape templates +
PR #90 all-31-families). Feature branch: `devin/fix-shape-card-buckets`.
Small, surgical PR — the heavy lifting is done; this connects the last wire.

## Root cause (verified — do not re-derive)

PR #89/#90 work end-to-end on the backend: `_shape_template_insights`
(`home_intelligence.py`) generates radar/heatmap/treemap/sankey/funnel/scatter
cards; `routes/home_intelligence.py:212` (`_run_for_project`) appends them after
the LLM cards; the worker cache-fill (`refresh_business_insight_result` →
`hir._run_for_project`) stores them in `business_insight_results`; PR #90's
renderer can draw them.

**But the Business-Insight feed renders exactly three buckets**
(`web-ui/components/tablescope/home/intelligence-feed.tsx` ~lines 479-495):

```ts
risks         = insightType.startsWith("risk_") || severity critical/urgent/warning
trends        = insightType.startsWith("trend_") && !risks
opportunities = (insightType.startsWith("opportunity_") || severity === "opportunity") && !risks && !trends
```

Shape cards carry `insight_type: "shape_radar" | "shape_heatmap" |
"shape_treemap" | "shape_sankey" | "shape_funnel" | "shape_scatter"` — they match
**no bucket** and are silently dropped client-side. Cards are generated, cached,
sent to the browser, and never rendered. The Project-Insight screen has the same
pattern (`project_insight_service._card_group` maps only
`risk*`/`trend*`/`opportunity*` and returns `None` otherwise).

## Fix (both ends — belt and suspenders)

### 1. Backend: give shape cards an explicit display group

In `_shape_template_insights` (`home_intelligence.py`), add a `group` (or
`category`) field to every generated card — e.g. `"group": "analysis"` — and map
each shape type sensibly if a finer split is wanted (scatter/heatmap → analysis;
funnel → opportunities is acceptable if justified). Do **not** rename the
`shape_*` insight_type values (they are persisted in caches/feedback keys); add
the group field alongside. Mirror the same for any project-insight shape cards:
`_card_group` must return a real group for `shape_*` types instead of `None`.

### 2. Frontend: add a catch-all fourth bucket — no card may ever be invisible

In `intelligence-feed.tsx`, after computing `risks`/`trends`/`opportunities`,
compute:

```ts
const analysis = allInsights.filter(
  (c) => !risks.includes(c) && !trends.includes(c) && !opportunities.includes(c),
);
```

Render it as a fourth section — heading **"Deeper analysis"** — using the exact
same `IntelligenceCard` rendering (same buttons, feedback, badges, Add to
dashboard). Cards with the backend `group === "analysis"` land here by design;
**any** future card whose type matches no prefix also lands here instead of
vanishing. Apply the equivalent catch-all to the Project-Insight screen's
grouping so `shape_*` project cards render too.

### 3. Tighten the radar period-subject fallback

In `_shape_template_insights`, the dims fallback
(`if not dims: dims = shape.dimensions[:]`) lets the **period column** become the
radar subject on period-only tables (a shape-wrong radar). Change: if the only
dimension is period-like, **skip the radar template** for that table (the
line/combo families already cover time × measures). Keep radar for genuinely
categorical subjects.

### 4. Clear caches + verify visible

- Clear the Business-Insight cache and project-insight snapshots (the tenant
  Clear-cache endpoint/button if landed, else
  `scripts/delete_insight_caches.py`) so cards regenerate with the group field.
- Deploy (rebuild web-ui — the feed change is client code) and verify on
  https://app.tablescope.cloud/: the Business-Insight page shows a **Deeper
  analysis** section containing scatter/radar/heatmap/etc. cards rendered by
  ECharts; existing risk/trend/opportunity sections unchanged.

## Tests

- **The invariant that would have caught this:** a feed/component test asserting
  **every card in the API payload renders in exactly one bucket** — feed a list
  containing `risk_x`, `trend_x`, `opportunity_x`, `shape_scatter`, and an
  unknown `future_type`; assert all five appear in the DOM and the last two are
  in "Deeper analysis". This regression test is mandatory.
- Backend: shape cards carry `group: "analysis"`; project `_card_group` returns a
  group for `shape_*`; radar template skipped when the only dimension is
  period-like.
- Existing three buckets unchanged for prefixed types; severity-based risk
  routing intact.
- web-ui `typecheck`/`test --run`/`build`; platform-api `pytest`/`ruff` green.

## Definition of done

- Shape-template cards (scatter/radar/heatmap/treemap/sankey/funnel) are visible
  on the Business-Insight page under "Deeper analysis", rendered via ECharts,
  with full card actions (Explain, Chart suggestion, feedback, Add to dashboard).
- Project-Insight page renders its shape cards too.
- The every-card-renders invariant test is green — no silently dropped cards,
  ever again.
- Caches cleared, deployed, and verified live; branch merged into the deployed
  lineage (not stranded).

## Report

The group-field diff, the fourth-bucket diff (both feeds), the radar-fallback
change, the invariant test, cache-clear + deploy confirmation, and a screenshot
of the live "Deeper analysis" section showing non-line/bar chart families.
