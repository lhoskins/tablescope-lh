# Devin: merge + deploy — Knowledge Graph validation, Phase 6 (items #41–43: incremental rebuild correctness)

**Repository:** `lhoskins/tablescope-lh`
**Branch to merge:** `kg-validation-phase6-incremental-rebuild`
**Base:** `kg-validation-phase4-activation-kpi` — **not** `UX-design-03` directly. This
branch touches the same file Phase 4 rewrote (`rebuild_execution.py`'s `_validate_payload`/
`_patch_context_nodes`), so it's based on that branch to avoid a conflict. **If Phase 4
hasn't been merged into `UX-design-03` yet, merge Phase 4 first**, then merge this branch
on top (or rebase it onto `UX-design-03` after Phase 4 lands, if you prefer a clean
single-parent history). Phase 5 (`kg-validation-phase5-grounding`) is an unrelated sibling
branch also off Phase 4/earlier — this branch does not depend on it and doesn't touch any
file it modified.

**`platform-api/` only · no migration · all tests green**

---

## Context

Sixth installment of the 50-item Knowledge Graph validation review, closing out the last
three P0 items in Section E (lifecycle/reliability): **#41** (coalesced change-set
merging), **#42** (AI card refresh on incremental rebuild), **#43** (deletion handling in
incremental patches). All three live in the same two files
(`rebuild_request.py`/`rebuild_execution.py`) and share one root cause: the incremental
rebuild path was built to be *cheap* (skip AI enrichment, reuse whatever the caller already
queued) but never revisited once the queueing logic grew request-coalescing on top of it —
so "cheap" quietly became "stale" and, for deletions, "wrong."

## 41. Merge coalesced change sets rather than returning the first queued build unchanged

**Validated:** true, in `rebuild_request.py::request_incremental_rebuild`. When a build is
already `queued` for a project, every subsequent call this session had ever seen simply
`return`ed that same build **completely unchanged**:

```python
if pending is not None:
    return pending, pending.build_type
```

The new change event's `change_set` was silently discarded — never analyzed, never
folded into `affected_entity_summary`. Concretely: a document-change event arrives,
queues a build with `affected_entity_summary = {"affected_types": ["document"], ...}`. A
risk gets created a moment later, before the worker picks up that build. The docstring's
promise — "an incremental run re-reads current source state at execution time, so one
queued build covers every change that lands before it starts" — is only half true: the
*generic* graph reload (`_load_stored_graph`) does re-read everything, but project-context
nodes (goal/metric/risk) are patched in **only** for the types named in
`affected_entity_summary` (see `_patch_context_nodes`, called from
`run_incremental_rebuild`). Since "risk" was never added to that build's summary, the new
risk's context node never gets patched in — not on this build, and not ever, since nothing
re-visits a build once it's queued.

**Fix:** `request_incremental_rebuild` now always runs `impact_analyzer.analyze` for the
new event, and — when a build is already queued — calls a new `_coalesce_change_set`
instead of returning early:
- Unions the new event's `affected_entity_types`/`affected_entity_ids` into the pending
  build's `affected_entity_summary` (deduped, order-preserving).
- Escalates the pending build to `build_type="full"` if *this* event alone isn't safely
  incremental — even if the build was already safely queued as `"incremental"` from an
  earlier, safe event. A build must not stay incremental just because it was incremental
  when it was first created.
- Advances `source_checkpoint["timestamp"]` to the later of the two, so
  `_verify_source_checkpoint` waits for the newest write, not just the first one's.

**Tests:** `tests/test_kg41_incremental_coalescing.py` (4 tests) — a second event's types/
ids actually merge into the same queued build; an unsafe second event (`change_scope:
"schema"`) escalates an already-incremental build to `full`; the source checkpoint
advances to the later timestamp; three rapid events against the same project still
produce exactly one queued build, with all three entity ids present.

## 42. Refresh affected AI cards during incremental rebuilds

