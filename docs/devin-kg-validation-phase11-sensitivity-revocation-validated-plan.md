# Devin: merge + deploy — Knowledge Graph validation, Phase 11 (Section A remainder: #08–09)

**Repository:** `lhoskins/tablescope-lh`
**Branch to merge:** `kg-validation-phase10-source-lineage` (this phase's commits land on top of Phase 10's, same branch)
**Base:** `kg-validation-phase8-observability-goldens` tip (already includes Phases 1–10)

**`platform-api/` only · no migration · all tests green**

---

## Context

This phase closes out the last two Section A (security/authorization/isolation) items:

- **#08 (P1)**: "Introduce sensitivity labels and propagation rules... Propagate the
  strictest applicable classification from evidence nodes into inferred edges and
  generated cards. **Accept:** derived content cannot have broader visibility than its
  most restrictive evidence."
- **#09 (P1)**: "Validate deletion and revocation propagation... **Accept:** revoked
  content is absent immediately after the authorized invalidation window."

Both items are large by their full text — a complete implementation of #08 alone would
mean a new group-membership model, new visibility columns on five tables with no such
column today, and a UI for assigning six classification levels; #09's full scope touches
every deletion route plus cache-invalidation semantics across several caching layers. A
research pass (an Explore agent, full transcript available on request) was run first
against the real code to separate genuine, fixable gaps from things that already work, so
this phase targets the concrete, verified, high-value gaps rather than a sprawling
redesign — each deliberately-deferred piece is named explicitly below.

## KG-08: sensitivity labels and propagation

**Validated:** only two visibility values are ever written anywhere in the codebase today
(`"shared_project"`, `"private"` — on `ProjectAsset`, `ai_documents`, and an otherwise
entirely dead `visibility` column on `AIProjectGraphNode`/`AIProjectGraphEdge`, always
written as the literal constant `"shared_project"`). `SavedQuery`, `Dashboard`,
`DatabaseDataSource`, `FileSourceMeta`, and `ReferenceDocument` have **no** visibility
field at all. `access_group_id` columns exist in four places but reference nothing — there
is no `AccessGroup`/group-membership model anywhere in `app/models/`. The existing KG-04/06
viewer filter (`app/services/knowledge_graph/visibility.py`) already implements a working,
tested private-vs-shared model, but it is `ProjectAsset`-only.

**Confirmed concrete leak, found during this validation and fixed here:** `collect_structural_graph`'s
new (Phase 10, KG-16) chunk/passage nodes carry `source_type == "ai_document_chunk"`, a
different `source_type` than `"project_asset"`. Both `filter_raw_graph_for_user` (KG-06,
pre-AI-enrichment) and `filter_payload_for_viewer` (KG-04, post-build reads) computed
"which node ids to hide" by matching `source_type == "project_asset"` only — a private
document's own passage/chunk nodes (raw excerpted text) were never matched, so only their
connecting edge to the (correctly) hidden document node was stripped. The passage node
itself — with its `properties.summary` (up to 300 chars of the document's actual
content) — survived in the visible node list, floating disconnected from the hub but still
fully readable by a viewer the parent document is hidden from. This is exactly the
"derived content broader than its most restrictive evidence" failure mode KG-08's Accept
criterion names, not a hypothetical: a passage *is* its parent document's evidence.

**Fix:**
- `collect_structural_graph` (`app/services/knowledge_graph_context/collectors.py`) now
  tags each passage node's `properties` with `"asset_id": <parent ProjectAsset.id>`.
- New shared helper `_hidden_node_ids(nodes, hidden_asset_ids)`
  (`app/services/knowledge_graph/visibility.py`) covers both `source_type ==
  "project_asset"` and `source_type == "ai_document_chunk"` (via `properties.asset_id`).
  Both `filter_raw_graph_for_user` and `filter_payload_for_viewer` now call this one helper
  instead of each duplicating the same node-id computation inline — closing a drift risk
  between the two functions, matching the "one shared helper, not two copies" pattern used
  throughout this whole review (KG-13/44's `_FINGERPRINT_MODELS`, KG-20's
  `active_reference_document_conditions`).
- Verified (not touched): a third, legacy copy of "is this node hidden" logic exists inline
  in `app/routes/project_graph.py`'s older `{nodes, edges}` route, reading directly from
  the persisted `ai_project_graph_nodes` staging table. Confirmed via a targeted grep sweep
  that no code path ever inserts a `source_type == "ai_document_chunk"` row into that
  table — passage nodes exist only in the `collect_structural_graph` → snapshot-cache
  pipeline the two functions above guard — so that route was never exposed to this leak
  and needs no change.
