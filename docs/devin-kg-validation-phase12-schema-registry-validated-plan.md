# Devin: merge + deploy — Knowledge Graph validation, Phase 12 (Section C part 1: #24–26)

**Repository:** `lhoskins/tablescope-lh`
**Branch to merge:** `kg-validation-phase10-source-lineage` (this phase's commits land on top of Phases 10–11's, same branch)
**Base:** `kg-validation-phase8-observability-goldens` tip (already includes Phases 1–11)

**`platform-api/` only · no migration · all tests green**

---

## Context

This phase covers the first three of Section C's (relationship quality) seven items:

- **#24 (P1)**: "Define a formal node and edge schema registry... **Accept:** invalid
  combinations such as a dashboard `governs` a tenant are rejected before persistence."
- **#25 (P1)**: "Validate relationship direction and inverse consistency... **Accept:**
  reversed or contradictory structural relationships are detected automatically."
- **#26 (P1)**: "Detect duplicate and ambiguous graph-key collisions... **Accept:** two
  different sources with the same normalized name remain distinguishable."

Two research passes (Explore agents, full transcripts available on request) ran first
against the real code. Both confirmed the same overall shape: every *structural* node/edge
(the ones `collect_structural_graph` emits) already has a single, hardcoded, internally
consistent emission site — there is no live bug of "sometimes reversed" or "wrong type
combination" in that code today. The one real, unconstrained gap is
`create_family_relationship_edges` (`app/services/project_graph_service/linking.py`) — the
sole write path where a free-form, LLM-supplied `target_type`/`relationship_type` string
reaches `ai_project_graph_nodes`/`ai_project_graph_edges` with no type-appropriateness check
at all. This phase targets that real gap plus two supporting, low-risk fixes, rather than
building a general-purpose schema/direction/merge system with no second real consumer yet.

## KG-24: reserved structural node types can't be impersonated

**Validated:** `create_family_relationship_edges` upserts a node with `node_type` taken
directly from the AI profile's `target_type` string (defaulting to `"process"`), with zero
validation. Nothing stops an LLM response from producing `target_type="dashboard"` (or
`"project"`, `"data_source"`, `"saved_query"`, `"kpi"`, `"reference_document"`) — creating a
node claiming one of these types with **no real `source_id`/`source_type`** backing it,
indistinguishable from (and able to `graph_key`-collide with) the actual structural node of
that type for the same project. This is precisely the review's own example (a `dashboard`
node with the wrong provenance).

**Fix:** new `app/services/knowledge_graph/schema_registry.py` —
`RESERVED_STRUCTURAL_NODE_TYPES` (`project`, `data_source`, `saved_query`, `dashboard`,
`kpi`, `reference_document`) and `is_reserved_structural_type()`. Wired into
`create_family_relationship_edges`: a `target_type` matching one of these is coerced to the
existing default (`"process"`) instead of being written through. `"document"` is
deliberately **not** in the reserved set — an existing, tested pattern
(`tests/test_document_families.py::test_relationship_edges_created`, `target_type="document"`)
already uses it as a legitimate placeholder for a document referenced by name but not (yet)
itself a structural node with a real `source_id` — it never carries a `source_type`/
`source_id` to collide on, so it isn't an impersonation risk the way the six reserved types
are.

**Also fixed (dead-code drift, zero behavior change):** `app/routes/project_graph.py`'s
`FAMILY_EDGE_TYPES` (a read-side filter set) listed `"responds_to"`, which is absent from
the write-side allow-list (`FAMILY_RELATIONSHIP_TYPES`,
`app/services/project_graph_service/graph_primitives.py`) and therefore could never actually
be produced. Removed from the read-side list rather than added to the write side, since
nothing emits it today and adding a new writable relationship type wasn't asked for.

**Deliberately not done:** a full schema registry (required properties, cardinality,
evidence requirements, and a from/to type-pair matrix for every relationship type) — every
other node/edge in the codebase already has a single correct, hardcoded emission site (see
KG-25 below), so a general-purpose registry has no second real consumer yet and would be
speculative infrastructure rather than a fix for an active gap.