**Validated:** true — a code comment in `run_incremental_rebuild` said it outright: *"the
expensive part of a full rebuild is AI enrichment, which stays cached: `aiCardsByCenter`
carries over from the active snapshot unchanged."* An incremental rebuild never called AI
enrichment at all, for any centre, ever — so a KPI/process/document whose content changed
kept showing its insight cards from before the change until the next full rebuild.

**Fix:** new `app/services/knowledge_graph_lifecycle/incremental_cards.py` —
`affected_center_keys(old_nodes, old_edges, new_nodes, new_edges, cached_cards_by_center)`
diffs the graph before/after the incremental patch and returns `(refresh_keys, stale_keys)`:
- **`refresh_keys`**: centres whose own node changed, whose cached card's
  `traceToEvidence.nodeIds` cite a node that changed, or that are newly centre-eligible
  with no cached bundle yet. An edge add/remove/confidence-change also "touches" both of
  its endpoints, so a KPI-to-query relationship changing invalidates the KPI's card too,
  not just a rename.
- **`stale_keys`**: cached centres that are no longer centre-eligible at all (the node was
  deleted/deactivated) — evicted rather than left pointing at nothing.

`_precache_center_cards` (`app/services/knowledge_graph/snapshot.py`) gained an optional
`center_keys` parameter so an incremental rebuild can re-enrich *only* the touched centres
instead of every centre in the project (full rebuild's existing behavior, unchanged —
`center_keys=None` still means "every eligible centre"). `run_incremental_rebuild` now
computes `refresh_keys`/`stale_keys` against the pre-patch snapshot, evicts the stale ones,
and calls `_precache_center_cards` with exactly `refresh_keys` when there's a
`requested_by` user to attribute the AI call to (mirroring the existing full-rebuild gate)
— failure to refresh is caught and logged, falling back to the previously-cached cards for
those centres rather than failing the whole incremental build.

**Deliberately scoped:** detection is a straightforward before/after graph diff, not a
dependency-graph analysis of *why* a card might be stale beyond direct evidence citation —
over-invalidating (re-enriching a centre that turns out not to have needed it) is a safe,
bounded-cost false positive; under-invalidating (the original bug) is not.

**Tests:** `tests/test_kg42_incremental_card_refresh.py` (7 tests) — six unit tests of
`affected_center_keys` (unchanged graph needs nothing; a newly-eligible centre with no
cache needs refresh; a changed centre node needs refresh; a centre whose cached card's
*evidence* node changed needs refresh even though the centre itself didn't; an edge change
touches both endpoints; a removed centre is evicted, not refreshed) plus one end-to-end
integration test against a real project/build/snapshot with a stubbed AI client, proving a
full rebuild enriches both of two centres, and a subsequent incremental rebuild that
changes only one of them re-enriches *only* that one — the untouched centre's cached
bundle is left alone, not silently dropped or needlessly recomputed.

## 43. Handle deletions correctly in incremental patches

**Validated:** true, in `_patch_context_nodes`. For each of goal/metric/risk, the method
queried only the *currently active* rows and upserted them into `node_map` — it never
compared against what was already there, so a goal/metric/risk that was deleted or
deactivated between incremental patches was never removed from the payload. Every prior
incremental rebuild just re-copied whatever context node ids it didn't happen to touch,
forever.

