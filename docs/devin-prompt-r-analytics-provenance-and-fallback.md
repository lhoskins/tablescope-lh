# Devin prompt (validated + enhanced): R provenance on insight cards, R-first Python fallback, and dashboard-nav restore

Repository: `lhoskins/tablescope-lh`
Base branch: `devin/r-echarts-e2e-validation` (PR #74 head — the deployed R
lineage). If PR #74 has merged, start from its merged target and re-verify the
paths below. Feature branch: `devin/r-analytics-insight-provenance`. Open the PR
back to the selected base. Do not deploy to production.

This document validates the uploaded provenance prompt against the actual code,
corrects three load-bearing assumptions, folds in the requested **R-first /
Python-fallback** behavior, and adds the **dashboard-nav restore**. Treat the
uploaded prompt's body as authoritative **after** applying the corrections in
Part A; Parts B and C are additive scope.

Migration reality: head on this base is **`0066`**; `0067` is the next number if
a migration is truly needed — but provenance should ride the **existing
persisted JSON envelope** (see A3), so likely no migration is required.

---

## Part A — Validation findings & required corrections to the provenance prompt

### A1. CRITICAL: today's `executionEngine` is derived from config, not execution

`result_envelope.py:68` builds the envelope's engine as:

```python
"executionEngine": method.get("execution_engine") if method else None,
```

That is the **catalog method's configured engine**, not the engine that actually
ran. And neither executor stamps the engine it ran:

- `executors/r_executor.py` returns the R service JSON verbatim on success and a
  `{"status": "error", ...}` dict on failure — no engine field.
- `executors/python_executor.py` returns `method_executor.execute(...)` verbatim
  — no engine field.

So the envelope literally cannot distinguish "R actually executed" from "the
method is *configured* for R." Shipping the badge off the current field would
violate the prompt's central rule ("Do not infer R execution from a configured
method"). **This is the linchpin fix and it must land first.**

Do:

1. **Stamp the actual engine in each executor result.**
   - In `PythonExecutor.execute`, set `result["engine"] = "python"` before
     returning (only when the result is a dict with a real status; leave error
     shapes intact otherwise).
   - In `RExecutor.execute`, on the **success** path set `result["engine"] = "r"`
     after `resp.json()`. On the **failure** path leave the error envelope's
     engine unset (it did not execute in R).
2. **Read the actual engine in `result_envelope.build`.** Change line 68 to
   prefer the executed engine, falling back to the configured value only for
   legacy/no-op results:

   ```python
   "executionEngine": exec_result.get("engine")
       or (method.get("execution_engine") if method else None),
   ```

   Keep this backward-compatible: older envelopes/tests without
   `exec_result["engine"]` still resolve to the configured value.
3. The badge condition (`executionEngine === "r"`) is now truthful: it is true
   only when `RExecutor` actually returned a successful result, and it becomes
   `"python"` automatically on fallback (Part B).

### A2. CRITICAL: Project Insights do NOT run the Analytical Method Engine

`platform-api/app/services/project_insight_service.py` never calls `analyze()` /
`analyze_methods` — it references analytical methods only to *filter suggested
questions* (line ~150). Project Insight risk/trend/opportunity cards are
AI-narrative, built from `_card_group`/severity mapping, **not** from a
deterministic R/Python execution. There is therefore **no R provenance to badge
on `InsightCardItem` today.**

The uploaded prompt's Section 3 assumes Business↔Project symmetry that does not
exist. Correct it as follows (do **not** fabricate provenance, and do **not**
silently wire `analyze()` into project insights — that is a much larger,
separate effort and is out of scope here):

- **Build the shared provenance contract end-to-end on both card renderers**
  (`IntelligenceCard` and `InsightCardItem`) so the plumbing and legacy-safety
  are symmetric and forward-compatible.
- **Be explicit that Project Insight cards will show no R badge** until the
  engine actually executes on that path. The `InsightCardItem` badge must key off
  real per-insight provenance (absent today) → it renders nothing, which is
  correct. The Explain "Analysis details" section shows the legacy
  "provenance not available" state for these.
- Where the prompt says "Update `project_insight_service` … so the same
  provenance contract reaches `InsightCardItem`," scope that to **serialization
  passthrough**: if/when a project insight carries a `method_envelope`, serialize
  its provenance; do not manufacture one. Note this limitation in the PR.

Net effect: on today's code the **R badge appears only on Business Insight /
Home cards** (the `home_intelligence` path that runs
`_attach_method_envelopes`) and any Ask Anything surface that executes the
engine. That is the honest, verifiable behavior.

### A3. Provenance rides the existing persisted envelope — field mapping

