# Devin-ready implementation plan: Knowledge Graph architecture

Supersedes `docs/devin-kg-architecture-review-brief.md` (PR #122) with a
sequenced, file-level implementation plan. That brief's section 3
recommendations are the basis for this plan; this document turns them into
concrete phases with exact function moves, migration steps, and tests.

## Why now, and what changed since the brief was written

The brief's item-5 diagnosis (connector-style mismatch = deploy/cache
staleness) turned out to be **half right**: the version-gated
snapshot-invalidation mechanism it describes is real and correct, but it
was not the actual cause of the reported mismatch. Direct tracing of the
full pipeline — `_classify_relationship` → `_edge_payload` →
`build_graph_payload` → `build_node_centric_graph_from_snapshot` → the
`GraphEdge` API contract → `knowledge-graph-screen.tsx`'s client-side
filtering → `knowledge-graph-canvas.tsx`'s rendering — found the backend
100% correct end-to-end, and the real bug in the **frontend canvas**:

```ts
// web-ui/components/tablescope/project/knowledge-graph-canvas.tsx (before fix)
const traced =
  tracedNodeIds === null ||                              // ← bug
  (tracedNodeIds.has(e.source) && tracedNodeIds.has(e.target));
```

`tracedNodeIds === null` means "no trace-to-evidence is active" (the normal
browsing state), but this line treated that as "every edge is traced,"
which made `connectorStroke()` always take its flat solid-gray override
branch — silently ignoring `connectorStyle`/`relationshipStrength` for
every edge in the default view. Fixed (this PR) to:

```ts
const traced =
  tracingActive &&
  tracedNodeIds!.has(e.source) && tracedNodeIds!.has(e.target);
```

with a regression test (`knowledge-graph-canvas.test.tsx`) that renders a
Recommended and an Inferred edge with `tracedNodeIds={null}` and asserts
`stroke-dasharray` is actually present — the class of test the brief's
3.5 recommended but that didn't yet exist, and that would have caught this.

**Implication for this plan**: the backend classification pipeline
(`_classify_relationship`, `_edge_payload`, `build_graph_payload`) is
verified correct and stable — the split in Phase 1 below is a pure
refactor with no logic changes, safe to do mechanically. The one place that
needed a real logic fix was the rendering layer, which is *not* in
`knowledge_graph_builder.py` at all — worth remembering when scoping "KG
architecture" work: the frontend canvas is part of this system's
architecture too, not just the backend service.

## Phase 1 — Split `knowledge_graph_builder.py` (mechanical, low-risk)

1,653 lines, 14 commits of churn on this branch alone. Split into:

| New file | Moves from `knowledge_graph_builder.py` |
|---|---|
| `services/knowledge_graph/loader.py` | Raw node/edge DB loading, `_load_stored_graph`, `enrich_node`, `_is_canvas_hidden`, `_pick_center`, `_highest_degree`, `_neighborhood` |
| `services/knowledge_graph/classifier.py` | `_classify_relationship`, `classify_connector_style`, `_edge_confidence`, `_evidence_basis`, `_evidence_summary`, the `_REFERENCE_MEMBERSHIP_REL_TYPES`/`_RECOMMENDED_REL_TYPES`/`_INFERRED_REL_TYPES` constants |
| `services/knowledge_graph/cards.py` | `_build_card_for_node`, `_build_gap_finding`, `_center_overview_card`, `_kpi_measurement_gap_card`, `_rank_and_dedupe_cards`, `_precache_center_cards` (if present under this name) |
| `services/knowledge_graph/snapshot.py` | `rebuild_project_graph_snapshot`, `get_project_graph_snapshot`, `get_project_graph_data`, `SNAPSHOT_PIPELINE_VERSION`, the pipeline-version staleness check |
| `services/knowledge_graph/renderer.py` | `build_graph_payload`, `build_node_centric_graph_from_snapshot`, `build_node_centric_graph`, `_edge_payload`, `_stats`, `_empty_stats` |

`knowledge_graph_builder.py` becomes a thin re-export shim:
```python
from .knowledge_graph.classifier import classify_connector_style  # noqa: F401
from .knowledge_graph.renderer import build_graph_payload  # noqa: F401
# ... every current public name, re-exported ...
```
so every existing `from app.services.knowledge_graph_builder import X` in
`project_graph.py`, `home_intelligence.py`, `knowledge_graph_ai_context.py`,
and `tests/test_knowledge_graph.py` keeps working without touching those
call sites in this phase.

**Steps:**
1. Create the five new files, move the listed functions verbatim (no logic
   changes), fixing only intra-module imports.
2. Turn `knowledge_graph_builder.py` into the re-export shim.
3. Run `tests/test_knowledge_graph.py` unchanged — it must pass without
   modification, proving the split didn't change behavior.
