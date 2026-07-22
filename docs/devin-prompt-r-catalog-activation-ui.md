# Devin prompt: R method catalog — import, activate curated sets, and admin activation UI

Repository: `lhoskins/tablescope-lh`
Base branch: `devin/r-echarts-e2e-validation` (the deployed R lineage; re-verify
if PR #74 merged). Feature branch: `devin/r-catalog-activation-ui`.
Do not deploy to production as part of this task.

## Goal

Mirror the existing "import 937 methods, activate 24" pattern for R, and make
activation UI-driven going forward:

1. **Reuse the existing catalog as the method universe** — it is an
   engine-agnostic taxonomy of 937 statistical methods (24 executable/Python
   today, 913 reference-only). R is an *engine*, not a second taxonomy. Do NOT
   duplicate the catalog.
2. **Implement + activate two curated R sets now** (both executable, R-first with
   Python fallback):
   - **Set A — R twins of the current 24 executable methods** (same
     `executor_key`s, R implementations).
   - **Set B — business time-series methods** (`period_change`,
     `detect_change_point`, `detect_anomalies`, `forecast_time_series`,
     `contribution_to_change`).
3. **Build an admin activation API + UI** so any catalog method with an available
   implementation can be activated/deactivated later without a migration.

Hard constraint (state it in the PR): a method can only be **activated
(executable)** when a real implementation exists for its `executor_key` — a
Python function in `method_executor.EXECUTORS` or an R method in
`r-analytics/methods/`. Importing/definitions are cheap; activation is gated on
implementation. The long tail stays reference-only until implemented.

## Preserve-existing (non-negotiable)

- With `R_ANALYTICS_ENABLED=false`, behavior is **byte-for-byte today's**: the
  registry (`executors/registry.py`) already returns `PythonExecutor` for any
  method unless `engine=="r" AND is_r_analytics_enabled()`. So flipping a
  method's `execution_engine` to `r` runs Python when R is off — unchanged.
- **Fold in the R-first / Python-fallback registry change** (it was not taken
  earlier and is REQUIRED here): when R is enabled but the R service errors, a
  method whose `executor_key` has a Python twin must fall back to Python instead
  of returning an error. Without it, flipping the 24 to R makes an R outage
  degrade every core method. Implement `R_ANALYTICS_FAILURE_MODE=python_fallback`
  exactly as specified in
  `docs/devin-task-r-analytics-python-fallback.md` (config reader + registry
  retry gated on `status=="error"` and `py_key in method_executor.EXECUTORS`,
  stamping the actual engine + fallback provenance).
- Do not alter the SciPy/statsmodels Python executors' numeric behavior.

---

## Part 1 — R implementations in `r-analytics/methods/`

Each R method returns the normalized `AnalysisExecutionResult` contract already
used by `describe_numeric.R` (status, results, assumptions, caveats, warnings,
n/usable_n/excluded/missing, quality, reason, plus chart_data/chart_hints where
relevant). Pin every new R package in `renv.lock`. Run as the existing non-root,
no-network, read-only-rootfs service.

### Set A — R twins of the 24 (implement one `methods/<executor_key>.R` each)

Same `executor_key`s the Python executors use (so both engines share a key and
the engine field routes the runtime; fallback works because the Python twin
exists):

```
describe_numeric            pearson_correlation      spearman_correlation
kendall_correlation         one_sample_t_test        welch_t_test
students_t_test             mann_whitney_u           paired_t_test
wilcoxon_signed_rank        one_way_anova            welch_anova
kruskal_wallis              chi_square_independence  fisher_exact
linear_regression           logistic_regression      poisson_regression
negative_binomial_regression  trend_slope            mann_kendall_trend
sens_slope                  normality_test           stl_decomposition
```

Requirement: each R twin must reproduce the Python method's numeric outputs
within a documented tolerance (see statistical parity tests). Use base R /
`stats` where possible (`cor.test`, `t.test`, `wilcox.test`, `aov`,
`kruskal.test`, `chisq.test`, `fisher.test`, `glm`, `lm`, `stl`), `MASS` for
negative binomial, `Kendall`/`trend` for Mann-Kendall & Sen's slope. Preserve the
same effect-size/CI/p-value policy the catalog requires.

### Set B — business time-series methods (new `executor_key`s)

R-only capabilities (no Python twin → they will not Python-fallback; on R outage
they return the R error envelope and the caller degrades gracefully — that is
correct, not a bug):

| executor_key | R basis | Output essentials |
|---|---|---|
| `period_change` | base R date math | absolute + relative change, %-point for rates; current/comparison period, partial-period flag, zero/negative-baseline guards (never emit Inf) |
| `detect_change_point` | `changepoint` (cpt.mean/var) | change-point index/date, segment means, confidence |
| `detect_anomalies` | `forecast`/`stats` (STL remainder or tsoutliers) | expected band + flagged points |
| `forecast_time_series` | `forecast` (ETS/auto.arima) | point forecast + prediction intervals |
| `contribution_to_change` | base R decomposition | per-group contribution to aggregate movement, ranked |

`period_change` must honor the edge cases from the R plan (zero baseline →
relative undefined not Inf; missing prior → `insufficient_data`; negative
baseline → warning; partial current period → tentative; fiscal/timezone from
project/tenant config, never the container clock).

---

## Part 2 — Catalog: activate the two sets (no taxonomy duplication)

The catalog is generated by `scripts/convert_analytical_catalog.py` from
`source_taxonomy.json` + a hardcoded `EXECUTABLE` list, emitting
`app/seed_data/analytical_methods/catalog.json`. The seeder
(`scripts/seed_analytical_catalog.py`) reads `execution_engine`, `executor_key`,
`chart_contract`, `max_rows`, `timeout_seconds`, etc., and is **idempotent by
catalog `version` string**.

Do:

1. **Set A (flip existing 24 to R-first):** in `convert_analytical_catalog.py`,
   for the 24 methods in `EXECUTABLE`, set `execution_engine="r"` (keep the same
   `executor_key`, keep `is_executable=true`). They stay Python when R is off and
   run R (with Python fallback) when R is on.
2. **Set B (add 5 new executable methods):** add an `EXECUTABLE_R` list in the
   converter with the Set-B methods — full catalog entries (`display_name`,
   `category`, `tier: 1`, `status: active`, `is_executable: true`,
   `execution_engine: "r"`, `executor_key`, `supported_intents`, `method_card`,
   `output_contract`, `llm_guardrails`). If a matching reference method already
   exists in the taxonomy (e.g. a change-point or forecasting entry), flip that
   existing entry to executable+R instead of adding a duplicate `method_id`.
3. **Reference tail stays as-is:** the other ~913 methods remain
   `is_executable=false`, `executor_key=null`. They are R-activatable later via
   the UI once an implementation is added — no import of a separate R list is
   needed (the taxonomy already IS the R method universe).
4. **Bump the catalog `version`** in the taxonomy/output (e.g. `1.0` → `1.1`) so
   the idempotent seeder creates a new active version containing the R bindings.
   Regenerate `catalog.json` by running the converter and commit the result.
5. **Remove the fragile sample-method migration path:** delete/neutralize
   `0066_sample_r_analytical_method.py`'s runtime insert (it no-ops on a fresh DB
   because migrations run before the first seed) and instead ensure
   `r_descriptive_profile` (or its replacement) is defined in the seed catalog.
   Do not rely on migrations for catalog content. If you keep `0066` for history,
   make its `upgrade()` a no-op guard.