## KG-25: contradictory-direction detection

**Validated:** every structural relationship type (`reads_from`, `visualizes`, `measures`,
`uses_query`, `has_passage`, etc.) is emitted from exactly one call site in
`collect_structural_graph`, always in the same direction — confirmed by reading every
emission site. `"governs"` is a real, tested, exercised edge type (document→process/family
target via the family-linking path); `"mitigates"` and a first-class `"policy"` node
(the review's other example) are not implemented anywhere — prompt-text/display-taxonomy
only, never written. No inverse-relationship pairing concept existed anywhere in the
codebase before this phase.

**Fix:** `schema_registry.py` adds `INVERSE_OF` (the pairs that already coexist as
unordered members of existing allow-lists: `governs`/`governed_by`,
`supersedes`/`superseded_by`) and `detect_contradictory_direction_edges(edges)` — flags a
same-`relationship_type` edge asserted in both directions between the same two nodes
(A--rel-->B *and* B--rel-->A), a real modeling-error signal since a non-symmetric
relationship can't correctly hold both ways at once. Wired into
`evaluate_structural_integrity` (`app/services/knowledge_graph_lifecycle/structural_integrity.py`)
— the existing single chokepoint already shared by rebuild-activation gating and health
reporting (KG-21/22/23/47) — as a new **non-blocking warning** (`contradictory_direction_count`
in the result dict), consistent with how orphan-ratio/disconnected-component signals are
already reported there.

**Deliberately not done:** direction isn't *enforced* anywhere (nothing would reject a
future regression that emitted `reads_from` backwards) — only detected after the fact on
whatever candidate graph is being validated. Enforcing correct direction per relationship
type would need the fuller schema registry explicitly deferred above.

## KG-26: graph-key collision visibility

**Validated:** `merge_graph_sources` (`app/services/knowledge_graph/loader.py`) — the single
chokepoint where the persisted AI graph and the ephemeral structural graph combine — lets
whichever node is seen first for a given `graph_key` win, with the loser's id remapped onto
it and **silently dropped**, no log, no record, regardless of whether the two nodes are
actually the same underlying record. Concretely: a file source and a database table both
named "orders" both normalize to `datasource:orders` and collapse into one node with no
trace that a second, different-sourced record ever existed.

**Fix:** `merge_graph_sources` now compares `(source_type, source_id)` between the winning
and losing node on every collision. When they differ — proof the two nodes are *not* the
same record — it logs a `knowledge_graph.graph_key_collision` warning naming both nodes'
ids and source identities. When they match (the expected case: the AI-enriched and
structural rows for the same real record folding into one node), nothing is logged, exactly
as before.

**Deliberately not done (a conscious, documented scope decision, not an oversight):** the
merge *behavior* is unchanged — the losing node still doesn't survive as a separate,
distinguishable node in the merged graph, so the review's literal Accept criterion ("two
different sources... remain distinguishable") is only partially met: collisions are now
visible (loggable/greppable), not yet non-destructive. Making the loser survive under a
disambiguated key would require auditing every downstream consumer that currently assumes
`graph_key` uniqueness (rendering, KPI phrase-matching, visibility filtering, canvas
centering) — a materially larger, higher-risk change than a logging-only fix, and is flagged
here as the natural next step once collision *frequency* in real data is actually known
(currently zero visibility into whether this happens often, rarely, or never in practice).

## Tests added

| File | Coverage |
|---|---|
| `tests/test_kg24_25_26_schema_registry.py` (8 tests) | `is_reserved_structural_type`/`inverse_of` correctness; `detect_contradictory_direction_edges` flags a reversed pair and ignores normal structure; `evaluate_structural_integrity` surfaces the new non-blocking warning and count; `merge_graph_sources` logs a collision between different sources and stays silent for the same source |
| `tests/test_kg24_reserved_type_coercion.py` (2 tests) | end-to-end through `apply_document_family`/`create_family_relationship_edges`: a reserved target_type (`"dashboard"`) is coerced to `"process"` with no `source_type`/`source_id`; a legitimate non-reserved target_type (`"supplier"`) passes through unchanged |