4. Only after Phase 1 is merged and stable, update call sites to import
   directly from the new submodules and delete the shim (a separate,
   later cleanup — don't couple it to this phase).

## Phase 2 — Decouple KG rebuild from insight rebuild via an explicit event

Today, `rebuild_knowledge_graph` (the arq worker in `app/tasks/workflows.py`)
directly calls `mark_project_insight_stale()` and conditionally
`enqueue_rebuild_project_insight()` / `enqueue_refresh_business_insight_result()`
inline, in its own try/except blocks. A slow or failing KG build stalls both
downstream insight types with no independent retry policy per consumer.

1. Add a `knowledge_graph_rebuilt` arq job registered in `WorkerSettings`
   that takes `(tenant_id, project_id, build_id)` and does exactly what
   `rebuild_knowledge_graph` currently does inline after a successful build:
   `mark_project_insight_stale()` + the two conditional enqueues.
2. `rebuild_knowledge_graph` itself just enqueues `knowledge_graph_rebuilt`
   on success instead of doing the insight-side work inline.
3. This means a bug/slowdown in the insight-side reaction (e.g. a
   `mark_project_insight_stale()` DB hiccup) can't block or fail the KG
   build's own retry/backoff bookkeeping, and vice versa — each has its own
   arq `max_tries`/backoff.
4. Test: assert `rebuild_knowledge_graph` succeeding enqueues exactly one
   `knowledge_graph_rebuilt` job (mock `enqueue_job`); assert
   `knowledge_graph_rebuilt` itself calls `mark_project_insight_stale` and
   the two conditional enqueues, independent of the build task.

## Phase 3 — Deploy-version parity for `SNAPSHOT_PIPELINE_VERSION`

This session repeatedly found fixes that were correct in the repo but not
what was actually deployed (2FA enforcement, demo-refresh windowing, Quick
Actions routing). `SNAPSHOT_PIPELINE_VERSION` is exactly this risk pattern
concentrated into one constant: a snapshot's staleness check only works if
the *running* process's constant reflects the *intended* current code.

1. Add a lightweight startup check in `platform-api`'s app lifespan (where
   other startup checks already live, if any — otherwise a new
   `app/startup_checks.py`): on boot, log the running
   `SNAPSHOT_PIPELINE_VERSION` and — for the N most-recently-active
   projects (by `IntelligenceSnapshot.updated_at`, reusing the same
   activity-gate pattern as `business_insight_refresh_activity_days`) —
   check whether their KG snapshot's stored `pipeline_version` differs from
   the running constant, and if so enqueue a rebuild proactively instead of
   waiting for a user's page load to trigger it.
2. Add `pipelineVersion` to whatever response already carries build/version
   metadata to the frontend (it's already in the snapshot; just confirm the
   knowledge-graph API response surfaces it) so a future frontend banner
   ("this graph was built under an older version — refresh recommended")
   is possible without another backend change.
3. Do not attempt to make `SNAPSHOT_PIPELINE_VERSION` "immutable/build-time
   derived" (e.g. from a build hash) in this phase — that's a bigger
   deploy-pipeline change or (given every fix found so far this session)
   sits on the same "what's actually deployed" root problem already being
   addressed by consolidating branches into `devin/r-echarts-e2e-validation`
   (PR #120) — re-evaluate once that consolidation pattern is standard
   practice rather than adding a second, parallel mechanism now.

## Phase 4 — Enforce the document → graph ordering contract

1. Add a `source_checkpoint` (a transaction/commit timestamp or monotonic
   counter) parameter to `request_event_driven_rebuild()`. The caller
   (`document_processing_service.py`, `reference_library_processing.py`)
   passes the timestamp of its own just-committed write.
2. In the KG rebuild worker, before reading `ai_project_graph_nodes`/
   `ai_project_graph_edges`, verify the staging tables' `updated_at` for the
   affected project is `>= source_checkpoint`. If not yet visible (replica
   lag, or the coalesced build fired before the triggering write actually
   flushed), defer via the same `Retry` mechanism already used elsewhere in
   `workflows.py` (e.g. `home_intelligence.py`'s tenant-slot retry) rather
   than silently building on stale data.
3. Test: simulate a document upload commit, immediately trigger a rebuild
   with a `source_checkpoint` from *before* the commit lands (mock a delay),
   assert the worker retries rather than building; then let the commit
   "land" and assert the retry succeeds and reads the new rows.

## Phase 5 — Test coverage for the classification/rendering contract

Building on what Phase 1's split makes newly-testable in isolation:

1. `classifier.py`: parametrized unit tests over every combination of
   `relationship_type` × `evidence.validation_status` × `evidence.basis`
   that `_classify_relationship` branches on — assert
   `(relationshipStrength, connectorStyle, displayByDefault)` for each
   combination, not just the couple of cases already covered by
   `test_knowledge_graph.py`.
2. `renderer.py`: assert `build_graph_payload`'s edge filtering
   (`min_confidence`/`include_inferred`) and the `_edge_payload` output
   shape are unchanged by the split (snapshot-test the full payload against
   a fixed input, byte-for-byte, before and after Phase 1).
3. Frontend: the `connectorStroke`/canvas tests added by this PR
   (`knowledge-graph-canvas.test.tsx`) are the first tests asserting actual
   rendered `stroke-dasharray` values — extend this pattern to cover
   `edgeOpacity` too (Recommended/Weak/Hidden edges should render faded,
   not just correctly dashed), since that's adjacent, currently-untested
   logic in the same file.
4. Add one true end-to-end test (backend classify → API → frontend filter →
   canvas render) if the test infra supports it, specifically covering the
   default (non-tracing) view — this is the exact configuration the real
   bug lived in and that no existing test exercised.

## Sequencing and risk

- Phase 1 (split) should land first and alone — it's the highest-leverage,
  lowest-risk change (no behavior change) and makes every later phase
  easier to review and test in isolation.
- Phases 2 and 4 change worker control flow and touch retry semantics —
  land and soak these independently, not combined, given how much of this
  session's other work involved subtle retry/backoff bugs
  (`acquire_tenant_slot`'s TTL-refresh bug from earlier this session is a
  cautionary example of exactly this class of change going wrong quietly).
- Phase 3 is additive (a new startup check + response field) and safe to
  land any time after Phase 1.
- Phase 5 should grow alongside each of the other phases rather than as a
  single follow-up pass — each phase's own steps above already specify the
  tests it needs.