Selection wiring (`selection_matrix` in the taxonomy/catalog):
- Set A keeps existing intents (describe_numeric, compare_two_groups, …) — the
  flip to R needs no matrix change.
- Set B needs new intents + matrix rows: `compare_periods` (+
  `compare_year_over_year`, `compare_to_baseline`, `measure_rate_of_change` as
  aliases) → `period_change`; `detect_change_point`; `detect_anomalies`;
  `forecast_time_series`; `contribution_to_change`. Add corresponding
  `infer_intent` phrasing and `resolve_roles` role shapes in the engine so real
  questions ("month over month", "when did it change", "what should we expect")
  route to them. Do NOT give them private `r_*` intents (the current sample's
  flaw — nothing routes to it).

---

## Part 3 — Activation API (new, admin-gated mutation)

`platform-api/app/routes/analytical_methods.py` is read-only today. Add mutation
endpoints on the **active catalog version**, gated `require_role(Role.ADMIN)`
(catalog is global/platform, not tenant data — use the highest admin the app
has; confirm whether a root/platform admin exists and use it):

- `POST /api/analytical-methods/{method_id}/activate`
- `POST /api/analytical-methods/{method_id}/deactivate`
  (or a single `PATCH /{method_id}` with `{is_executable, status}`).

Rules:
- **Activation guard:** reject (422) unless an implementation exists for the
  method's `executor_key` — Python: `executor_key in method_executor.EXECUTORS`;
  R (`execution_engine=="r"`): the key is present in the R service dispatch
  (expose a static allowlist the API can check, or a health/list endpoint on
  `r-analytics`). Never let the UI activate a method that cannot run.