**Fix:** each bucket (`goal`/`metric`/`risk`) now reconciles against its own authoritative
active set instead of only upserting: after upserting every currently-active row, any
existing `node_map` entry whose key has that type's prefix (`"goal:"`/`"metric:"`/
`"risk:"`) but isn't in the just-queried active set is deleted. This doesn't depend on
guessing which specific id was deleted from the flat `affected_ids` list (which isn't
partitioned by type) — it's a full, correct reconciliation of the bucket a patch actually
touches. Nodes removed this way are also tracked, and any edge in the payload referencing
a removed node id is pruned too, so a deleted context node can't leave a dangling edge
reference behind (the review's "and their edges" concern) — currently no code path
actually creates an edge to a goal/metric/risk node, so this is real defense-in-depth
rather than a reachable bug today, exactly like the dangling-edge check added in Phase 4
for the same reason.

**Tests:** `tests/test_kg43_context_node_deletion.py` (4 tests) — a deactivated goal is
removed on the next patch while an untouched sibling goal survives; a hard-deleted metric
is removed; deleting a risk also prunes an edge that pointed at it while leaving an
unrelated node untouched; patching one type (`goal`) never touches nodes of a type that
wasn't named in this call (`risk`), confirming the reconciliation is correctly scoped per
type, not a blanket wipe.

## Tests added

| File | Coverage |
|---|---|
| `tests/test_kg41_incremental_coalescing.py` (4 tests, new file) | change-set union, unsafe-event escalation, checkpoint advancement, no duplicate builds |
| `tests/test_kg42_incremental_card_refresh.py` (7 tests, new file) | touched-centre detection (unit) + selective re-enrichment (integration) |
| `tests/test_kg43_context_node_deletion.py` (4 tests, new file) | deactivation/hard-delete removal, edge pruning, per-type scoping |

All 15 proven to fail against pre-fix code (`git stash` on the fix files, rerun, confirm
failure, restore) before being confirmed passing.

## Verification

| Suite | Result |
|---|---|
| `pytest tests/test_kg41*.py tests/test_kg42*.py tests/test_kg43*.py -q` | 15 passed |
| `pytest tests/test_knowledge_graph_lifecycle.py tests/test_knowledge_graph_rebuild.py tests/test_knowledge_graph_event_triggers.py tests/test_kg21_activation_validation.py tests/test_knowledge_graph_ai.py -q` | 43 passed, 0 regressions |
| `ruff check` (touched files) | clean |
| `mypy` (touched files) | clean |
| Full `pytest -q` (whole platform-api suite) | **1748 passed, 4 skipped, 10 failed** — same 10 pre-existing/unrelated failures as every prior phase (dashboard visualization, percent-change summary statistics, business-insight snapshot staleness) — 0 new |

```bash
cd platform-api
pytest -q
ruff check app/services/knowledge_graph_lifecycle/rebuild_request.py \
  app/services/knowledge_graph_lifecycle/rebuild_execution.py \
  app/services/knowledge_graph_lifecycle/incremental_cards.py \
  app/services/knowledge_graph/snapshot.py
mypy app/services/knowledge_graph_lifecycle/rebuild_request.py \
  app/services/knowledge_graph_lifecycle/rebuild_execution.py \
  app/services/knowledge_graph_lifecycle/incremental_cards.py \
  app/services/knowledge_graph/snapshot.py
```

## Deploy

`platform-api` only, no migration, no `web-ui`/`ai-server` change.

```bash
docker compose build platform-api
docker compose up -d platform-api platform-api-worker
```

## Verify live

- Trigger two change events for the same project in quick succession (before the first
  incremental build starts) affecting different entity types (e.g. a document edit, then a
  risk edit). Confirm the resulting build's `affected_entity_summary.affected_types`
  contains both, and that the eventual patched graph reflects both changes — not just the
  first.
- On a project with an existing active Knowledge Graph, edit a KPI or process node that has
  a cached insight card, trigger an incremental rebuild, and confirm that centre's card
  actually updates (not just the raw graph) while an unrelated centre's card is untouched.
- Deactivate (or delete) a project goal/metric/risk that has a Knowledge Graph context
  node, trigger an incremental rebuild naming that type, and confirm the node disappears
  from the graph rather than lingering.

## Remaining work

Section E's remaining P1 items: #44 (source-checkpoint verification hardening), #45
(durable idempotency/concurrency controls), #46 (recover queued builds with missing
heartbeats), #48 (stage-level metrics/traces/SLOs), #49 (golden end-to-end validation
projects). Item #50 (P0, grounded-answer evaluations) remains deliberately last per the
review's own ordering. Sections C and D still have open P1 items (#24–30, #34–38, #40)
not yet attempted.

## Report back

Confirmation the coalescing/refresh/deletion behavior works correctly live, and whether to
continue with Section E's remaining P1 reliability items next, or move to item #50
(grounded-answer evaluations) as the final P0.

---

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01M7j8CDCHCdwHpw9FrRhLN5
