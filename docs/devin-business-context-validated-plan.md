# Business Context (Success Criteria / KPIs / Project Risks) — validated & enhanced plan

Supersedes `Tablescope_Devin_Plan_Business_Context_Success_Criteria_KPIs_Project_Risks.md`.
Read this document instead of the original. Where a section is not mentioned
here, the original stands.

**Branch:** `devin/business-context-success-criteria-kpis-risks`
**Base:** `origin/devin/r-echarts-e2e-validation` (verified deployed lineage)

The plan's shape is correct: success criteria as parents, KPIs nested under
them, Project Risks independent and top-level, a two-step creation flow, and
governed AI-assisted source matching that never self-activates. All of that is
kept. What follows is what changes to land it in this repository without
losing existing code or silently no-opping a piece of it.

---

## 0. Validation findings

Every claim below was checked against the repository at the base SHA.

### 0.1 Confirmed — every path in the plan's "Repository-specific implementation" exists

```
web-ui/app/projects/[id]/business-context/page.tsx                    ✅
web-ui/components/tablescope/project/business-context-screen.tsx      ✅ (1653 lines)
web-ui/lib/api/project-context.ts                                     ✅
platform-api/app/routes/project_context.py                            ✅
platform-api/app/services/project_context.py                         ✅
platform-api/app/models/project_context.py                           ✅
platform-api/app/schemas/project_context.py                          ✅
platform-api/app/services/project_ai_context.py                      ✅
```

The current screen is exactly what the plan assumes it is: a **tabbed CRUD
shell** (`useState("settings")`) with `GoalsPanel`, `MetricsPanel`,
`RisksPanel` as three independent siblings — goals and metrics are not
nested, and there is no summary strip. The screenshot the plan supplies is the
*target*, not the current state. This refactor is real, not cosmetic.

### 0.2 Confirmed — the data model matches the plan's naming exactly

```
project_business_contexts    (ProjectBusinessContext)
project_goals                (ProjectGoal)           ← "success criterion"
project_metrics               (ProjectMetric)         ← "KPI"
project_metric_targets        (ProjectMetricTarget)
project_risks                  (ProjectRisk)
project_goal_metric_links      (ProjectGoalMetricLink) ← legacy M:N, to preserve
project_goal_risk_links        (ProjectGoalRiskLink)   ← legacy, to preserve
project_risk_metric_links      (ProjectRiskMetricLink) ← legacy, to preserve
project_context_audit_events   (ProjectContextAuditEvent)
```

`ProjectMetric` has **no** direct FK to `ProjectGoal` today — only the M:N
`project_goal_metric_links` table. The plan's `success_criterion_id` backfill
step (§ Data model and migration) is real work, not a formality: confirm your
backfill query counts before writing it (§1.3 below).

### 0.3 Confirmed, and load-bearing — nav and route registration already exist; do not re-register them

```ts
// web-ui/components/tablescope/nav.ts:178
key: "project-business-context",
href: `${base}/business-context`,
```

```python
# platform-api/app/main.py:48,239
from app.routes import project_context as project_context_routes
...
app.include_router(project_context_routes.router, prefix=api_prefix)
```

Both are already wired. **Do not add a second nav entry or a second
`include_router` call** — the plan doesn't ask for one, but a rebuild that
touches these files defensively sometimes does, and a duplicate route
registration throws at import time (FastAPI) or produces a silently-shadowed
nav item (React key collision), not a clean error either way.

### 0.4 Blocking — the exact case the user is asking about: a new arq task will be silently dead unless registered

The plan's §Background execution says "use the existing background-worker/Redis
pattern" and "persist a matching job before enqueueing" — correct, but it
elides the one step that makes a new task actually run. `platform-api/app/tasks/workflows.py`
registers every runnable task explicitly:

```python
class WorkerSettings:
    """arq worker entrypoint."""
    functions: ClassVar[list] = [
        process_upload,
        index_for_search,
        sync_saas_object,
        analyze_project_intelligence,
        scan_repository_connection,
        rebuild_knowledge_graph,
        run_knowledge_graph_health_check,
        recover_stale_graph_builds,
        evaluate_stale_graphs,
        reprocess_project,
        refresh_business_insight_result,
        rebuild_project_insight,
    ]
```

**arq only executes functions in this list.** Enqueueing a job for an
unregistered task *succeeds* — `enqueue_job()` returns a job id, the row lands
in the durable jobs table, nothing raises. The job simply never dequeues. This
is the single easiest way for this feature to look complete in a demo (the UI
shows `searching`, the API returns 202) and do nothing in reality. See §1.1 for
the exact before/after.

### 0.5 Confirmed — risk `severity` is client-supplied today, not computed

The plan requires: *"Calculate rating on the server from a versioned
likelihood × impact matrix. The client may preview the rating but must not be
authoritative."* Today it is the opposite — `severity` is a free string the
client sends and the service only validates against allow-lists:

```python
# platform-api/app/services/project_context.py:58-61
_VALID_LIKELIHOOD = {"rare", "unlikely", "possible", "likely", "almost_certain"}
_VALID_IMPACT = {"negligible", "insignificant", "minor", "moderate", "major", "severe", "catastrophic"}
_VALID_SEVERITY = {"low", "medium", "high", "critical"}
_VALID_RISK_STATUSES = {"open", "mitigating", "monitoring", "mitigated", "closed", "accepted"}
```

**Note the asymmetry: 5 likelihood levels, 7 impact levels.** A hand-written
5x5 matrix — the obvious first design — silently fails to rate a risk with
`impact="insignificant"` or `impact="catastrophic"`, both of which are
already-valid, already-accepted values today. §1.2's matrix accounts for all 7.

```python
async def _validate_risk_payload(self, payload: ProjectRiskCreate | ProjectRiskUpdate) -> None:
    if hasattr(payload, "likelihood") and payload.likelihood is not None:
        if payload.likelihood not in _VALID_LIKELIHOOD:
            raise HTTPException(status_code=400, detail=f"Invalid likelihood: {payload.likelihood}")
    if hasattr(payload, "impact") and payload.impact is not None:
        if payload.impact not in _VALID_IMPACT:
            raise HTTPException(status_code=400, detail=f"Invalid impact: {payload.impact}")
    if hasattr(payload, "severity") and payload.severity is not None:
        if payload.severity not in _VALID_SEVERITY:
            raise HTTPException(status_code=400, detail=f"Invalid severity: {payload.severity}")
    if hasattr(payload, "status") and payload.status is not None:
        if payload.status not in _VALID_RISK_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid risk status: {payload.status}")
    await self._validate_owner(payload.owner_id if hasattr(payload, "owner_id") else None)
```

```python
# create_risk() — severity is a straight passthrough
severity=payload.severity,
```

```python
# update_risk() — severity is in the generic settable-fields loop
for field in ("title", "description", "category", "likelihood", "impact",
              "severity", "owner_id", "mitigation", "contingency", "status",
              "review_date", "source_reference", "active"):
    value = getattr(payload, field)
    if value is not None:
        setattr(risk, field, value)
```

This needs a real before/after, not a description — see §1.2.

### 0.6 Confirmed — no KPI matching infrastructure exists to reuse

`ProjectMetric.source_mapping` is a free-form `dict | None` with no
candidate/job/audit trail behind it, and no `source_match`, `matching_job`, or
similar table/service exists anywhere in `platform-api/app`. The plan's KPI
matching subsystem (candidate generation, validation, states, audit) is new
work in full, exactly as the plan frames it — nothing to correct here, just
confirming there is no partial version to accidentally duplicate or diverge
from.

### 0.7 Confirmed — the plan's named base branch does not exist, but the work it wants is already merged

`devin/project-actions-monday-refresh` is not a real ref. However,
`origin/devin/r-echarts-e2e-validation`'s history contains
`Merge devin/project-actions-monday-workspace into devin/r-echarts-e2e-validation`
— the "Monday-style Project Actions workspace" patterns the plan wants as
precedent are **already in the base branch**. Branch from
`origin/devin/r-echarts-e2e-validation` directly; there is no separate branch
to hunt for.

