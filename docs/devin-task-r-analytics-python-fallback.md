# Devin task: add `R_ANALYTICS_FAILURE_MODE` python-fallback to the executor registry

Repository: `lhoskins/tablescope-lh`
Base branch: `devin/r-analytical-layer-deploy` (the deployed R scaffold).
Suggested working branch: `devin/r-analytics-python-fallback`.

Small, additive change. Do **not** touch the SciPy/statsmodels numeric code, the
R container, or the frontend. Keep the PR to the registry + config + tests.

## Problem

When `R_ANALYTICS_ENABLED=true` and the `r-analytics` service is unreachable or
times out, `RExecutor.execute()` catches the failure and returns
`{"status": "error", "quality": "unavailable", ...}`
(`executors/r_executor.py`). The registry uses that result directly — it never
retries Python:

```python
# executors/registry.py — current
def get(self, execution_engine: str | None) -> Executor:
    engine = (execution_engine or "python").lower()
    if engine == "r" and is_r_analytics_enabled():
        return RExecutor()
    return PythonExecutor()

def execute(self, method, df, roles, profile, policies=None):
    request = ExecRequest(...)
    return self.get(method.get("execution_engine")).execute(request)
```

This contradicts the module's own docstrings — `registry.py` says *"Keeps Python
as the default and fallback"* and `r_executor.py` says failures become error
status *"so the engine can fall back to the Python executor"* — but no fallback
is wired. Result: any R outage silently degrades every R-selected method to an
error envelope with no recovery. The original R plan specified
`R_ANALYTICS_FAILURE_MODE=python_fallback|skip`; it was not implemented.

## Goal

When R returns an **unavailability** error and a Python implementation for the
method exists, transparently re-run it through the Python executor and return
that result (marked as a fallback). Otherwise, behave exactly as today. This
must never raise and never change behavior when R is disabled or R succeeds.

## Scope boundaries (important)

- Fall back **only** on R **service unavailability** — i.e. the exact envelope
  `RExecutor` emits on connection/timeout/HTTP failure: `status == "error"`
  (its `quality` is `"unavailable"`). Do **not** fall back on
  `insufficient_data` or `invalid_input` — those are legitimate deterministic
  outcomes; Python would return the same. (R timeouts currently surface as
  `status == "error"` via the generic `except`, so they are covered.)
- Fall back **only** when a Python executor actually exists for the method.
  The R sample method's `executor_key` (e.g. `r_descriptive_profile`) is **not**
  a key in `method_executor.EXECUTORS`, so a same-key retry would fail. Resolve
  the Python key as: `method["python_fallback_executor_key"]` if present, else
  `method["executor_key"]` — and only fall back if that resolved key is in
  `method_executor.EXECUTORS`. If it isn't, return the R error envelope
  unchanged (this is the `skip` outcome for methods without a Python twin).
- Default `R_ANALYTICS_FAILURE_MODE=python_fallback`. `skip` disables the
  fallback (always return the R error envelope). Unknown values → treat as
  `python_fallback`.

## Changes

### 1. `analytical_method_engine/r_config.py` — add the mode reader

Follow the existing pattern in this file (env-var readers with defaults):

```python
DEFAULT_R_ANALYTICS_FAILURE_MODE = "python_fallback"

def r_analytics_failure_mode() -> str:
    raw = (os.getenv("R_ANALYTICS_FAILURE_MODE") or DEFAULT_R_ANALYTICS_FAILURE_MODE).strip().lower()
    return raw if raw in {"python_fallback", "skip"} else DEFAULT_R_ANALYTICS_FAILURE_MODE
```

### 2. `analytical_method_engine/executors/registry.py` — wire the fallback

Keep `get()` as-is. Change `execute()` so that after an R run, if the result is
an unavailability error and the mode + Python availability allow it, retry via
`PythonExecutor` and annotate the result. Keep it exception-safe.

