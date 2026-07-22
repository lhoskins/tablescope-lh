# Devin plan (validated + hardened): R as TableScope's invisible analytical & visualization layer

Repository: `lhoskins/tablescope-lh`

This is a **validated and enhanced** overlay for the uploaded R Analytical Layer
plan. The original plan is unusually well-grounded — every architectural
reference was checked against the actual tree and confirmed. This document:

1. records the validation evidence (so Devin can trust the base),
2. corrects a small number of imprecise file/line references,
3. adds **preserve-existing guardrails** (the explicit ask: do not overwrite
   working functionality unless strictly required to install R), and
4. restates the branch strategy with verified facts.

Treat the original plan's Phase 1–4 bodies as authoritative **after** applying
the corrections in section B. Where this document and the original disagree,
this document wins.

---

## A. Validation summary — what was verified (evidence)

Base branch inspected: `devin/1784600100-card-trend-arrows`.

- **"348 commits ahead of `main`"** — exact. `git rev-list --count
  origin/main..origin/devin/1784600100-card-trend-arrows` = 348.
- **All 15 "current architecture to extend" files exist** on that branch:
  `analytical_method_engine/{engine,method_executor,result_envelope,method_registry,method_selector}.py`,
  `seed_data/analytical_methods/catalog.json`, `visualization_engine.py`,
  `response_envelope.py`, `web-ui/components/ai/{ResponsePresenter,method-envelope}.tsx`,
  `web-ui/components/tablescope/home/intelligence-card.tsx`,
  `home_intelligence.py`, `project_insight_service.py`, `routes/ai_proxy.py`,
  `web-ui/components/dashboard/WidgetRenderer.tsx`.
- **The deterministic executors are SciPy/statsmodels** as described.
  `method_executor.py` imports `scipy.stats`, `numpy`, `pandas`; the dispatch
  table `EXECUTORS: dict[str, Callable[..., dict[str, Any]]]` is defined at
  `method_executor.py:523` and dispatched via `fn = EXECUTORS.get(executor_key)`
  (~line 558). The engine calls it at `engine.py:86`
  (`method_executor.execute(...)`).
- **`ANALYTICAL_METHOD_ENGINE_MODE` exists** with exactly the values
  `off|readonly|hybrid` — `analytical_method_engine/config.py` defines
  `EngineMode.{OFF,READONLY,HYBRID}`, `DEFAULT_ENGINE_MODE = "off"`, read from
  `os.getenv("ANALYTICAL_METHOD_ENGINE_MODE")`.
- **The parameter-audit-hash bug is real and precisely located.**
  `result_envelope.py:73` calls `_parameter_hash(intent, {}, method_id)` —
  passing a literal `{}` where the function signature
  (`_parameter_hash(intent, roles, method_id)`, line 18) expects the normalized
  roles. The hash therefore ignores roles/parameters. The plan's fix is correct.
- **Migration `0050` is genuinely the next number.** Current head is
  `0049_analytical_method_catalog.py`; no `0050_*` exists.
- **Section-2.4 targets exist**: `method_selector.py`, `column_roles.py`,
  `intent.py` are all present.
- **Charting reality (critical for "preserve existing"):** `web-ui/package.json`
  ships **`recharts` ^2.15.0** and **`d3` ^7.9.0**. **ECharts is NOT installed.**
  `WidgetRenderer.tsx` imports chart primitives from `recharts` (line 38) and
  `withDefaults` from `chartRegistry`. So the plan's `renderer: "legacy"` maps to
  the **recharts** renderer; ECharts is strictly additive.
- **docker-compose.yml exists** with services `teiid, platform-api,
  platform-api-worker, platform-api-migrate, nginx, certbot, web-ui, db, redis,
  pgbouncer` on networks `default` and `tenant_acme_net`. `nginx` is the only
  port-publishing edge.
- **`executors/` directory is net-new** (does not exist yet). **No R references
  exist anywhere** (`R_ANALYTICS*` is net-new).