- Set `is_executable`/`status` on the `analytical_methods` row for the active
  version only; audit the change (who/when/what).
- Deactivation is always allowed; ensure the selector no longer picks a
  deactivated method (it already filters on active/executable in the registry).

---

## Part 4 — Admin activation UI

Extend `web-ui/app/admin/analytical-methods/page.tsx` (currently view-only:
list + `is_executable` badge + detail modal) and
`web-ui/lib/api/analytical-methods.ts`:

- Add an **Engine** column/badge (R / Python) and an engine filter.
- Add an **Activate / Deactivate** toggle per row (and in the detail modal),
  wired to the Part-3 endpoints via `useMutation`, with optimistic update +
  invalidation of the methods list query.
- **Disable the activate toggle** (with a tooltip "No implementation available")
  when the method has no Python/R executor — mirror the API guard client-side.
- Confirm dialog on activation/deactivation; keep it keyboard accessible.
- Preserve existing list, pagination, detail modal, and feedback/governance UI.

---

## Part 5 — Tests

- **Statistical parity (Set A):** for each of the 24 twins, R output vs the
  Python executor on fixed fixtures within a documented tolerance; assert the
  same effect-size/CI/p-value fields are populated. Not dependent on a live R
  container unless marked integration.
- **Set B correctness:** independently-verified expected values for
  `period_change` edge cases (zero/negative/missing/partial baseline, MoM/QoQ/
  YoY), change-point on a known break, forecast interval coverage, anomaly flags,
  contribution sums to the aggregate delta.
- **Fallback:** R-enabled + R-unavailable + Set-A method → Python result
  (`engine=="python"`, fallback provenance); Set-B method (no twin) → R error
  envelope, caller not blanked; R-disabled → Python, byte-for-byte unchanged.
- **Activation API:** admin can activate an implemented method; activating an
  unimplemented method → 422; non-admin → 403; deactivate removes it from
  selection; change is audited.
- **Seed/version:** new version seeds the R bindings + Set B; existing version is
  not duplicated; `execution_engine`/`executor_key` persist.
- **UI:** engine badge/filter render; toggle activates/deactivates and reflects
  immediately; toggle disabled with tooltip when no implementation; existing
  view behavior intact.
- Repo-standard: `pytest -q` (analytical + executor + home/project insight
  suites), `ruff`, `mypy`; web-ui `typecheck`, `test --run`, `build`. Known
  Teiid-name-resolution failures are environmental — show they also fail on base.

---

## Part 6 — Rollout & Definition of done

- `R_ANALYTICS_ENABLED=false` → identical to today (Set A runs Python; Set B
  methods simply aren't reached/executed).
- `R_ANALYTICS_ENABLED=true` + `R_ANALYTICS_FAILURE_MODE=python_fallback` +
  `ANALYTICAL_METHOD_ENGINE_MODE=hybrid` → Set A runs R-first with Python
  fallback; Set B business methods run on R for their intents.
- Catalog shows the 24 core methods as **R** engine + the 5 Set-B methods as
  active R, all `is_executable`, on the new seeded version; the reference tail
  remains inactive and R-activatable via the UI.
- Admin can activate/deactivate any implemented method from the UI; unimplemented
  methods cannot be activated.
- All tests/type/lint/build green; preserve-existing verified.

## PR summary must include

Base/branch + new catalog version string; the converter diff (Set A flip +
`EXECUTABLE_R`); the list of R methods implemented (Set A 24 + Set B 5) with
their packages added to `renv.lock`; the activation API routes + auth + guard;
the UI toggle behavior + the "no implementation" disable; statistical-parity
tolerances and results; fallback/R-off verification; screenshots of the admin
methods page showing engine badges and the activation toggle; and confirmation
that the reference tail is untouched and the sample-method migration no longer
inserts catalog content.
```