### 0.8 Blocking — migration number collision with a sibling in-flight branch

Migration head on `origin/devin/r-echarts-e2e-validation` is
`0069_project_actions_workspace.py` (`revision = "0069"`), so the next revision
is **`0070`**.

**A second, unrelated branch — `devin/llm-framework-huggingface-offline-deployment`
— was built from the same base and has already claimed revision `0070`** for
its own tables (`llm_model_artifacts`, `llm_runtime_targets`, etc.). If both
branches are open simultaneously, whichever merges second will fail
`alembic upgrade head` with a duplicate-revision error, or worse, silently
create two heads if the numbers don't collide but both declare
`down_revision = "0069"`.

**Before writing this branch's migration:**
1. Check whether `devin/llm-framework-huggingface-offline-deployment` has
   merged yet. If it has, your migration head is `0070` and this branch's
   revision is `0071`.
2. If it has not merged, coordinate revision numbers explicitly rather than
   both branches guessing `0070` — or generate the revision id only at merge
   time (`alembic revision` against the actual merge-target HEAD), not while
   developing in isolation.
3. State the exact revision chain (`revision` / `down_revision`) you used in
   the PR description, per the plan's own instruction — this is exactly the
   case that instruction exists for.

---

## 1. Corrections and enhancements, with before/after code

### 1.1 Register the KPI-matching arq task — the "will be missed in build" risk

**Before** (`platform-api/app/tasks/workflows.py`):

```python
class WorkerSettings:
    """arq worker entrypoint."""

    on_startup: ClassVar = _configure_worker_logging
    redis_settings: ClassVar[RedisSettings] = _redis_settings()
    functions: ClassVar[list] = [
        process_upload,
        index_for_search,
        sync_saas_object,
        analyze_project_intelligence,
        scan_repository_connection,
        rebuild_knowledge_graph,
        run_knowledge_graph_health_check,
        recover_stale_graph_builds,
        evaluate_stale_graphs,
        reprocess_project,
        refresh_business_insight_result,
        rebuild_project_insight,
    ]
```

**After:**

```python
from app.tasks.kpi_source_matching import match_kpi_data_source  # new module, §3.3

class WorkerSettings:
    """arq worker entrypoint."""

    on_startup: ClassVar = _configure_worker_logging
    redis_settings: ClassVar[RedisSettings] = _redis_settings()
    functions: ClassVar[list] = [
        process_upload,
        index_for_search,
        sync_saas_object,
        analyze_project_intelligence,
        scan_repository_connection,
        rebuild_knowledge_graph,
        run_knowledge_graph_health_check,
        recover_stale_graph_builds,
        evaluate_stale_graphs,
        reprocess_project,
        refresh_business_insight_result,
        rebuild_project_insight,
        match_kpi_data_source,   # ← without this line the job enqueues and never runs
    ]
```

**Verification the PR must include:** enqueue one matching job in a test
environment and show the arq worker log picking it up
(`arq.worker: X.XXs → match_kpi_data_source(...)`), not just that
`POST /kpis/{id}/source-match-jobs` returned `202`. A `202` with a persisted
row proves the write path works; it proves nothing about whether the task
runs.

### 1.2 Server-authoritative risk rating — before/after

**Before** (`platform-api/app/services/project_context.py`):

```python
_VALID_SEVERITY = {"low", "medium", "high", "critical"}
_VALID_RISK_STATUSES = {"open", "mitigating", "monitoring", "mitigated", "closed", "accepted"}

...

async def _validate_risk_payload(self, payload: ProjectRiskCreate | ProjectRiskUpdate) -> None:
    if hasattr(payload, "severity") and payload.severity is not None:
        if payload.severity not in _VALID_SEVERITY:
            raise HTTPException(status_code=400, detail=f"Invalid severity: {payload.severity}")
    ...

async def create_risk(self, project_id: int, payload: ProjectRiskCreate) -> ProjectRisk:
    ...
    risk = ProjectRisk(
        ...
        likelihood=payload.likelihood,
        impact=payload.impact,
        severity=payload.severity,          # ← client-authoritative today
        ...
    )
```