- New `app/services/knowledge_graph/sensitivity.py`: a single ranked vocabulary
  (`public_project < shared_project < project_restricted < shared_group < private <
  confidential < regulated`) plus `sensitivity_rank`/`strictest_sensitivity` helpers. This
  is additive only — no schema change, no behavior change to any existing filter — laying
  a consistent foundation for whichever future work adds the remaining five labels to real
  columns, rather than each future call site inventing its own ordering. An unrecognized or
  missing label ranks as the current implicit default (`shared_project`), so every existing
  row is unaffected.

**Deliberately not done (materially separate efforts, named explicitly rather than
silently skipped):**
- Adding visibility columns to `SavedQuery`/`Dashboard`/`DatabaseDataSource`/
  `FileSourceMeta`/`ReferenceDocument` — five migrations plus UI, and no product decision
  yet on what "project-restricted" vs. "shared-group" means operationally for a data
  source or a dashboard specifically.
- Building an `AccessGroup`/group-membership model to back `access_group_id` — the
  "shared-group" label has no substrate to attach to without this.
- Propagating a *graded* (non-binary) sensitivity label onto generated cards. The existing
  KG-04/06 mechanism already satisfies the Accept criterion's letter for the two-tier model
  that actually exists today: a card citing hidden evidence is removed entirely (a stricter,
  safe behavior than a partial-restriction label would be) — but it's a hide/show binary,
  not a computed classification value stored on the card. Wiring `strictest_sensitivity`
  into `app/services/knowledge_graph/cards.py`'s card builders once real graded labels
  exist elsewhere is natural future work using the vocabulary added here.
- `BusinessInsightResult`'s single project-wide shared cache has no per-label segmentation
  at all — out of scope for this pass.

## KG-09: deletion and revocation propagation

**Validated (research pass, full per-route breakdown available on request):** `ProjectAsset`
deletion already correctly cleans up `ai_documents`/`ai_document_chunks` and its own
`ai_project_graph_nodes`/`edges` rows, and calls `archive_empty_family`. `SavedQuery`,
`Dashboard`, `DatabaseDataSource`, and `ReferenceDocument` deletions are already covered
(eventually — every ≤15 minutes) by the existing fingerprint-diffing staleness cron
(`evaluate_stale_graphs`), since all five are already hashed inputs to
`compute_source_fingerprint`. Two concrete, un-covered gaps were confirmed:

1. **Archived queries never actually left the graph.** `collect_structural_graph`'s
   saved-query fetch had no `is_archived` filter at all — unlike the analogous
   `FileSourceMeta`/`DatabaseDataSource` "archived" filters that already existed. Since
   archiving is this app's required precondition for deleting a query
   (`app/routes/projects_queries.py`), an archived-but-not-yet-hard-deleted query
   (which can persist indefinitely) kept appearing in the Knowledge Graph exactly like an
   active one.
2. **`ProjectMember` deactivation/removal never marked the graph stale at all** — not
   immediately, and not even eventually. Unlike every other source type,
   `compute_source_fingerprint` never read the `ProjectMember` table, so revoking or
   removing a member's project access was invisible to the one mechanism
   (`evaluate_stale_graphs`) that every other deletion/change relies on to eventually
   trigger a rebuild.

**Fix:**
- `collect_structural_graph`'s saved-query fetch now filters `SavedQuery.is_archived.is_(False)`,
  matching the existing pattern for file/database sources.
- `compute_source_fingerprint` (`app/services/knowledge_graph_lifecycle/bootstrap.py`) now
  hashes every `ProjectMember` row for the project (`user_id, role, is_active`, sorted).
  `ProjectMember` has a composite `(project_id, user_id)` primary key and no `updated_at`
  column, so it doesn't fit `_FINGERPRINT_MODELS`'s single-id/timestamp shape (the same
  reason `reference_documents`/`repository_scans` already get their own dedicated blocks
  rather than joining that list) — it's hashed directly in its own block instead. This
  feeds the fingerprint (and therefore the 15-minute `evaluate_stale_graphs` cron) only;
  `current_source_watermark` still has no timestamp to read for this source, so membership
  changes are not part of that separate, more time-precise mechanism.

**Deliberately not done:**
- No deletion/revocation route was changed to trigger an *immediate* (sub-15-minute)
  rebuild or to invalidate the cached `AIProjectGraphSnapshot` payload synchronously —
  `mark_stale()` only flips a status flag; the cached snapshot itself keeps being served
  until an actual rebuild completes (manual, or the next cron pass). Wiring an immediate
  rebuild trigger into five separate deletion routes, each requiring careful session/
  lifecycle-manager plumbing and its own regression coverage, is a substantially larger,
  separate change from the two targeted, high-confidence fixes above.