```python
from app.services.analytical_method_engine import method_executor
from app.services.analytical_method_engine.r_config import (
    is_r_analytics_enabled,
    r_analytics_failure_mode,
)

def execute(self, method, df, roles, profile, policies=None):
    request = ExecRequest(
        method_id=method.get("method_id") or "unknown",
        executor_key=method.get("executor_key") or "",
        df=df, roles=roles, profile=profile, policies=policies,
        max_rows=method.get("max_rows"),
        timeout_seconds=method.get("timeout_seconds"),
    )
    executor = self.get(method.get("execution_engine"))
    result = executor.execute(request)

    used_r = isinstance(executor, RExecutor)
    if (
        used_r
        and result.get("status") == "error"          # R service unavailable
        and r_analytics_failure_mode() == "python_fallback"
    ):
        py_key = method.get("python_fallback_executor_key") or method.get("executor_key")
        if py_key and py_key in method_executor.EXECUTORS:
            py_request = ExecRequest(
                method_id=request.method_id, executor_key=py_key, df=df,
                roles=roles, profile=profile, policies=policies,
                max_rows=request.max_rows, timeout_seconds=request.timeout_seconds,
            )
            py_result = PythonExecutor().execute(py_request)
            # Mark provenance so audit/UI can see the fallback happened.
            py_result.setdefault("warnings", []).append(
                "R analytics unavailable; computed via Python fallback."
            )
            py_result["engine_fallback"] = "python_from_r"
            return py_result

    return result
```

Notes:
- `method_executor.EXECUTORS` is the existing dispatch table
  (`method_executor.py:523`); membership check avoids calling Python with a
  key it can't run.
- `engine_fallback` is a new, optional provenance key. If `result_envelope.build`
  / the `execution` provenance block should surface it, add it there too — but
  do not break existing envelope consumers; it must be additive and optional.
- Do not retry more than once. Do not retry on `skip`, on `insufficient_data`,
  or on `invalid_input`.

### 3. `docker-compose.yml` — expose the new gate (additive)

Under `platform-api.environment` (next to the existing `R_ANALYTICS_*`, ~line 81):

```yaml
      R_ANALYTICS_FAILURE_MODE: ${R_ANALYTICS_FAILURE_MODE:-python_fallback}
```

Add the same line to `platform-api-worker` and `platform-api-migrate` if they
carry the other `R_ANALYTICS_*` vars, so the worker path behaves identically.

### 4. (Optional, only if a method needs differing keys) catalog field

The sample R method works without this because it simply won't fall back (no
Python twin). For real R methods that DO have a Python equivalent under a
different key (e.g. an R `period_change` whose Python twin is `describe_numeric`
or similar), add an optional `python_fallback_executor_key` to the method schema
and seed it in `catalog.json`. This is optional for THIS task — the registry
already reads it defensively via `.get(...)`. If you add the column, it must be
nullable with no default (additive migration, reversible downgrade); do not
renumber or edit existing migrations.

## Tests — extend `platform-api/tests/test_executor_registry.py`

- R enabled, R service raises/unavailable, method has a Python twin
  (`executor_key` in `EXECUTORS`), mode `python_fallback` → result is the
  Python-computed envelope, `status == "ok"`, carries the fallback warning and
  `engine_fallback == "python_from_r"`. (Simulate R failure by monkeypatching
  `RExecutor.execute` to return the `status:"error"` envelope, or by pointing
  `R_ANALYTICS_URL` at a dead port.)
- R enabled, R unavailable, **no** Python twin (executor_key not in `EXECUTORS`)
  → returns the R `status:"error"` envelope unchanged (no fabrication).
- R enabled, R unavailable, mode `skip` → returns the R error envelope unchanged.
- R enabled, R **succeeds** → returns the R envelope; Python executor is not
  called (assert no fallback warning / no `engine_fallback`).
- R disabled → `PythonExecutor` path unchanged (regression); numeric output
  identical to today.
- R returns `insufficient_data` / `invalid_input` → **not** overridden by a
  Python retry.

## Acceptance

- `pytest platform-api/tests/test_executor_registry.py` green, plus the existing
  `test_result_envelope.py` / `test_intent_engine.py` still green.
- `ruff` clean.
- With `R_ANALYTICS_ENABLED=false`: full behavior byte-for-byte identical to the
  base branch (no fallback path taken).
- With `R_ANALYTICS_ENABLED=true` and the `r-analytics` container stopped: a
  method with a Python twin returns a real Python result (not an error
  envelope); a method without one returns the R error envelope and the calling
  surface (Ask Anything / insight card) still renders its base answer — it does
  not blank.

## Handoff

Report: the exact registry diff; the new config reader; which statuses trigger
fallback and which do not; confirmation that R-success and R-disabled paths are
unchanged; the tests added and their results; and whether the optional
`python_fallback_executor_key` catalog field was added (and if so, the migration
number + that it is additive/nullable/reversible).