**After** — add `platform-api/app/services/risk_rating.py` (new file, does not
touch existing service logic beyond the two call sites below). Likelihood (5
levels) and impact (**7** levels, per §0.5) are normalized to `1..5` and
`1..7` and combined by a weighted-product formula rather than a hand-written
grid, which is what makes covering all 35 combinations tractable and
verifiable — a literal `dict` of 35 entries is exactly the kind of table a
reviewer skims instead of checks:

```python
"""Versioned likelihood x impact risk-rating.

The plan requires the server to be authoritative for risk severity; the client
may preview a computed value but must never set it directly. Versioned so a
later change to the formula does not silently reinterpret historical ratings —
existing rows keep the version they were rated under.

Likelihood carries 5 levels and impact carries 7 (matching _VALID_LIKELIHOOD /
_VALID_IMPACT in project_context.py) — an asymmetric hand-written 5x5 grid was
the original draft here and silently failed to rate "insignificant" or
"catastrophic" impact, both already-valid values. A normalized product avoids
that by construction: every (likelihood, impact) pair maps to *some* bucket.
"""
from __future__ import annotations

RATING_MATRIX_VERSION = 1

_LIKELIHOOD_ORDER = {"rare": 1, "unlikely": 2, "possible": 3, "likely": 4, "almost_certain": 5}
_IMPACT_ORDER = {
    "negligible": 1, "insignificant": 2, "minor": 3, "moderate": 4,
    "major": 5, "severe": 6, "catastrophic": 7,
}
# Normalized score = (likelihood/5) * (impact/7), range (0, 1]. Thresholds
# chosen so a "possible" x "moderate" risk (the middle of both scales) lands
# in "medium", matching the plan's own worked example.
_THRESHOLDS = (  # (max_score_exclusive_upper_bound, severity)
    (0.20, "low"),
    (0.45, "medium"),
    (0.70, "high"),
    (1.01, "critical"),  # 1.01 so a perfect 1.0 (almost_certain x catastrophic) is included
)


def compute_severity(likelihood: str | None, impact: str | None) -> str | None:
    """Returns the computed rating, or None if either input is missing/unrecognised.

    None (not a fallback severity) is deliberate: a risk with no likelihood/impact
    set is unrated, not "low" — conflating the two would understate real risk.
    """
    li, im = _LIKELIHOOD_ORDER.get(likelihood or ""), _IMPACT_ORDER.get(impact or "")
    if li is None or im is None:
        return None
    score = (li / 5) * (im / 7)
    for upper_bound, severity in _THRESHOLDS:
        if score < upper_bound:
            return severity
    return "critical"  # unreachable given the 1.01 sentinel; satisfies mypy
```

The full 35-combination output, verified by running the formula above (not
hand-computed):

```
low (13):      rare×{negligible..major,severe}, unlikely×{negligible,insignificant,minor},
               possible×{negligible,insignificant}, likely×negligible, almost_certain×negligible
medium (12):   rare×catastrophic, unlikely×{moderate,major,severe,catastrophic},
               possible×{minor,moderate,major}, likely×{insignificant,minor},
               almost_certain×{insignificant,minor}
high (6):      likely×{moderate,major,severe}, possible×{severe,catastrophic}, almost_certain×moderate
critical (4):  likely×catastrophic, almost_certain×{major,severe,catastrophic}
```