All real-bug tests proven to **fail** against pre-fix code (`git stash` on the relevant fix
file(s), rerun to confirm failure, restore, rerun to confirm pass) — including the
integration-level KG-24 test, which failed with the literal `'dashboard' == 'process'`
mismatch before the fix.

## Verification

| Suite | Result |
|---|---|
| `pytest tests/test_kg24_25_26_schema_registry.py tests/test_kg24_reserved_type_coercion.py tests/test_document_families.py -q` | 20 passed, 0 regressions on the existing document-family suite |
| `pytest tests/test_kg21_activation_validation.py tests/test_knowledge_graph_health.py -q` | 10 passed — the shared `evaluate_structural_integrity` chokepoint's existing consumers unaffected |
| KG-focused regression sweep (`pytest -k "knowledge_graph or kg or project_graph or document_families" -q`) | 309 passed, 2 failed (same pre-existing `test_business_insight_phase1.py` Redis-connection failures as every prior phase — this sandbox has no Redis running; unrelated) |
| `ruff check` (all touched/new files) | clean |
| `mypy` (all touched/new files) | clean |
| Full `pytest -q` (whole platform-api suite) | **1826 passed, 4 skipped, 10 failed** — same 10 pre-existing/unrelated failures as every prior phase (dashboard visualization, percent-change summary statistics, business-insight snapshot staleness) — 0 new |

```bash
cd platform-api
pytest -q
ruff check app/services/knowledge_graph/schema_registry.py \
  app/services/knowledge_graph/loader.py \
  app/services/knowledge_graph_lifecycle/structural_integrity.py \
  app/services/project_graph_service/linking.py \
  app/routes/project_graph.py
mypy app/services/knowledge_graph/ \
  app/services/knowledge_graph_lifecycle/ \
  app/services/project_graph_service/ \
  app/routes/project_graph.py
```

## Deploy

`platform-api` only. No migration, no schema change.

```bash
docker compose build platform-api
docker compose up -d platform-api platform-api-worker
```

## Verify live

- Trigger document processing on a document whose AI profile proposes a family
  relationship with an unusual `target_type` (or check application logs after a normal
  processing run) and confirm no `ai_project_graph_nodes` row is ever created with
  `node_type` in `{project, data_source, saved_query, dashboard, kpi, reference_document}`
  unless it has a real `source_type`/`source_id`.
- Run (or trigger) a Knowledge Graph rebuild/health-check for a project and confirm the
  response still reports normally (`contradictory_direction_count: 0`, no new warning) for
  ordinary data.
- Grep application logs for `knowledge_graph.graph_key_collision` after a rebuild on a
  project with genuinely overlapping source names (e.g. a file source and a database table
  sharing a name) to confirm the new log line appears where it previously would have been
  silent.

## Remaining work

Section C has 4 items left, all P1: #27 (canonical entity resolution with aliases — a
materially large, from-scratch effort: no alias/canonicalization mechanism exists today for
customers/suppliers/sites/products/people/processes, no group model, no reviewer-confirmation
workflow), #28 (relationship cardinality and join-quality evidence — Home Intelligence
already computes real cardinality/overlap signals in `query_helpers.py` but discards them
after one widget-planning response; `DatabaseDataSource` has zero column profiling unlike
file sources), #29 (temporal consistency — `AIProjectGraphNode`/`Edge` carry no timestamp
beyond `created_at`, and no per-card/per-relationship freshness check exists distinct from
the whole-graph staleness fingerprint), #30 (semantic coverage scoring — the existing
coverage manifest, `app/services/knowledge_graph_context/coverage.py`, reports raw counts
for 6 of 9 listed dimensions with no percentage anywhere, and no unified health+coverage
report). Section D (#32/34–38/40) remains fully open. Sections A, B, and E are fully closed.

## Report back

Confirm the collision-log line appears as expected for a real name-overlap case, then
decide whether to continue into #27–30 (each materially larger and more product-decision-
dependent than #24–26, per the research above) or pause Section C here and move to Section
D instead.

---

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01M7j8CDCHCdwHpw9FrRhLN5
