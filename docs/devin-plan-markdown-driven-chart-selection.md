# Devin plan: markdown-driven chart selection (remove all hard-coded chart lists) + Business-Insight scrollbar fix

Repository: `lhoskins/tablescope-lh`
Base: `devin/r-echarts-e2e-validation` (contains PR #89/#90/#92). Feature branch:
`devin/markdown-driven-chart-selection`.

## Why variety is still capped (verified — the remaining hard-coded chain)

All 31 families are registered (PR #90) and visible buckets exist (PR #92), yet
risks/trends/opportunities show only line/bar/KPI and Deeper analysis shows only
scatter/heatmap/comparison. The chart vocabulary is hard-coded at every decision
point:

1. **The planner prompt embeds a fixed enum** —
   `ai-server/tablescope-ai-api/app/routers/ai.py:2491` hard-codes
   `"chart_type": "kpi_grid|line|area|dual_line|scatter|bubble|bar|...|none"`
   into the LLM prompt string.
2. **Unknown types silently become bar** — `ai.py:2567-2569`:
   `if chart_type not in _ALLOWED_PLAN_CHART_TYPES: chart_type = "bar"`. Any
   richer chart the LLM proposes is collapsed to bar. This is the single biggest
   variety killer for risk/trend/opportunity cards.
3. **Shape templates are six hard-coded blocks** —
   `home_intelligence._shape_template_insights` implements exactly
   radar/heatmap/treemap/sankey/funnel/scatter as inline Python. That is why
   Deeper analysis shows only those.
4. **Per-type branches in card building** — `home_intelligence` special-cases
   types inline (`chart_type in ("line","area","combo")` at 963, scatter/bubble
   at 2191, `_TWO_VALUE_TYPES` at 2300, etc.).
5. **`visualization_engine` family rules are inline Python branches** — each
   family's eligibility is a code block, not data.

Conclusion: the user is right — chart selection must stop being code-enumerated.

## Target architecture (the ask + my recommendation)

**Single source of truth: a chart-selection best-practices markdown**, following
the existing `prompt_loader` + `*_best_practices.md` pattern already used in both
services (`ai-server/.../app/prompts/*_best_practices.md`,
`platform-api/app/prompts/*_best_practices.md`).

Create `chart_selection_best_practices.md` (one canonical copy; mirror or share
between services the same way existing best-practice files are mirrored) with
**one section per chart family** (all 31), each carrying a machine-readable
front-matter block plus prose guidance:

```markdown
## heatmap
```yaml
family: heatmap
requires: {dims: 2, measures: 1}
excludes: [period_only_dimension]
roles: {x: dimension, y: dimension, value: measure}
subtypes: [calendar]
```
Use when comparing a measure across two categorical dimensions (e.g. region ×
product). Prefer over grouped bars when both cardinalities exceed ~5. Never use
for a single time series...
```

Consumption (this is the important design decision — **advice, please keep it**):

- **The LLM planner reads the prose + family list** (via `prompt_loader`) instead
  of an inline enum — it may propose ANY family in the file, with role mappings.
- **The deterministic ranker (`visualization_engine`) reads the front-matter
  rules** (parsed once at startup) instead of inline Python branches — it
  validates/ranks the LLM's proposal and all alternatives against the actual data
  shape. **Keep this validation layer.** The markdown removes the hard-coded
  vocabulary; the shape check must remain, otherwise the LLM will put gauges on
  time series again (we have already seen the ranker's value here). LLM proposes
  from the markdown; the data shape disposes.
- **Snap-to-bar is abolished.** When a proposed type fails validation, fall back
  to the ranker's top shape-fit decision — never a hard-coded `"bar"`.

## Work items

### 1. Author `chart_selection_best_practices.md`

- All 31 registered families, each with front-matter (requires/excludes/roles/
  subtypes) + concise best-practice prose (when to use, when not to, drawn from
  the ECharts gallery vocabulary: stacked/gradient area, bump/ranking line,
  confidence band, mixed line+bar, polar bar, boxplot variants, calendar heatmap,
  candlestick, sunburst, tree, graph, parallel, themeRiver, pictorialBar, …).
- Loaded via the existing `prompt_loader` in BOTH services; add a lockstep test:
  every family in the markdown is registered in the renderer
  (`EChartsWidget`/`chartRegistry`), and every registered family appears in the
  markdown. No drift in either direction.

### 2. ai-server planner: prompt from the markdown, no enum, no snap-to-bar

- Build the plan prompt's chart guidance + allowed-type list from the loaded
  markdown (`ai.py` ~2392-2491) — delete the inline enum string.
- Replace `_ALLOWED_PLAN_CHART_TYPES` gating (~2567-2569) with
  markdown-derived membership; on unknown/failed type, defer to the platform
  ranker (emit no forced type) instead of `"bar"`.

### 3. platform-api: data-driven families, generic card building

- `visualization_engine`: parse the front-matter into the family/eligibility
  table at startup; replace the inline per-family branches with a generic loop
  over that table (shape predicates from `requires`/`excludes`, scores from fit).
  Same deterministic behavior, zero per-family code.
- `home_intelligence`: replace `_shape_template_insights`'s six inline blocks
  with a generic generator driven by the same table — for each family whose
  `requires` matches a table's probed shape, emit the templated SQL/card (role
  mapping from the front-matter `roles`). New families then appear in Deeper
  analysis by editing the markdown only.
- Collapse the per-type special cases (`_TWO_VALUE_TYPES`, the
  line/area/combo period check, scatter/bubble branch) into role-driven generic
  code keyed off the front-matter roles.
- Frontend `buildMultiDimWidget`/`chartRegistry` should already be generic per
  PR #90; verify no remaining per-family switch that would drop a family the
  markdown allows.

### 4. Editing the markdown must be the ONLY step to tune selection

Acceptance for the refactor: adding/removing/re-scoping a chart family or
changing its guidance requires **editing `chart_selection_best_practices.md`
only** — no Python/TS chart-name changes anywhere (renderer builder must already
exist; the lockstep test enforces that pairing).

### 5. Business-Insight page: remove the outer scrollbar

The page currently shows a second (outer/window) scrollbar in addition to the
app-shell's `main` scroller. Exactly **one** scroll container may own vertical
scrolling — the app-shell `<main className="flex-1 overflow-y-auto">`
(`app-shell.tsx:66`). Find what makes the document/body taller than the viewport
on `web-ui/app/business-insight/page.tsx` (the `h-screen` shell is at
`app-shell.tsx:46`; look for content escaping the flex column, margins collapsing
outside, or a fixed-height element exceeding the shell) and eliminate the outer
scrollbar. Re-verify the earlier requirement: with all panels expanded, the single
scrollbar reaches the last card; no clipped content; Home and other shell pages
unaffected.

### 6. Regenerate + verify variety

- Clear insight caches (Clear-cache button/endpoint or script) and regenerate.
- Expected live outcome: risk/trend/opportunity cards can carry any
  shape-eligible family the planner proposes (stacked/area/combo/bands where the
  data fits), and Deeper analysis grows beyond scatter/heatmap/comparison as
  families match probed shapes (boxplot for distributions, sunburst/tree for
  hierarchies, candlestick for OHLC, etc.).
- **Honest bound (state it in the PR):** variety remains limited by actual data
  shapes — monthly label/value sources will still legitimately produce
  line/bar/KPI; the win is that nothing in code caps the vocabulary anymore.

## Tests

- Lockstep: markdown families ⇄ renderer registry (both directions).
- Planner: prompt contains the markdown-derived family guidance; a plan proposing
  `boxplot` with valid roles survives (no snap-to-bar); an invalid proposal falls
  back to the ranker's shape-fit choice, not `"bar"`.
- Ranker: behavior driven from front-matter — a family added to the markdown with
  matching shape rules becomes eligible with **no Python change** (test with a
  fixture family); time-series exclusions still enforced (`excludes:
  period_only_dimension`).
- Shape templates: generic generator emits a card for every family whose
  `requires` matches a fixture table; the six previous families still work.
- Scrollbar: business-insight page has exactly one vertical scroll container;
  last card reachable with panels expanded.
- Full suites green (platform-api pytest/ruff/mypy; web-ui typecheck/test/build).

## Definition of done

- Zero hard-coded chart-type lists/enums/branches remain in ai-server planner,
  `visualization_engine`, `home_intelligence` card/template building (grep proof:
  chart family names appear only in the markdown, the renderer builders, and the
  registry).
- The LLM/planner receives its chart guidance from
  `chart_selection_best_practices.md`; deterministic shape validation retained;
  snap-to-bar removed.
- Deeper analysis and the three main buckets show additional families wherever
  data shape supports them (live screenshots after cache clear).
- One scrollbar on the Business-Insight page.
- Merged into the deployed lineage + rebuilt/redeployed (not stranded).

## Report

The markdown file (all 31 sections); grep proof no chart-name enums/branches
remain outside markdown/renderer/registry; the planner-prompt diff (enum removed,
markdown injected); the generic ranker/template loops; scrollbar root cause +
fix; cache-clear + live screenshots of new families in each bucket; the honest
data-shape bound restated with the per-source audit numbers if available.