It is monotonic in both dimensions and the extremes land where expected
(rare×negligible = low, almost_certain×catastrophic = critical = 1.0 exactly).
One result is worth flagging rather than let a reviewer stumble on it:
**`rare×catastrophic` (medium) outranks `almost_certain×negligible` (low)** —
a rare-but-catastrophic risk rates higher than a near-certain-but-negligible
one. That is standard, deliberate risk-matrix behavior (tail risk isn't
dismissed just because it's unlikely), not a bug, but call it out in the PR so
it isn't "fixed" by someone who hasn't seen a risk matrix before.

Present this table for human sign-off on the threshold choice before merging —
the exact cut points (`0.20/0.45/0.70`) are a product decision, not something
to bury in code.

```python
# project_context.py — _validate_risk_payload: reject a client-supplied
# severity outright (rather than silently overwriting it) so a caller relying
# on the old contract gets a clear 400 instead of a quietly ignored field.
# Every other check is unchanged from the current function — only the
# severity branch changes, from "validate against an allow-list" to "reject".
async def _validate_risk_payload(self, payload: ProjectRiskCreate | ProjectRiskUpdate) -> None:
    if hasattr(payload, "likelihood") and payload.likelihood is not None:
        if payload.likelihood not in _VALID_LIKELIHOOD:
            raise HTTPException(status_code=400, detail=f"Invalid likelihood: {payload.likelihood}")
    if hasattr(payload, "impact") and payload.impact is not None:
        if payload.impact not in _VALID_IMPACT:
            raise HTTPException(status_code=400, detail=f"Invalid impact: {payload.impact}")
    if getattr(payload, "severity", None) is not None:
        raise HTTPException(
            status_code=400,
            detail="severity is computed by the server from likelihood and impact "
                   "and cannot be set directly.",
        )
    if hasattr(payload, "status") and payload.status is not None:
        if payload.status not in _VALID_RISK_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid risk status: {payload.status}")
    await self._validate_owner(payload.owner_id if hasattr(payload, "owner_id") else None)
```

```python
# create_risk() — compute instead of pass through
from app.services.risk_rating import compute_severity, RATING_MATRIX_VERSION
...
risk = ProjectRisk(
    ...
    likelihood=payload.likelihood,
    impact=payload.impact,
    severity=compute_severity(payload.likelihood, payload.impact),
    rating_matrix_version=RATING_MATRIX_VERSION,   # new column, §1.3
    ...
)
```

```python
# update_risk() — drop "severity" from the client-settable loop, recompute
# whenever either input changes
for field in ("title", "description", "category", "likelihood", "impact",
              "owner_id", "mitigation", "contingency", "status",
              "review_date", "source_reference", "active"):   # "severity" removed
    value = getattr(payload, field)
    if value is not None:
        setattr(risk, field, value)

if payload.likelihood is not None or payload.impact is not None:
    risk.severity = compute_severity(risk.likelihood, risk.impact)
    risk.rating_matrix_version = RATING_MATRIX_VERSION
```

**Frontend:** `ProjectRiskBase.severity` becomes response-only. The create/edit
dialog computes a **preview** client-side (same matrix, duplicated
intentionally — it's a pure lookup table, not worth a round-trip for a live
preview) and labels it "Preview — calculated on save," matching the plan's
"client may preview... must not be authoritative."

**Schema/migration note:** `rating_matrix_version` is a new nullable-then-backfilled
column on `project_risks`, additive per the plan's own migration rules. Existing
risks get backfilled with `compute_severity(likelihood, impact)` where both are
set; where either is null, leave `severity` as whatever was already stored and
`rating_matrix_version` null — do not overwrite a manually-entered historical
rating with `None` just because the inputs are missing.

### 1.3 `success_criterion_id` backfill — verify the ambiguous-link count before writing the migration

The plan says: *"Backfill it where an existing metric has exactly one
`ProjectGoalMetricLink`... leave ambiguous/unlinked legacy metrics unchanged
and report them."* Get the real numbers first — this determines whether the
backfill is a non-event or needs a manual-review step in the rollout:

```sql
-- Run against a production-like snapshot before finalizing the migration.
-- links_per_metric = 0  -> unlinked, left as NULL, fine
-- links_per_metric = 1  -> the only case backfilled automatically
-- links_per_metric > 1  -> ambiguous, must be reported, not guessed
SELECT links_per_metric, count(*) AS metric_count
FROM (
    SELECT m.id, count(l.goal_id) AS links_per_metric
    FROM project_metrics m
    LEFT JOIN project_goal_metric_links l ON l.metric_id = m.id
    GROUP BY m.id
) t
GROUP BY links_per_metric
ORDER BY links_per_metric;
```

Put this query's actual output in the PR description (the plan asks for
"migration validation" reporting — this is that report, and it should exist
before the migration is written, not discovered after).

