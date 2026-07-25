# Devin plan: Deeper analysis — stop charting IDs (DELIVERED), then make it method-driven

Repository: `lhoskins/tablescope-lh`

## The answer to "should we install more complex methods?"

**No — you already have 29 executable analytical methods and Deeper analysis
calls none of them.**

Verified on the deployed lineage:

- The catalog (v1.1) has **29 executable methods, all `execution_engine: r`**,
  including exactly the "complex" ones this section should showcase:
  `contribution_to_change`, `detect_change_point`, `detect_anomalies`,
  `forecast_time_series`, `period_change` (MoM/YoY), `stl_decomposition`,
  `pearson`/`spearman`/`kendall` correlation, `welch_anova`, `kruskal_wallis`,
  `multiple_linear_regression`, `mann_kendall_trend`, `sens_slope`, …
- `_shape_template_insights` — the function that produces every Deeper-analysis
  card — contains **zero** references to `analyze_methods` / `analyze()` /
  `method_envelope`. `grep -c` returns 0.

So "Deeper analysis" today is not analysis at all. It is a **shape prober**: it
runs `SELECT * FROM <table> LIMIT 50`, looks for any column combination that can
be drawn, and emits a chart. That is why it charted order ids, and why it never
feels more technical than the main feed — there is no statistical method behind
any of it. Installing more methods would not change that, because nothing in
this path invokes a method.

---

## Part A — DELIVERED: stop charting identifiers

Branch **`claude/deep-analysis-business-value`** (based on the current deployed
lineage, which already contains the merged fit-confidence work from PR #96).

**STRICT RULES: merge as-is; do not rewrite/refactor/rename. Report suspected
bugs in the PR rather than silently changing the delivered code.**

What it adds (`visualization_engine`):

- `is_identifier_column(shape, col, rows)` — two independent signals:
  1. **Name**: `order_id`, `sku`, `ref_no`, `batch`, `invoice`, `serial`, …
  2. **Near-uniqueness**, but **only when the column sits beside a genuine
     low-cardinality dimension**. This guard is the subtle part and it is load
     bearing: an *aggregated* result has one row per category by construction,
     so 8 suppliers in 8 rows — or 40 in 40 — is a legitimate bar chart, not a
     key. An early version without this guard wrongly flagged `supplier`.
     Period columns are never identifiers (a daily axis is legitimately
     distinct).
- `business_dimensions(shape, rows)` — non-period, non-identifier dimensions.
- Wired into `_catalog_shape`, so a key can no longer inflate the dimension
  count that decides which families are eligible (this is what let a 300-value
  id unlock two-dimension families such as heatmap), and into the
  Deeper-analysis template loop, which now **skips a table with no business
  dimension** instead of falling back to keys.

Verified: `order_id + status` ranks as a one-dimension shape (no heatmap);
`supplier/defects` and daily series are unaffected. `test_visualization_engine`
**27/27**, `test_chart_catalog` **18/18**, `ruff` clean. (Two engine tests that
import `app.main` are excluded here — this container's numpy/pandas is broken;
they must pass in CI.)

---

## Part B — Make Deeper analysis actually deep (design for Devin)

Rebuild the section around the **Analytical Method Engine**, not shape probing.
Keep the existing shape templates as a fallback for tables where no method
applies.

1. **Drive from intents, not table shapes.** For each project table, resolve the
   business measures and periods (reuse the existing role detection), then ask
   the engine for the methods whose intents those columns satisfy:
   `compare_periods`, `detect_trend`, `trend_seasonality`, `detect_anomalies`,
   `detect_change_point`, `forecast_time_series`, `relationship_numeric`,
   `compare_multiple_groups`, `contribution_to_change`.
2. **Execute through the governed path** — `analyze()` /
   `analyze_methods(...)` with `ai_governance_service` gating, exactly as
   Business Insights do it — so every Deeper-analysis card carries a real
   `method_envelope`: engine (`r`), method id, n / usable n, assumptions,
   caveats, warnings, quality.
3. **Render the method's evidence**, not a generic chart: forecast → line +
   prediction band; anomalies → line + flagged points; change point → line +
   marker; correlation → scatter + regression line; contribution-to-change →
   ranked contribution bars; group comparison → boxplot + effect size;
   seasonality → STL decomposition panels. The ECharts families for these are
   already registered.
4. **Card copy leads with the finding**, with the method behind "Analysis
   details" (the R Analytics badge + Explain panel already exist).
5. **Materiality gate** — only surface a result that clears a configured
   threshold (significant change, real anomaly, adequate n). A statistically
   empty result should produce no card rather than filler. This is what makes
   the section feel genuinely deeper.
6. **Never key an analysis on an identifier** — use `business_dimensions()`
   from Part A when choosing group-by columns.

Sequencing suggestion: `period_change`, `detect_anomalies`,
`detect_change_point`, `forecast_time_series`, `contribution_to_change` first —
they map to the questions users actually ask, and all five already exist in the
catalog with R implementations.

## Definition of done

- Part A merged; no Deeper-analysis card is keyed on an identifier column.
- Part B: Deeper-analysis cards carry a real `method_envelope` with
  `executionEngine: "r"`, and their charts render the method's evidence
  (bands/markers/effect sizes), not a generic re-plot.
- Cards below the materiality threshold are suppressed rather than filled.
- Caches cleared, redeployed, screenshots of an anomaly card, a forecast card,
  and a contribution-to-change card.
