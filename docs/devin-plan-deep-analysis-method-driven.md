# Devin: Deeper analysis — method-driven, executive-grade (DELIVERED CODE)

Repository: `lhoskins/tablescope-lh`
Branch: **`claude/deep-analysis-business-value`** (this branch — the code is here)
Based on: `devin/r-echarts-e2e-validation` (already contains the merged
fit-confidence work from PR #96).

## ⚠️ Delivery model

The code is **written and tested on this branch**. Your job is to **merge, run
the full suites in CI, deploy, clear insight caches, and verify** — not to
rewrite it.

**STRICT RULES**
1. Do **not** rewrite, refactor, rename, or reformat the delivered files. Merge
   as-is. Resolve any conflict by preserving the delivered code and adapting the
   surrounding code.
2. If you believe delivered code has a bug, **report it in the PR description**
   with the exact change and reason — do not silently change it.
3. Run the two tests this container could not (`test_ask_and_run_call_site_agrees_with_engine`,
   `test_home_call_site_agrees_with_engine`) in CI — this container's
   numpy/pandas is broken, so anything importing `app.main` was excluded here.

---

## Why this was needed

**"Should we install more complex methods?" — No. You already have 29 and this
section called none of them.**

Verified on the deployed lineage:

- The catalog (v1.1) has **29 executable methods, all `execution_engine: r`**,
  and the selection matrix resolves **23 intents** — including
  `compare_year_over_year`, `compare_periods`, `compare_to_baseline`,
  `measure_rate_of_change`, `contribution_to_change`, `detect_anomalies`,
  `detect_change_point`, `forecast_time_series`, `trend_seasonality`,
  `relationship_numeric`, `compare_multiple_groups`, `continuous_prediction`.
- `_shape_template_insights` — the function behind every Deeper-analysis card —
  contained **zero** references to `analyze_methods` / `analyze()` /
  `method_envelope`.

So Deeper analysis was a **shape prober**: `SELECT * FROM <table> LIMIT 50`,
find any drawable column combination, emit a chart. No statistical method ran,
which is why the cards never felt deeper than the main feed — and why they
charted `order_id`.

---

## What is delivered (3 commits)

### 1. Identifier columns are never chart dimensions

`visualization_engine.is_identifier_column()` / `business_dimensions()`. Two
independent signals:

- **name** — `order_id`, `sku`, `ref_no`, `batch`, `invoice`, `serial`, …
- **near-uniqueness, but only beside a genuine low-cardinality dimension.**
  This guard is load-bearing: an *aggregated* result has one row per category by
  construction, so 8 suppliers in 8 rows (or 40 in 40) is a legitimate bar
  chart, not a key. An earlier version without it wrongly flagged `supplier`.
  Period columns are never identifiers.

Wired into `_catalog_shape` (so a key can no longer inflate the dimension count
that decides family eligibility — this is what let a 300-value id unlock
heatmaps) and into the template loop, which now **skips a table with no business
dimension** rather than falling back to keys.

### 2. Method-driven Deeper analysis with a materiality gate

New `platform-api/app/services/deep_analysis.py` — pure, no pandas/DB/LLM, so it
is fully unit-testable:

- **`plan_deep_analyses()`** — asks which governed *intents* a table's business
  columns support, with evidence minimums applied **before** execution (a
  forecast or STL fitted to 6 points is confident-looking nonsense). It never
  names a method, only the business question; the catalog resolves the method.
- **`assess_materiality()`** — the differentiator. A method that ran cleanly but
  **found nothing produces no card**: no anomalies flagged, an insignificant or
  flat trend, a sub-5% period move, a driver model with R² < 0.2, and — notably
  — a *statistically significant but trivially weak* correlation, because with
  enough rows everything reaches significance. Unknown intents default to
  material so a newly catalogued method is never silently suppressed, and the
  gate never raises.
- **`evidence_presentation()` / `spec_presentation()`** — maps each intent to
  the chart **plus analytical layers** that show its evidence, with an override
  so one intent can map to two charts (see co-movement below).

`home_intelligence._method_driven_insights()` orchestrates: probe → plan →
project SQL per intent (aggregated per period for time series, **raw rows** for
distribution/relationship methods so the method sees the distribution) →
execute via `analyze_methods()` on the **same governed path Business Insights
use** (R-first, tenant governance, provenance) → gate on materiality → build the
card carrying `analyticalMethod` / `method_envelope`, so the **R Analytics badge
and Explain panel light up automatically**. Fail-closed per analysis.

The route runs methods first and keeps shape templates as a fallback for tables
where no method applies.

### 3. Executive-grade analyses

For a monthly KPI table with history, a second metric, a segment and a budget
column, the planner now offers (ranked):

| Priority | Analysis | Chart |
|---|---|---|
| 0.97 | **Year over year** | combo |
| 0.95 | Period over period (MoM) | combo + reference line |
| 0.93 | **Actual vs Budget/Target** | combo |
| 0.91 | **Two KPIs along a shared timeline** | dual-axis combo |
| 0.90 | Unusual observations (anomalies) | line + band + markers |
| 0.88 | What drove the change (contribution) | ranked bar |
| 0.86 | **Rate of change / momentum** | line |
| 0.85 | When the metric shifted (change point) | line + marker |
| 0.83 | **Underlying trend — real or noise** | line + regression |
| 0.80 | Outlook (forecast) | line + prediction band |
| 0.78 | **What explains this KPI (drivers)** | bar |
| 0.75 | KPI vs KPI (raw correlation) | scatter |
| 0.72 | KPI by segment | boxplot |

Three decisions worth knowing:

- **YoY is gated on distinct calendar years, not row count.** 24 monthly rows
  inside a single year cannot support a YoY read. It fires only with ≥2 actual
  years and outranks MoM.
- **"Two data points moving along a timeline" is a distinct analysis from a
  scatter.** Same correlation intent, but aggregated per period and drawn as a
  dual-axis combo ("Revenue and Gross Margin over time"). Both variants are
  planned and ranked separately — which is why `DeepAnalysisSpec` gained a
  `presentation` override.
- **Actual-vs-target fires only when a baseline column exists**, and the
  baseline is excluded from the KPI list so it is compared *against* rather than
  analysed as its own KPI. Detection had a real bug: `\b` never fires inside
  `budget_revenue` because `_` is a word character — fixed with explicit
  separators, verified against `budget_revenue`, `revenue_target`,
  `planned_output`, `goal_units`, while correctly ignoring `revenue` and
  `gross_margin`.

---

## Test status (this container)

`deep_analysis` **34/34**, `chart_catalog` **18/18**,
`visualization_engine` **27/27**, `ruff` clean on every touched file.

---

## Devin: merge, deploy, verify

1. Merge this branch into the deployed lineage.
2. Full suites in CI: platform-api `pytest` / `ruff` / `mypy`; ai-server
   `pytest`; web-ui `typecheck` / `test --run` / `build`.
3. Deploy (rebuild images) and **clear insight caches** so cards regenerate
   through the new path.
4. Verify on the live Business-Insight page:
   - Deeper analysis shows **YoY / MoM / actual-vs-target / co-movement /
     contribution / anomaly / forecast** cards, not shape-probe charts.
   - **No card is keyed on an identifier column.**
   - Cards carry the **R Analytics badge**; Explain shows method, engine, n,
     assumptions/warnings.
   - Statistically empty results produce **no card** (that is correct, not a
     regression).

### One thing to check after deploy

The materiality gates read result keys defensively (`anomalies`,
`change_points`, `p_value`, `correlation`, `r_squared`, `relative_change` /
`percent_change`, …). I could not see the R implementations' actual output key
names from here. If a gate reads keys the R methods do not emit, that intent
falls through to **material** — safe (you would see cards, not lose them), but
the gate would not be filtering.

Open one anomaly card and one driver/correlation card, read the Explain panel's
result keys, and if they differ from the lists in `_MATERIALITY_RULES`
(`deep_analysis.py`), add the real key names to the relevant `_first_num` /
`_first_list` lookups. That is a one-line change per key — report it in the PR
rather than restructuring the gate.

## Report

Confirmation the delivered files are byte-identical (or exact deviations +
reasons); CI totals per suite; deploy + cache-clear confirmation; screenshots of
a YoY card, an actual-vs-target card, a co-movement (dual-axis) card, and an
anomaly card with its R Analytics badge; plus any materiality key names you had
to add.