The engine already attaches `item["method_envelope"] = envelope` in
`home_intelligence._attach_method_envelopes` (HYBRID + method selected), and
envelopes flow through `response_envelope.attach_envelope`. **Verify the
`method_envelope` is persisted into the card snapshot/cache that Business
Insights restore from — not only the live response** — so provenance survives
refresh, caching, and Home pinning (the prompt's Section 6). If the snapshot
currently drops it, carry it into the persisted JSON (reuse the existing
snapshot JSON columns; no new migration).

Map the prompt's `AnalysisProvenance` to what the envelope actually has:

| Prompt field | Source in current envelope | Action |
|---|---|---|
| `executionEngine` | `exec_result.engine` (after A1) | fixed by A1 |
| `status` | `exec_result.status` (`ok`/`insufficient_data`/`invalid_input`/`timeout`/`error`) | map to `ok`/`warning`/`error` |
| `quality` | `envelope.quality` | passthrough |
| `assumptions`/`caveats`/`warnings` | present | passthrough (bounded) |
| `methodId` | `audit.catalogMethodId` | passthrough |
| `methodName` | not present (only id) | derive from catalog `method` name; else null |
| `audit.parameterHash` | `audit.parameterHash` (**already fixed** — passes `roles`, not `{}`) | passthrough |
| `audit.inputDataHash` | `audit.inputDataHash` (`profile.hash`) | passthrough |
| `audit.registryVersion` | `audit.methodRegistryVersion` | passthrough |
| `dataScope.rowCount` | `envelope.n` | map |
| `analyzedAt` | **not present** | ADD: stamp a UTC timestamp into the envelope at build time |
| `fallback` | **not present** | ADD via Part B |
| `dataScope.{projectId,dateRange,filters}` | not in envelope | null / "Not available" unless cheaply threadable |

So the only net-new envelope fields are **`analyzedAt`** and the **`fallback`**
block (B). Everything else is passthrough or a trivial mapping. Do not add UI
rows for values that are null — render "Not available" or omit, per the prompt.

### A4. Confirmed-good assumptions (no action)

- `IntelligenceCard` → `web-ui/components/tablescope/home/intelligence-card.tsx`;
  `InsightCardItem` lives in
  `web-ui/components/tablescope/project-insight/project-insight-screen.tsx`.
  Both exist; keep the existing Explain action, feedback/review, governance,
  pinning, and Save-to-Dashboard behavior untouched.
- The `parameterHash` `{}` bug is **already fixed** on this base, so audit hashes
  are safe to surface (shortened/copyable) per the prompt.
- Migration head is `0066`; only use `0067` if a schema change is truly needed
  (it should not be).

---

## Part B — R-first execution with Python fallback (requested)

Goal: prioritize R and fall back to Python when R is unavailable, analogous to
the multi-table tiering — **and** make the fallback truthful in provenance (no R
badge on a Python-produced result; the details disclose the fallback).

Current `executors/registry.py` already picks R **first** when the method is
configured `execution_engine="r"` and `R_ANALYTICS_ENABLED=true`; otherwise
Python. What is missing is the **fallback on R failure** — today an R outage
yields a `status:"error"` envelope with no recovery.

Do (small, additive; do not change SciPy/statsmodels numerics or the R
container):

1. **`r_config.py`** — add a mode reader following the existing pattern:

   ```python
   DEFAULT_R_ANALYTICS_FAILURE_MODE = "python_fallback"

   def r_analytics_failure_mode() -> str:
       raw = (os.getenv("R_ANALYTICS_FAILURE_MODE") or DEFAULT_R_ANALYTICS_FAILURE_MODE).strip().lower()
       return raw if raw in {"python_fallback", "skip"} else DEFAULT_R_ANALYTICS_FAILURE_MODE
   ```

2. **`executors/registry.py`** — after an R run, if the result is an
   **unavailability** error (`status == "error"`; that is exactly what
   `RExecutor` emits on connect/timeout/HTTP failure, and R timeouts surface as
   `error`), the mode is `python_fallback`, **and a real Python executor exists
   for the method**, retry via `PythonExecutor` and annotate:

   ```python
   executor = self.get(method.get("execution_engine"))
   result = executor.execute(request)
   if (
       isinstance(executor, RExecutor)
       and result.get("status") == "error"
       and r_analytics_failure_mode() == "python_fallback"
   ):
       py_key = method.get("python_fallback_executor_key") or method.get("executor_key")
       if py_key and py_key in method_executor.EXECUTORS:
           py_req = ExecRequest(method_id=request.method_id, executor_key=py_key,
               df=df, roles=roles, profile=profile, policies=policies,
               max_rows=request.max_rows, timeout_seconds=request.timeout_seconds)
           py_result = PythonExecutor().execute(py_req)   # stamps engine="python" (A1)
           py_result["fallback"] = {"used": True, "fromEngine": "r",
               "toEngine": "python", "reason": result.get("reason")}
           py_result.setdefault("warnings", []).append(
               "R analytics unavailable; computed via Python fallback.")
           return py_result
   return result
   ```

   Gate rules (do not deviate): fall back **only** on `status == "error"` (never
   on `insufficient_data`/`invalid_input` — legitimate outcomes Python would
   reproduce), **only** when `py_key in method_executor.EXECUTORS` (the R sample
   method's `r_descriptive_profile` key is not in the Python map, so it simply
   won't fall back — that is the correct `skip` outcome, not a bug), and **never
   more than once**. `skip` mode disables the retry entirely.

3. **Provenance tie-in (this is why B lives with A):** because `PythonExecutor`
   stamps `engine="python"` (A1) and the registry sets the `fallback` block, the
   envelope's `executionEngine` becomes `"python"` and `provenance.fallback`
   is populated. The UI then correctly shows **no R badge** for a fallback
   result and discloses the fallback in Analysis details — matching the prompt's
   UI-states row "R attempted, Python fallback produced result → No R badge →
   Engine Python + sanitized fallback disclosure."

4. **`result_envelope.build`** — surface the fallback: add
   `"fallback": exec_result.get("fallback")` to the envelope (additive,
   optional). Also add `"analyzedAt": <UTC ISO timestamp>` (A3).

5. **docker-compose.yml** — add `R_ANALYTICS_FAILURE_MODE:
   ${R_ANALYTICS_FAILURE_MODE:-python_fallback}` next to the existing
   `R_ANALYTICS_*` in `platform-api` (and the worker/migrate services if they
   carry the other R vars).

Tests (extend `tests/test_executor_registry.py`): R-unavailable + Python twin +
`python_fallback` → Python result with `engine=="python"` and `fallback.used`;
R-unavailable + no Python twin → R error envelope unchanged; `skip` → unchanged;
R-success → R result, Python not called; R-disabled → unchanged (byte-for-byte
regression); `insufficient_data`/`invalid_input` never overridden.

---

## Part C — Restore the missing project "Dashboards" nav link

Regression: on this lineage `web-ui/components/tablescope/nav.ts` `projectNavGroups`
lost its **`project-dashboards`** entry (it goes `project-documents` →
`project-business-context`), even though the route
(`web-ui/app/projects/[id]/dashboards/page.tsx`), the screen
(`dashboards-screen.tsx`, which sets `activeNav="project-dashboards"`), and the
`NavKey` union (`web-ui/lib/ui/types.ts:56` includes `"project-dashboards"`) all
still exist. The link was dropped by an earlier UI PR; the page is reachable only
by direct URL.

Do (pure additive restore — no other nav changes):

1. Ensure `IconLayoutDashboard` is imported from `@tabler/icons-react` in
   `nav.ts` (add it if missing).
2. In `projectNavGroups`, add the item **immediately after `project-documents`**:

   ```ts
   {
     key: "project-dashboards",
     label: "Dashboards",
     href: `${base}/dashboards`,
     icon: IconLayoutDashboard,
   },
   ```

3. Verify: on a project, the sidebar shows **Dashboards** under **Tables** and
   navigates to `/projects/{id}/dashboards`; the existing dashboards screen
   highlights the active nav. Do not alter the Home-level Dashboards entry or any
   other nav item.

---

## Verification (whole PR)

```bash
cd platform-api
pytest -q tests/test_executor_registry.py tests/test_result_envelope.py \
          tests/test_home_intelligence.py tests/test_project_insight_service.py
ruff check app tests && mypy app
cd ../web-ui && npm run typecheck && npm test -- --run && npm run build
```

Do not dismiss failures as pre-existing without showing they also fail on the
base branch (the known Teiid name-resolution failures in
`test_home_intelligence.py::test_project_dashboard_builds_real_chart_widgets` and
`test_scope_sets.py` are environmental — confirm identically on base).

## Acceptance (delta over the uploaded prompt)

- Envelope `executionEngine` reflects the **executed** engine (A1); a Python
  fallback result is labeled Python and never shows the R badge (B3).
- Business Insight / Home cards show the R badge only for genuinely
  R-executed results; Project Insight cards show no badge today, with the
  contract wired for forward-compat and the limitation documented (A2).
- Provenance survives refresh/cache/pin for the exact displayed insight (A3).
- R-disabled behavior is byte-for-byte identical to base (B tests).
- The project **Dashboards** nav link is restored (C).
- All other feedback/review, governance, pinning, dashboard, and explanation
  behavior is unchanged.

## PR summary must include

Branch/base + migration note (expected: none needed, head `0066`); the
executor-engine-stamping diff and the one-line `result_envelope` engine-read
change; the fallback gate rules; the provenance data-flow (engine → envelope →
snapshot → card); Business Insight screenshot with Explain open showing the R
badge + Analysis details; a Python/fallback screenshot showing **no** R badge +
fallback disclosure; the nav-restore screenshot; sanitized R and fallback
response fragments; test results; and the explicit note that Project Insight
cards carry no R provenance until `analyze()` is wired into
`project_insight_service` (out of scope here).
```