Conclusion: the plan's premises hold. Proceed on the branch strategy in
section D, applying the corrections in section B and the guardrails in section C.

---

## B. Corrections to specific references (apply these)

These are the only places the original plan is imprecise. None change the plan's
intent; they prevent Devin from editing the wrong file or fabricating a fix.

1. **Engine-mode gate location.** `ANALYTICAL_METHOD_ENGINE_MODE` is **not** in a
   central `config.py`/`settings.py`; it lives in
   `platform-api/app/services/analytical_method_engine/config.py` as an
   `EngineMode` enum read from the environment. Add the new **R feature gate the
   same way** — a sibling env-var/config (`R_ANALYTICS_ENABLED`, etc.), resolved
   independently of `EngineMode`, so `hybrid` does not imply R. Do **not** add R
   values to `EngineMode`; keep the two gates orthogonal (a `hybrid` engine with
   `R_ANALYTICS_ENABLED=false` must be byte-for-byte current behavior).

2. **Executor refactor insertion point.** The coupling to fix is two-sided:
   `EXECUTORS` at `method_executor.py:523` **and** the call site
   `engine.py:86` (`method_executor.execute(...)`). Wire the new
   `executors/registry.py` so `engine.py` resolves an executor by
   `execution_engine`/`executor_key` and calls its `.execute(request)`; move the
   existing `EXECUTORS` map and `method_executor.execute` body behind
   `PythonExecutor` **without changing their computation**. Keep
   `method_executor.execute` importable (or a thin shim) so existing imports/tests
   don't break.

3. **The audit-hash fix — exact.** In `result_envelope.py`, change line 73 from
   `_parameter_hash(intent, {}, method_id)` to pass the **actual normalized
   roles and parameters**. Note `_parameter_hash` truncates SHA-256 to 16 chars;
   keep that or bump `resultSchemaVersion` if you widen it. **Because this changes
   the emitted `parameterHash` value**, any existing test/snapshot asserting the
   old (buggy) hash must be updated deliberately — call this out in the PR rather
   than letting a "passing" test silently encode `{}`.

4. **Migration number.** `0050_analytical_execution_engine.py` is correct
   (`down_revision = '0049'`). Make every new column **additive with a default**
   (`execution_engine` default `'python'`, `result_schema_version` default `1`,
   `chart_contract` default `{}`; `max_rows`/`timeout_seconds` nullable). Provide
   a working `downgrade()`. Do not add NOT-NULL columns without a server default
   to the populated `analytical_methods` table.

5. **Frontend "legacy" renderer = recharts.** The persisted
   `renderer: "legacy" | "echarts"` field must default existing/saved widgets to
   `legacy` (recharts). Do not migrate recharts widget JSON on read. The ECharts
   type/`WidgetType` update in the original §3.5 should target
   `web-ui/components/dashboard/types.ts` (where `WidgetConfig`/`WidgetType`
   live) and `web-ui/lib/visualizations/chartRegistry.ts` (which has a companion
   `chartRegistry.test.ts` — keep it green).

6. **AI-server "analytical method best-practice prompts" do not exist as a
   file.** The AI server has `app/prompts/{dashboard_best_practices,
   project_insight_best_practices,knowledge_graph_insight_best_practices}.md`
   loaded by `app/services/prompt_loader.py`. There is no analytical-method
   prompt today. Add analytical-method guidance as a **new** prompt file loaded
   through `prompt_loader.py` (or fold it into an existing one) — do not edit a
   file that isn't there. Keep the rule that the **catalog**, not the LLM,
   selects the engine/method.

7. **docker-compose network placement.** Attach `r-analytics` to the existing
   **`default`** network only; do **not** add it to the `nginx` service's
   upstreams or publish its port. `nginx` (compose service, line ~148) is the
   only edge that publishes ports — leaving `r-analytics` off it satisfies the
   plan's "do not publish the service port."

---

## C. Preserve-existing guardrails (explicit user requirement)

> "Preserve existing functionality and do not overwrite unless absolutely
> necessary to complete the R installation."

Hard rules for every phase:

- **SciPy/statsmodels executors are untouched behavior.** Wrapping them in
  `PythonExecutor` is a move, not a rewrite. No numeric output may change. The
  existing analytical tests must pass **unchanged** (contract-only import
  adjustments are the maximum allowed edit).
- **recharts stays the default renderer.** ECharts is additive behind
  `ECHARTS_RENDERER_MODE=off|shadow|new_widgets|default`, default `off`. In
  `off`/`shadow` the user sees exactly today's recharts output. Never delete or
  rewrite `WidgetRenderer.tsx`'s recharts paths in this work; the legacy renderer
  is removed only in the separately-approved later cleanup (original §3.7 step 8).
- **No saved-widget mutation on read.** Widgets without a `renderer` field are
  treated as `legacy`. Any migration to `echarts` is explicit, idempotent, and
  reversible while recharts exists.
- **Both feature gates default OFF/disabled.** `R_ANALYTICS_ENABLED=false` and
  `ECHARTS_RENDERER_MODE=off` in the committed defaults and in production until
  shadow validation passes. Enabling the analytical engine must not enable R;
  enabling R must not switch the renderer.
- **Fail-open, never fail-blocking.** R timeout / unavailable / malformed /
  oversized input must fall back to the configured Python method or return the
  normal answer without deeper evidence — it must never block Ask Anything,
  insight refresh, or dashboard rendering (original §4.5 acceptance).
- **Additive schema only.** Migration `0050` and any Phase-3 widget fields add
  columns/tables with defaults; no drops, no type narrowing, reversible
  downgrades.
- **Don't disturb the other active lineage.** This analytical work is on a
  different branch lineage than the recent feedback/UI branches
  (`devin/insight-review-*`, `devin/prompt-*`). Do not pull those in; keep the
  PR scoped to the R/ECharts layer.

Any change that would violate one of these is "not absolutely necessary" by
definition — find the additive path instead, or stop and flag it.

---

## D. Branch strategy (verified)

- Base on **`devin/1784600100-card-trend-arrows`** — confirmed to contain the
  full analytical engine, visualization engine, intent engine, response
  envelope/presenter, catalog, and trend-card work (validation section A).
- **Before coding, `git fetch origin` and re-check for a newer integration
  branch.** Note: branches with newer commit dates exist
  (`devin/insight-review-*`, `devin/prompt-query-gen-width-invite-feedback`,
  dated 2026-07-22) but they are a **separate feedback/UI lineage** and are **not
  guaranteed to contain the analytical engine**. Only move to a newer base if
  `git merge-base --is-ancestor origin/devin/1784600100-card-trend-arrows
  <candidate>` returns true (candidate contains every analytical commit). None of
  these lineages is merged into `main`; do not base on `main`.
- Sequential PR branches (unchanged from the original):
  1. `devin/1784600100-card-trend-arrows` → `devin/r-runtime-executor-contract`
  2. → `devin/r-business-analysis-methods`
  3. → `devin/r-chart-evidence-integration`
  4. → `devin/r-insight-workflow-rollout`
  Single-branch fallback: `devin/r-analytical-layer` with the four phases as
  separate commits.

---

## E. The original plan (validated as accurate — follow it with B/C applied)

Everything below the line in the uploaded plan — Phases 1–4, the method/chart
matrix, testing requirements, definition of done, and Devin handoff — was
checked and is **accurate** against the base branch. Follow it as written, with:

- the **corrections in section B** applied to the specific files/lines, and
- the **guardrails in section C** treated as non-negotiable acceptance criteria.

Two additions to the original's acceptance/handoff, reflecting the guardrails:

- Add to every phase's acceptance: *"With `R_ANALYTICS_ENABLED=false` and
  `ECHARTS_RENDERER_MODE=off`, a full `pytest` + web-ui `tsc`/lint/component-test
  run is identical to the base branch (no behavioral diff)."*
- Add to the Devin handoff: *"State explicitly which existing files were moved
  vs. modified, and confirm no SciPy/statsmodels numeric output and no recharts
  render path changed."*
```
