# Devin: merge + deploy — Knowledge Graph validation, Phase 8 (items #48–49: observability + golden fixtures)

**Repository:** `lhoskins/tablescope-lh`
**Branch to merge:** `kg-validation-phase8-observability-goldens`
**Base:** `kg-validation-phase7-lifecycle-reliability` — **not** `UX-design-03` directly.
This branch's `#48` work touches the same file Phase 7 modified
(`rebuild_execution.py`'s `_transition_build`/`_fail_build`), so it's based on that branch
to avoid a conflict. **If Phase 7 hasn't been merged into `UX-design-03` yet, merge Phase 7
first**, then merge this branch on top.

**`platform-api/` + one migration (0089, additive/nullable column, no backfill needed) ·
all tests green**

---

## Context

Eighth installment of the 50-item Knowledge Graph validation review, closing out Section
E's remaining P1 items short of the deliberately-last #50: **#48** (stage-level metrics/
traces/SLOs) and **#49** (golden end-to-end KG validation projects).

## 48. Add stage-level metrics, traces, and service-level objectives

**Validated:** true. `KnowledgeGraphBuild` tracked `stage`/`progress`/`queued_at`/
`started_at`/`completed_at`, but nothing recorded *how long* any individual stage took —
an operator looking at a slow or failed build had `stage="ai_enrichment"` and a timestamp
range for the whole build, nothing narrower. None of the review's named signals (queue
delay, extraction/graph-load time, AI time, validation time, activation time, token usage,
cost, cache hit rate, failure category) were captured anywhere.

**Fix:** new `stage_metrics` JSON column on `knowledge_graph_builds` (migration `0089`,
additive/nullable, no backfill). `_transition_build` and `_fail_build`
(`rebuild_execution.py`) now close out the time spent in the build's *current* stage every
time the stage changes or the build reaches a terminal status, via a shared
`_finalize_stage_duration` helper — the elapsed time is added to
`stage_metrics["durations_ms"][<stage name>]`. Because the very first call has no prior
marker, it falls back to `queued_at`, so the first stage closed out (always "queued", the
stage a build is created with) captures **queue delay** for free, with no separate field
needed. Walking a normal successful full rebuild produces
`durations_ms = {"queued": ..., "initializing": ..., "fingerprinting": ..., "loading_sources": ...,
"ai_enrichment": ..., "validating": ..., "activating": ...}` — directly mapping onto the
review's named stages (extraction ≈ fingerprinting, graph load ≈ loading_sources, AI time
≈ ai_enrichment, validation time ≈ validating, activation time ≈ activating).
`retry_attempt` (an existing column) and `failure_category` (`error_code` at the point of
failure) are copied into the same dict on every terminal transition, and `_fail_build` —
which bypasses `_transition_build` entirely on a validation failure — gets the identical
treatment so a failed build's partial stage timings and failure category are captured too,
not just a successful build's full set. `KnowledgeGraphBuildRead` (the API-facing schema
behind the existing `/status` route) now exposes `stage_metrics`, so an operator can
already answer "which stage was slow/failing for build ID N" from the existing status API
with no new endpoint.

**Deliberately not done:** token usage, cost, and AI cache-hit-rate. Nothing in the
codebase's AI client (`app/services/ai_intelligence_client/`) currently surfaces
per-request token counts or cost — instrumenting that is a separate, larger change to the
AI client itself, not a rebuild-pipeline bookkeeping addition, and out of proportion to
this item's core "which stage is slow/failing" ask. Source counts are also not duplicated
into `stage_metrics` — they're already recorded per build via the linked
`KnowledgeGraphVersion.node_count`/`edge_count`/`validation_summary`, so adding a second
copy would only create a second source of truth to drift.

