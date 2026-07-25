# Devin plan: markdown-driven chart selection — DELIVERED CODE, transfer + integrate only

Repository: `lhoskins/tablescope-lh`

## ⚠️ Delivery model — read before touching anything

The core implementation is **already written, tested, and pushed** on branch
**`claude/markdown-chart-selection`** (based on `devin/r-echarts-e2e-validation`).

**STRICT RULES:**

1. **Do NOT rewrite, refactor, reformat, rename, or "improve" the delivered
   files** listed in the manifest below. Merge them as-is. If a merge conflict
   arises with newer base commits, resolve by preserving the delivered files'
   content and adapting the *surrounding* code, not the delivered code.
2. Your job is: **merge the branch, add the remaining integration described in
   Part B (with the exact before/after code given), run all tests, deploy, and
   verify.** Nothing else.
3. If you believe a delivered file has a bug, report it in the PR description —
   do not change it without listing the exact change and reason.

## Part A — Delivered code (branch `claude/markdown-chart-selection`)

All of it verified: platform catalog tests **13/13** pass; **full ai-server
suite 68/68** passes (proving the `ai.py` edits are safe); web-ui `tsc`
typecheck clean and lockstep test **4/4** passes.

| File | What it is |
|---|---|
| `platform-api/app/prompts/chart_selection_best_practices.md` | **The single source of truth.** 31 chart families, each with a fenced ```rules block (min/max dims + measures, `needs`/`excludes` traits, role mapping, subtypes, base score) plus prose guidance. `map` is gated off via `score: 0.00`. Editing this file is how chart selection is tuned from now on. |
| `ai-server/tablescope-ai-api/app/prompts/chart_selection_best_practices.md` | Mirror for the AI server (same content; keep the two in sync when editing). |
| `platform-api/app/services/chart_catalog.py` | Dependency-free parser → `ChartFamilyRule` / `ShapeSummary`; `load_chart_catalog()`, `eligible_families(shape)`, `allowed_plan_chart_types()`, `planner_guidance()`. This is what the visualization engine consumes in Part B. |
| `platform-api/tests/test_chart_catalog.py` | 13 tests incl. shape-eligibility cases (a time series must not offer gauge/radial_bar/pie/bar; single scalar → kpi first; matrix → heatmap; raw → boxplot/histogram; flow → sankey; OHLC → candlestick; gated map never eligible). |
| `ai-server/.../app/services/chart_catalog.py` | Slim planner-side parser: `allowed_plan_chart_types()` (54 values = 31 families + subtypes + legacy aliases `kpi_grid/dual_line/bullet/sparkline_table/none`), `plan_chart_type_enum()`, `planner_chart_digest()` (compact 1-line-per-family guide, deliberately small for bounded num_ctx). Fails open to the historical core set if the markdown is missing. |
| `ai-server/.../app/routers/ai.py` (3 surgical edits) | The hard-coded 21-value `_ALLOWED_PLAN_CHART_TYPES` frozenset → `chart_catalog.allowed_plan_chart_types()`; the hard-coded `"chart_type": "kpi_grid|line|…|none"` prompt enum → `plan_chart_type_enum()`; the per-family digest injected into the plan prompt. Unknown proposals now only snap to "bar" when genuinely outside the whole catalog (garbage), with an info log. |
| `ai-server/.../tests/test_chart_catalog.py` | 4 tests (vocabulary from markdown, sorted enum, digest size, fail-open). |
| `web-ui/lib/visualizations/chartCatalogLockstep.test.ts` | **The drift guard:** every markdown family must be renderable (registry key, alias, or subtype parent via its `SUBTYPE_RESOLUTION` map: waterfall→bar, bubble→scatter, histogram→bar, calendar_heatmap→heatmap, bump→line), and every registry family must be documented in the markdown. |

Net effect already achieved by Part A: the planner can propose **any of the 31
families** (boxplot, sankey, candlestick, sunburst, theme_river, …) and they
survive planning instead of being snapped to "bar".

## Part B — Integration work for Devin (exact before/after)

### B1. `visualization_engine.py` consumes the catalog (platform-api)

Goal: family eligibility comes from `chart_catalog` rules, not inline branches.
Bounded change — do it as a **filter + extension layer** around
`recommend_visualizations`, not a rewrite:

**(1) Build a `ShapeSummary` from the existing `_Shape`** (add near
`derive_shape`):

```python
from app.services.chart_catalog import ShapeSummary, eligible_families

def _catalog_shape(shape: _Shape, dict_rows: list[dict[str, Any]], roles: dict[str, Any]) -> ShapeSummary:
    dims = [c for c in shape.dimensions if not _is_period_dimension(shape, c)]
    traits: set[str] = set()
    if shape.time_columns:
        traits.add("time")
    if shape.dimensions and not dims:
        traits.add("period_only_dimension")
    if shape.row_count == 1 and not shape.dimensions:
        traits.add("single_row")
    if roles.get("rate"):
        traits.add("rate")
    if roles.get("source") and roles.get("target"):
        traits.add("flow")
    if roles.get("parent") or (len(dims) >= 2 and _looks_hierarchical(dict_rows, dims)):
        traits.add("hierarchy")
    if _has_ohlc_roles(roles):
        traits.add("ohlc")
    if shape.row_count > max(20, 2 * max((_cardinality(shape, d) for d in dims), default=1)):
        traits.add("raw")  # plausibly unaggregated rows
    if any(_has_negative(dict_rows, m) for m in shape.measures):
        traits.add("negative_values")
    return ShapeSummary(dims=len(dims), measures=len(shape.measures), traits=frozenset(traits))