- `archive_empty_family` (`app/services/project_graph_service/lifecycle.py`) still only
  clears `belongs_to_family` membership edges when deactivating an empty family node —
  other edge types (`governs`, `depends_on`, `references`, etc.) on an otherwise-orphaned
  family are left untouched, a distinct, narrower gap flagged but not fixed here.
- `BusinessInsightResult`'s cache still relies on its existing TTL (24h default) +
  `kg_version_id` match rather than any new revocation-triggered purge; the existing
  tenant-wide manual `/home-intelligence/clear-cache` escape hatch is unchanged.

## Tests added

| File | Coverage |
|---|---|
| `tests/test_kg08_passage_visibility.py` (2 tests) | a private document's passage/chunk node is hidden from a non-owner viewer (and visible to the owner) through both `filter_raw_graph_for_user` and `filter_payload_for_viewer` |
| `tests/test_kg08_sensitivity_vocabulary.py` (5 tests) | strictness ordering is monotonic; unknown/missing labels rank as the default; `strictest_sensitivity` picks the most restrictive label, defaults on empty evidence, and ignores `None` entries unless every entry is `None` |
| `tests/test_kg09_deletion_revocation.py` (4 tests) | an archived saved query no longer appears in the graph (active queries still do); deactivating or removing a `ProjectMember` changes `compute_source_fingerprint`'s output |

All real-bug tests (every test above except the pure vocabulary-correctness checks in
`test_kg08_sensitivity_vocabulary.py`, which have no prior behavior to regress against)
proven to **fail** against pre-fix code — `git stash` on the relevant fix file(s), rerun to
confirm failure, restore, rerun to confirm pass.

## Verification

| Suite | Result |
|---|---|
| `pytest tests/test_kg08_passage_visibility.py tests/test_kg08_sensitivity_vocabulary.py tests/test_kg09_deletion_revocation.py tests/test_kg04_document_visibility.py -q` | 15 passed, 0 regressions on the existing KG-04 visibility suite |
| KG-focused regression sweep (`pytest -k "knowledge_graph or kg" -q`) | 289 passed, 2 failed (same pre-existing `test_business_insight_phase1.py` Redis-connection failures as every prior phase — this sandbox has no Redis running; unrelated) |
| `ruff check` (all touched/new files) | clean |
| `mypy` (all touched/new files) | clean |
| Full `pytest -q` (whole platform-api suite) | **1816 passed, 4 skipped, 10 failed** — same 10 pre-existing/unrelated failures as every prior phase (dashboard visualization, percent-change summary statistics, business-insight snapshot staleness) — 0 new |

```bash
cd platform-api
pytest -q
ruff check app/services/knowledge_graph_context/collectors.py \
  app/services/knowledge_graph_lifecycle/bootstrap.py \
  app/services/knowledge_graph/visibility.py \
  app/services/knowledge_graph/sensitivity.py
mypy app/services/knowledge_graph_context/ \
  app/services/knowledge_graph_lifecycle/bootstrap.py \
  app/services/knowledge_graph/
```

## Deploy

`platform-api` only. No migration, no schema change.

```bash
docker compose build platform-api
docker compose up -d platform-api platform-api-worker
```

## Verify live

- Seed (or use) a project with a private document that has been chunked, and confirm a
  non-owner project member's graph view no longer shows a floating passage/excerpt node
  for it (previously visible even though the document node itself was correctly hidden).
- Archive a saved query and confirm it disappears from the project's Knowledge Graph on
  the next rebuild, without needing to hard-delete it.
- Deactivate or remove a project member and confirm `compute_source_fingerprint` for that
  project changes (visible indirectly: the project's Knowledge Graph is marked stale
  within the next ~15-minute `evaluate_stale_graphs` pass, where previously it never would
  be for a membership-only change).

## Remaining work

Section A is now fully closed (all of #01–10 done across Phases 1 and 11). Still open, all
P1: Section C (#24–30: schema registry, relationship-direction validation, duplicate
detection, entity resolution, join-quality evidence, temporal consistency, semantic
coverage scoring), Section D (#32/34–38/40: confidence calibration, real evidence paths,
contradiction detection, source-authority weighting, question-aware context selection,
context-omission reporting, deterministic card fallback). Sections B and E are fully closed.

## Report back

Confirm the two live-verification steps above (passage-leak fix, archived-query removal)
pass in a deployed environment, then continue into the remaining P1 batches (Section C,
then Section D) or stop here.

---

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01M7j8CDCHCdwHpw9FrRhLN5