**Tests:** `tests/test_kg48_stage_metrics.py` (2 tests) — a successful full rebuild records
a non-negative duration for every stage the pipeline actually walks through, plus
`retry_attempt=0` and `failure_category=None`; a validation-failure rebuild (reusing the
same under-connected-candidate fixture from Phase 4's activation-validation tests) records
`failure_category="validation_failed"` and durations for every stage reached before
failure, but *not* `"activating"`, which never ran.

## 49. Build golden end-to-end KG validation projects

**Validated:** true — there was no fixture-based regression suite comparing an actual
built graph against a reviewed-correct expectation; every existing KG test asserts
behavior in isolation (a specific validator, a specific matcher), not "does building this
whole realistic project still produce the graph we expect."

**Fix:** `tests/test_kg49_golden_fixtures.py` — five golden projects, each seeded through
real `AIProjectGraphNode`/`AIProjectGraphEdge` rows and built via the actual
`run_full_rebuild` pipeline (not a mocked/stubbed shortcut), asserting the resulting
`KnowledgeGraphVersion.node_count`/`edge_count`/`validation_summary` and, where relevant,
specific lineage edges match a recorded golden value:
- **small** — a minimal 2-node graph activates cleanly (node/edge counts, `valid=True`).
- **sparse** — a graph landing at *exactly* the 50% orphan-ratio boundary (the
  `_BLOCKING_ORPHAN_RATIO` threshold from Phase 4) stays valid with a warning, not a
  rejection — pins the boundary behavior precisely rather than leaving it to drift.
- **contradictory** — a KPI named "Rate" and an unrelated query ("Corporate Rate Card
  Report") whose names superficially overlap must not get a fabricated "measures" edge
  between them — a direct regression pin on KG-19's word-boundary KPI-matching fix.
- **multi_tenant** — two tenants built in the same test run never see each other's nodes
  in their own snapshot — a regression pin on tenant isolation.
- **medium** — a richer 5-node, multi-entity-type graph (KPI, query, dashboard, document,
  process) builds successfully with the exact expected lineage edges
  (`measures`/`visualizes`/`governs`) present between the exact node pairs seeded.

Each golden's expected values were established by running the real pipeline once and
recording its (reviewed) actual output — the two initial edge-count mismatches caught
during that process (`small`/`medium` were each off by one) turned out to be the existing,
correct `collect_structural_graph` behavior of always linking a KPI node to the hub with a
low-noise `recommended_kpi` edge, not a bug; the goldens were corrected to include it.

**Deliberately scoped down from all eight named fixture shapes:** **large** isn't built as
a separate fixture — it would exercise the same code paths as "medium" with no additional
regression-detection value at unit-test scale, only added runtime. Standalone
**multi-table**/**multi-document** fixtures aren't built either — their essential coverage
(multiple data-source/document nodes feeding one graph) is already exercised by "medium".
**Answers** (grounded AI response evaluation against these projects) is out of scope here
entirely — it's the review's own item **#50**, a separate, larger downstream-evaluation
effort that this phase deliberately leaves for last, matching the review's own ordering.

**Tests:** `tests/test_kg49_golden_fixtures.py` (5 tests, new file, no production code
change — this item is test infrastructure, not a bug fix).

## Tests added

| File | Coverage |
|---|---|
| `tests/test_kg48_stage_metrics.py` (2 tests, new file) | per-stage durations on success and on validation failure |
| `tests/test_kg49_golden_fixtures.py` (5 tests, new file) | small/sparse/contradictory/multi-tenant/medium golden end-to-end builds |

KG-48's tests proven to fail against pre-fix code (`git stash` on the three fix files —
model, schema, `rebuild_execution.py` — rerun, confirm both fail with
`AttributeError: 'KnowledgeGraphBuild' object has no attribute 'stage_metrics'`, restore,
confirm both pass). KG-49 has no accompanying production-code fix (it's new regression
test infrastructure), so the fail-before-fix step doesn't apply the way it does for a bug
fix — its five tests instead had two rounds of "run once, discover the true golden value,
correct the recorded expectation" during authoring, both traced to the real (correct)
`recommended_kpi` auto-edge, not a bug.

## Verification

| Suite | Result |
|---|---|
| `pytest tests/test_kg48*.py tests/test_kg49*.py -q` | 7 passed |
| `pytest tests/test_knowledge_graph_lifecycle.py tests/test_knowledge_graph_rebuild.py tests/test_knowledge_graph_event_triggers.py tests/test_kg21_activation_validation.py tests/test_kg41*.py tests/test_kg42*.py tests/test_kg43*.py tests/test_kg44*.py tests/test_kg45*.py tests/test_kg46*.py tests/test_kg48*.py tests/test_kg49*.py -q` | 69 passed, 0 regressions |
| `ruff check` (touched files) | clean |
| `mypy` (touched files) | clean |
| Full `pytest -q` (whole platform-api suite) | **1775 passed, 4 skipped, 10 failed** — same 10 pre-existing/unrelated failures as every prior phase (dashboard visualization, percent-change summary statistics, business-insight snapshot staleness) — 0 new |
| `alembic heads` | single head `0089`, `down_revision="0088"` — chain intact |

```bash
cd platform-api
alembic upgrade head
pytest -q
ruff check app/services/knowledge_graph_lifecycle/rebuild_execution.py \
  app/models/knowledge_graph_lifecycle.py \
  app/schemas/knowledge_graph.py
mypy app/services/knowledge_graph_lifecycle/rebuild_execution.py \
  app/models/knowledge_graph_lifecycle.py \
  app/schemas/knowledge_graph.py
```

## Deploy

`platform-api` only. **One migration this time** (`0089`, additive nullable column, no
backfill/downtime concern) — run it before or as part of the deploy, then restart both
processes.

```bash
cd platform-api
alembic upgrade head
docker compose build platform-api
docker compose up -d platform-api platform-api-worker
```

## Verify live

- Trigger a full rebuild for a real project, then `GET .../knowledge-graph/status` and
  confirm the build entry's `stage_metrics.durations_ms` has an entry for every stage the
  build walked through, with plausible (non-zero, non-negative) millisecond values.
- Trigger a rebuild you know will fail validation (or use a project with a known-broken
  graph) and confirm `stage_metrics.failure_category` matches the build's `error_code` and
  that stages after the failure point are absent.
- No golden-fixture action needed live — `tests/test_kg49_golden_fixtures.py` runs as part
  of the standard CI test suite on every future change, which is the enforcement mechanism
  itself.

## Remaining work

Section E is now fully closed except item **#50** (P0, deliberately last per the review's
own ordering — grounded-answer evaluations across AI Assistant, Business Insights, Project
Insights, Executive Brief, dashboard generation, and query generation). Sections A
(#08–09), B (#12/14/16–18/20), C (#24–30), and D (#32/34–38/40) still have open P1/P0
items not yet attempted.

## Report back

Confirmation `stage_metrics` shows sensible per-stage timing live, and whether to move to
item #50 next (the last P0, and a natural point to pause and take stock of the full
50-item effort) or continue into one of the still-open Section B/C/D P1 batches first.

---

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01M7j8CDCHCdwHpw9FrRhLN5