---

## 2. Phase additions

The plan's four phases are sound. Two additions:

### 2.1 Phase 1 must include §1.1's arq registration and a smoke test for it

Not "add the matching job infrastructure" as prose — add the line in
`WorkerSettings.functions` and the enqueue-to-dequeue proof from §1.1, as an
explicit Phase 1 exit criterion. It is cheap to do now and expensive to
discover missing after Phase 3 ships a UI in front of a queue nothing drains.

### 2.2 Phase 1 must resolve §0.8 before generating a migration file

Confirm the live migration head **and** whether the LLM-framework branch has
merged, per §0.8, as the literal first commit of this branch. Do not let two
branches independently guess the same revision number.

---

## 3. Branch and PR instructions (supersedes the plan's §Branch and PR instructions)

```bash
git fetch origin
git checkout -b devin/business-context-success-criteria-kpis-risks origin/devin/r-echarts-e2e-validation
```

Do not search for `devin/project-actions-monday-refresh` — it does not exist.
The Project Actions workspace patterns are already present in
`devin/r-echarts-e2e-validation` (§0.7).

**Preserving existing code — explicit do-not-touch list:**

- `web-ui/components/tablescope/nav.ts:178` — already registers the route.
  Extend nothing here; do not add a second entry.
- `platform-api/app/main.py:48,239` — already imports and registers
  `project_context_routes`. Do not add a second `include_router`.
- Every existing endpoint under `/projects/{project_id}/{goals,metrics,risks}`
  — keep them working unmodified, per the plan's own compatibility
  requirement; the new composite endpoints are additive siblings.
- `project_goal_risk_links`, `project_risk_metric_links` tables — preserve
  rows and the ORM relationships (`ProjectRisk.goal_links`,
  `ProjectRisk.metric_links` already exist and are populated by
  `_sync_risk_links`); just stop requiring or surfacing them in the new
  workspace UI, as the plan says.

**Commits**, in the order the plan specifies, with one addition:

1. schema/migration and compatibility layer — **resolve §0.8 first, include
   the §1.3 backfill report in the commit message or PR body**;
2. API/service/rollup/rating changes — **include §1.2's before/after**;
3. full-width Business Context workspace;
4. KPI matching jobs and validation — **include §1.1's `WorkerSettings`
   registration in this commit, not deferred to a later one**;
5. AI-context integration;
6. tests, documentation, feature flags, and rollout telemetry — **add both
   flags to `docker-compose.yml`'s `&platform_api_env` anchor, not only to
   `.env.example`.** A flag set only in `.env` without a matching
   `${VAR:-default}` line in the compose file's environment block is silently
   ignored by Docker Compose — this bit an unrelated feature on this exact
   codebase before it was caught, and it looks identical to "the flag did
   nothing" from the outside. Confirm both:

   ```yaml
   # docker-compose.yml, platform-api's &platform_api_env anchor
   BUSINESS_CONTEXT_V2_ENABLED: ${BUSINESS_CONTEXT_V2_ENABLED:-false}
   BUSINESS_CONTEXT_KPI_MATCHING_ENABLED: ${BUSINESS_CONTEXT_KPI_MATCHING_ENABLED:-false}
   ```

   and that `platform-api-worker` inherits them (it does, via
   `environment: *platform_api_env` — confirm rather than assume once the
   anchor is edited).

The PR must include everything the original plan's final paragraph asks for,
plus: the §1.3 backfill count report, confirmation of which side of the §0.8
migration-number race this branch landed on, and the §1.1 enqueue-to-dequeue
log proof.