```

(`_looks_hierarchical`, `_has_ohlc_roles`, `_cardinality`, `_has_negative` are
small helpers — implement against the existing `_Shape`/roles structures. If a
trait can't be detected cheaply, omit it: rules that `needs` it simply won't
fire, which is safe.)

**(2) At the end of `recommend_visualizations`, filter by catalog eligibility**
(this becomes the final authority over every inline branch):

```python
# BEFORE (end of recommend_visualizations):
    return _diverse_top_n(candidates, limit)

# AFTER:
    catalog_ok = {r.family for r in eligible_families(_catalog_shape(shape, dict_rows, roles))}
    candidates = [
        c for c in candidates
        if c.decision.chart_type.value in catalog_ok
        or c.decision.chart_type.value == "table"  # universal fallback stays
    ]
    return _diverse_top_n(candidates, limit)
```

This makes the markdown the hard gate: an inline branch can still propose a
family, but only catalog-eligible families survive. (The inline branches become
score/role providers; dissolving them into pure catalog scoring is a later
cleanup — do NOT attempt that larger rewrite in this PR.)

**(3) Add catalog-only candidates the inline code never proposes** (so new
markdown families surface without code): after the filter, for any
`eligible_families(...)` entry with `rule.score >= 0.5` not already among the
candidates, append `_candidate(ChartType(rule.family), rule.score,
reason=rule.guidance.split(".")[0])` **only if** `rule.family` is a valid
`ChartType` member. Extend the `ChartType` enum with any markdown family it
lacks (`sunburst`, `tree`, `graph`, `parallel`, `lines`, `candlestick`,
`boxplot`, `pictorial_bar`, `theme_river`, `map`, `histogram`,
`calendar_heatmap`, `waterfall`, `bump`, `bubble`, `effect_scatter` — check
current members first; several were added by PR #90's lockstep work).

Tests: extend `test_visualization_engine.py` — a time-series shape yields no
gauge/radial_bar/pie candidates (now catalog-enforced); a flow shape yields
sankey; a fixture family added to a monkeypatched markdown becomes eligible with
no Python change (`monkeypatch` `load_prompt_reference`).

### B2. `home_intelligence._shape_template_insights` reads the catalog

Replace the hard-coded six-family template list with iteration over
`eligible_families(...)` for each probed table, keeping the existing per-family
SQL builders as a dispatch map (`_TEMPLATE_BUILDERS: dict[str, Callable]`) —
new families appear in "Deeper analysis" when (a) the markdown declares them
eligible and (b) a builder exists; the every-card-renders invariant from PR #92
keeps unknown ones visible. Do not remove any currently working template
builder.

### B3. Business-Insight page: remove the outer scrollbar

Exactly one scroll owner — the app-shell `<main className="flex-1
overflow-y-auto">` (`app-shell.tsx:66`). Find what makes the document/body
scrollable on `web-ui/app/business-insight/page.tsx` (content escaping the
`h-screen` flex column at `app-shell.tsx:46`) and remove it. Re-verify: all
panels expanded → one scrollbar → last card fully reachable; Home unaffected.

### B4. Land + deploy + verify (the step that keeps getting missed)

1. Merge `claude/markdown-chart-selection` into your integration branch, add
   B1-B3, PR into `devin/r-echarts-e2e-validation` (or the current deployed
   lineage), merge.
2. Full suites: platform-api `pytest`/`ruff`/`mypy`; ai-server `pytest`
   (all 68+ must stay green); web-ui `typecheck`/`test --run`/`build`
   (lockstep test included).
3. Deploy: **rebuild** web-ui + ai-server + platform-api images; restart.
4. **Clear insight caches** (Clear-cache buttons or script) so cards regenerate
   through the new vocabulary.
5. Verify live: the plan prompt contains the digest + wide enum (log check); a
   distribution-shaped result offers boxplot/histogram; a time series offers no
   gauge/radial_bar; new families render via ECharts.

## Definition of done

- `claude/markdown-chart-selection` merged **unmodified** (any deviation listed
  explicitly in the PR).
- B1-B3 implemented per the given diffs; the catalog is the hard eligibility
  gate; chart-family names in platform-api/ai-server appear only in the
  markdown, the `chart_catalog` modules, renderer builders/registry, template
  builders, and tests — no enums or per-family `if` gates elsewhere.
- All suites green; deployed; caches cleared; live verification screenshots
  (suggestion modal for a time series and for a distribution; a new-family card
  rendering).

## Report

Confirmation the delivered files are byte-identical to the branch (or the exact
deviations + reasons); the B1/B2 diffs as landed; the scrollbar root cause; test
totals per suite; deploy + cache-clear confirmation; live screenshots.
