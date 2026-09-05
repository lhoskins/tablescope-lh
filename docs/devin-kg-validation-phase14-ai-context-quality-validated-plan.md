# Devin: merge + deploy — Knowledge Graph validation, Phase 14 (Section D: #32/34–38/40, section complete — 50-item review complete)

**Repository:** `lhoskins/tablescope-lh`
**Branch to merge:** `kg-validation-phase10-source-lineage` (this phase's commits land on top of Phases 10–13's, same branch)
**Base:** `kg-validation-phase8-observability-goldens` tip (already includes Phases 1–13)

**`platform-api/` only · 1 migration (`0092`, additive) · all tests green**

---

## Context

This phase closes out Section D — AI-context and evidence quality — the last remaining
section of the 50-item review:

- **#32 (P0)**: "Calibrate confidence instead of trusting raw model values."
- **#34 (P1)**: "Build real evidence paths, not only evidence-node lists."
- **#35 (P1)**: "Detect contradictory evidence."
- **#36 (P1)**: "Weight source authority explicitly."
- **#37 (P1)**: "Make AI-context selection question-aware."
- **#38 (P1)**: "Report context omissions and truncation downstream."
- **#40 (P1)**: "Add a safe deterministic fallback for KG insight cards."

Three research passes (Explore agents) ran first against the real code for all seven items,
each confirming a real, verified gap. As with every prior phase, each item's *full* text
describes a materially larger system than a single phase should build from scratch (a
reviewer-confirmation calibration workflow with a labeled dataset; a full path-finding
evidence-graph traversal; an authoritative source-conflict-resolution system). This phase
implements the concrete, verified, safely-scoped slice of each item and documents the rest
as deliberately deferred, matching every prior phase's discipline.

## KG-40: safe deterministic fallback for KG insight cards

**Validated:** `build_graph_payload` always computes deterministic, evidence-grounded
"structural" insight cards (`_build_card_for_node`/`_center_overview_card`/
`_kpi_measurement_gap_card`) into `payload["insightCards"]`/`["tracePaths"]` **before** any
AI enrichment ever runs (`snapshot.py`'s `_one()`: `payload = build_graph_payload(...)` then
`await enrich_payload_with_ai(payload, ...)` mutates the same dict). `_clear_cards()` in
`knowledge_graph_ai.py` unconditionally wiped these already-computed, never-fabricated cards
to `[]` on *any* AI failure/rejection/disable — discarding real evidence relationships for
no benefit (the AI-server-failure case has nothing to do with whether the structural cards
are trustworthy).

**Fix:** `_clear_cards()` no longer touches `insightCards`/`tracePaths` — it only sets
`aiGenerated = False` and a new `aiEnrichmentStatus = "unavailable"` field (mirroring the
existing KG-39 `grounding_status` convention). The success path sets
`aiEnrichmentStatus = "ok"`. The "no cached bundle" branch in
`build_node_centric_graph_from_snapshot` (`renderer.py`) similarly stopped wiping the cards
`build_graph_payload` had just computed. `_card_bundle`/`_overlay_card_bundle` (`cards.py`)
carry the new field through the cache read/write path so a served bundle's status survives.

**Deliberately not done:** nothing changes about *how* structural cards are built or ranked
— this only stops an unconditional wipe of content that was already correct.

## KG-34: real evidence paths with direction and relationship type

**Validated:** `traceToEvidence`/`tracePaths` only ever carried flat, unordered
`nodeIds`/`edgeIds` lists — no per-hop direction or relationship-type information anywhere,
so a UI would have to separately cross-reference the top-level `edges` array and guess how
hops chain together. The AI-enriched path (`knowledge_graph_ai.py`'s `_map_card`) was worse:
its `evidence_ids` was built from a plain Python `set()`, with no guaranteed order at all.

**Fix:** a new `_hops(neighbors)` helper in `cards.py` builds an ordered
`[{fromNodeId, toNodeId, relationshipType}, ...]` list directly from the real `(node, edge)`
pairs already gathered for each card (never invented) — added to all three structural card
builders' `traceToEvidence` dicts and both top-level `trace_paths.append(...)` call sites
(`renderer.py`, `knowledge_graph_ai.py`). `_map_card`'s `evidence_ids` became an
order-preserving `list(dict.fromkeys(...))`, and it gained a parallel `hops` list built from
the real grounding edges (`source`/`target`/`type` keys, distinct from `cards.py`'s raw
`from_node_id`/`to_node_id`/`relationship_type` keys).

**Deliberately not done:** `loader.py`'s `_neighborhood` BFS was not extended into a full
parent-pointer path reconstructor — both existing card builders are inherently
one-hop/star-shaped, and a one-hop "path" is already fully described by direct evidence
edges. Multi-hop path reconstruction across an arbitrary evidence chain is a materially
larger, separate effort with no current card shape that would consume it.

## KG-35: detect contradictory evidence

**Validated:** `merge_graph_sources` (KG-26) already logs when two nodes collide on the same
graph key but come from different sources — but that log line is the *only* trace of it
anywhere, and fires identically whether the two sources agree or actually assert different
facts about the same real-world entity.

**Fix:** `loader.py` gains `_property_conflicts(kept_props, dropped_props, ...)`: when a
KG-26 collision is between two different sources, their shared scalar (non-list/dict,
non-null) property keys are now also compared. A free-text/bookkeeping ignore-list
(`graph_key`, `confidence`, `summary`, `description`) is excluded since those are expected to
differ incidentally. Any surviving disagreement is appended to the winning node's
`properties.evidence_conflicts` (a list of `{key, keptValue, conflictingValue,
conflictingSourceType, conflictingSourceId}`), which flows through `enrich_node` into the
node's `properties` automatically — visible to any consumer that reads the node, not buried
in a log a caller can't see. A same-source collision (the expected AI+structural fold-in
case) is never treated as a conflict.

**Deliberately not done:** no attempt to decide *which* source is correct, no UI/card
surfacing of the conflict (out of scope — the item asks to *detect*, not resolve or
render), and no general-purpose semantic contradiction detection beyond scalar property
disagreement (e.g. two documents making opposing prose claims) — that requires NLP/LLM
judgment this phase does not add.

## KG-36: weight source authority explicitly

**Validated:** the review's own stated source-authority order ranks "approved company
policy" and "project documentation" above generic "industry references" — but
`evidence_severity.py`'s `gate_severity()` (which caps a risk-grade severity to `"watch"`
when a card's evidence rests only on reference-document nodes) was tier-blind: it treated a
company-tier reference document identically to a generic industry-tier one for this gating
purpose, contradicting the review's own stated precedence.

**Fix:** `gate_severity()` gains an optional `has_authoritative_non_industry_evidence: bool
= False` parameter; when `True`, it also exempts a card from the guidance-only cap. The one
other caller (`home_intelligence/orchestrator.py`) omits the new kwarg and is unaffected,
verified by grep. `knowledge_graph_ai.py`'s `_map_card` computes it by checking each
reference-document evidence node's `properties.tier` against `TIER_COMPANY`/`TIER_PROJECT`
(imported from `app.models.reference_library`) — a node with *no* tier recorded at all is
correctly **not** treated as authoritative (an initial `!= TIER_INDUSTRY` draft wrongly
treated "no tier" as authoritative; caught by the KG-focused regression sweep against a
pre-existing test and fixed before commit).

**Deliberately not done:** no general "explain when a lower-authority source was overridden"
audit trail, and `home_intelligence/orchestrator.py` was not wired to pass the new kwarg
(its evidence nodes don't currently carry a tier at the point `gate_severity` is called) —
both are separate, larger efforts.

## KG-37: question-aware AI-context selection

**Validated:** `_ranked()` (used by every bucket in `collect_knowledge_graph_ai_context`)
only ever sorted by a node's own static confidence — the user's free-text prompt had zero
influence on which risks/gaps/KPIs made it into a capped, deduped bucket, so the item most
relevant to what was actually asked could be pushed out by an unrelated but
higher-confidence one.

**Fix:** a new `_question_keywords(question)` extracts a small, explainable lowercased
keyword set (stopwords and ≤2-letter tokens dropped — no embeddings/ML). `_ranked()` gains
an optional `keywords` parameter and sorts by `(question_relevance, confidence)` instead of
`confidence` alone; an empty keyword set (no question given) reduces the sort key back to
`(0.0, confidence)` for every item — identical to the previous ordering. `question: str |
None = None` was threaded through `collect_knowledge_graph_ai_context` and `_kg_context`
(`ai_proxy_shared.py`), then wired at all 5 real call sites that have a free-text prompt:
`ai_proxy_query.py`, `ai_proxy_dashboard_generate.py`, `ai_proxy_dashboard_suggest.py`,
`ai_proxy_query_actions.py`, and both `ai_proxy_ask_and_run.py` call sites (`req.prompt` or
the local `question` variable, as available). `ai_proxy_dashboard.py`'s fixed-shape request
has no free-text prompt and was left unchanged.

**Deliberately not done:** no semantic/embedding-based relevance (lexical keyword overlap
only) and no per-surface tuning of the relevance/confidence weighting — both are reasonable
follow-ons once real usage data exists to tune against.

## KG-38: report context omissions and truncation downstream

**Validated:** every bucket in `collect_knowledge_graph_ai_context` was ranked and capped
(`max_items`) with no record of how much was left out — a caller could never tell "the
graph legitimately had only 2 risks" apart from "there were 20 risks and only 5 fit the
cap."

**Fix:** a new `context_coverage: {bucket: {available, selected}}` dict is attached to the
returned context, computed by comparing each bucket's raw pre-ranking candidate count
against what actually survived ranking/capping/dedup. Present (as `{}`) on every return path,
including the `"unavailable"`/legitimately-empty-graph early returns, so the field's shape is
never inconsistent across callers.

**Deliberately not done:** no propagation of per-bucket coverage into the `kg_grounding`
audit record or into the AI server's own prompt (a caller can already inspect
`context_coverage` directly) — wiring it further downstream is a smaller, separable
follow-on once a concrete consumer needs it.

## KG-32: confidence-calibration groundwork

**Validated:** `document_families_curation.py`'s accept/change/remove routes are the one
existing human-correction workflow directly on real KG edges. All three only ever reported
the (AI confidence, human decision) pair through `log_family_event` — a log line, not a
queryable table — and the original AI-suggested confidence was overwritten/discarded on
`asset.ai_metadata` the instant a decision was applied, with nothing durable left to
calibrate against later.

**Fix:** a new `ai_confidence_decisions` table (model `AiConfidenceDecision`, migration
`0092`) and `record_ai_confidence_decision()` write helper capture
`(tenant_id, project_id, asset_id, source_pipeline, ai_confidence_at_decision,
human_decision, decided_by, decided_at)` for every accept/change/remove — reading the AI's
*original* suggested confidence from `ai_metadata` before the decision overwrites it (a
`change` correctly records the prior AI confidence, not the human's override value; a
`remove` with no prior AI suggestion correctly records `None`, not a fabricated value).
`source_pipeline` is a plain string column (`"document_family"` today) so future AI
suggestion pipelines can share the same table without a schema change.

**Deliberately not done — this is groundwork/data-capture infrastructure only, not an
actual calibration report.** No precision/recall computation, no calibration curve, no
confidence-adjustment logic anywhere in the product: there is no historical labeled dataset
of confirmed-correct/incorrect AI suggestions to calibrate against yet (this was already the
explicit reasoning recorded for KG-32 in an earlier phase's commit, and remains true — this
phase only makes the (confidence, outcome) pairs durable and queryable so a *future*
calibration pass has real data to work from).

## Pre-existing test maintenance

Three pre-existing tests encoded the *old* (deficient) behavior as their expected
assertion and were updated to reflect the new, intended behavior — each confirmed passing
before and after with the correct value:

- `tests/test_knowledge_graph_ai.py` (3 tests) and `tests/test_knowledge_graph.py` (1 test):
  renamed/rewritten from "clears cards" to "falls back to structural cards" (KG-40's whole
  point is to change this exact behavior).
- `tests/test_kg42_incremental_card_refresh.py`: a structural fallback card
  (`doc:beta`) legitimately traces evidence through a changed node (`risk:alpha`, via their
  real `related` edge) once KG-40 stops wiping it — so `affected_center_keys` now correctly
  detects `doc:beta` also needs re-enrichment, not just the node that literally changed.
  Updated the assertion and its comment to state the corrected, more accurate scoping.

## Tests added

| File | Coverage |
|---|---|
| `tests/test_kg40_deterministic_card_fallback.py` (3 tests) | no cached bundle falls back to structural cards; a cached AI bundle still overrides the fallback; a cached fallback bundle is served as-is on a later read |
| `tests/test_kg34_evidence_path_hops.py` (4 tests) | structural card carries an ordered, direction-aware hop per evidence edge; the top-level trace path carries the same hops as its card; an AI-mapped card's evidence ids are ordered, not a bare set; an AI-mapped card carries direction-aware hops from real grounding edges |
| `tests/test_kg35_contradictory_evidence.py` (4 tests) | colliding nodes with different property values record a conflict; agreeing properties record no conflict; a same-source collision is never treated as a conflict; ignored (free-text/bookkeeping) keys never produce a conflict |
| `tests/test_kg36_source_authority_severity.py` (3 tests) | industry-tier-only evidence is still capped to watch; company-tier-only evidence is not capped; project-tier-only evidence is not capped |
| `tests/test_kg37_question_aware_context.py` (4 tests) | no question ranks by confidence only; a relevant question promotes the lower-confidence matching item; question-keyword extraction drops stopwords/short words; empty for no question |
| `tests/test_kg38_context_coverage.py` (3 tests) | coverage reports truncation when more items exist than the cap; no truncation shown when everything fits; coverage is empty for an empty graph |
| `tests/test_kg32_confidence_decision_audit.py` (3 tests) | accept records the AI-suggested confidence; change records the *prior* AI confidence, not the human's override; remove with no prior AI suggestion records null confidence |

All 24 new tests were proven fail-before/pass-after via `git stash` (production change
stashed → test fails for the validated reason → stash restored → test passes) before being
finalized.

## Verification

| Suite | Result |
|---|---|
| `pytest tests/test_kg40_deterministic_card_fallback.py tests/test_kg34_evidence_path_hops.py tests/test_kg35_contradictory_evidence.py tests/test_kg36_source_authority_severity.py tests/test_kg37_question_aware_context.py tests/test_kg38_context_coverage.py tests/test_kg32_confidence_decision_audit.py tests/test_knowledge_graph.py tests/test_knowledge_graph_ai.py tests/test_knowledge_graph_ai_context.py tests/test_kg42_incremental_card_refresh.py tests/test_document_families.py -q` | all passed, 0 regressions |
| `ai_proxy`/dashboard-generation regression (`test_ai_ask_and_run.py`, `test_ai_proxy_permissions.py`, `test_ai_proxy_query_relationship_hints.py`, `test_ai_proxy_shared.py`, `test_dashboard_suggest_preview_chart_type.py`, `test_knowledge_graph_ai_context.py`, `test_kg37_question_aware_context.py`) | 59 passed, 0 regressions |
| KG-focused regression sweep (`pytest -k "knowledge_graph or kg or project_graph or document_families or document_processing" -q`) | 355 passed, 2 failed (same pre-existing `test_business_insight_phase1.py` Redis-connection failures as every prior phase — this sandbox has no Redis running; unrelated) |
| `ruff check` (all touched/new files) | clean |
| `mypy` (all touched/new files) | clean |
| Full `pytest -q` (whole platform-api suite) | 1868 passed, 11 failed, 4 skipped in 1120s. Same 11 pre-existing, unrelated failures as Phase 13's baseline (confirmed identical by name): `test_business_insight_phase1.py`/`test_executive_insight_dependencies.py` (Redis-dependent snapshot-staleness tests), `test_percent_change_summary.py`, `test_visualization_engine.py`, `test_ai_dashboard_pipeline.py::test_correct_widget_converts_oversized_pie`, `test_ask_pipeline.py::test_matrix_resolves_to_heatmap_not_a_narrowed_bar` (chart/dashboard-presentation logic, no relation to the knowledge graph). 24 more tests pass than Phase 13's baseline (1868 vs 1844), matching this phase's 24 new tests exactly — zero regressions. Skips are the VPN/SMB live E2E tests (require an external URL not set in this sandbox). |

```bash
cd platform-api
pytest -q
ruff check app/models/__init__.py app/models/ai_confidence_decision.py \
  app/routes/ai_proxy_ask_and_run.py app/routes/ai_proxy_dashboard_generate.py \
  app/routes/ai_proxy_dashboard_suggest.py app/routes/ai_proxy_query.py \
  app/routes/ai_proxy_query_actions.py app/routes/ai_proxy_shared.py \
  app/routes/document_families_curation.py app/services/ai_confidence_audit.py \
  app/services/evidence_severity.py app/services/knowledge_graph/cards.py \
  app/services/knowledge_graph/loader.py app/services/knowledge_graph/renderer.py \
  app/services/knowledge_graph_ai.py app/services/knowledge_graph_ai_context.py
mypy app/models/__init__.py app/models/ai_confidence_decision.py \
  app/routes/ai_proxy_ask_and_run.py app/routes/ai_proxy_dashboard_generate.py \
  app/routes/ai_proxy_dashboard_suggest.py app/routes/ai_proxy_query.py \
  app/routes/ai_proxy_query_actions.py app/routes/ai_proxy_shared.py \
  app/routes/document_families_curation.py app/services/ai_confidence_audit.py \
  app/services/evidence_severity.py app/services/knowledge_graph/ \
  app/services/knowledge_graph_ai.py app/services/knowledge_graph_ai_context.py
```

## Deploy

`platform-api` only. One migration (`0092`), additive (new `ai_confidence_decisions` table,
no backfill needed — this sandbox has no live Postgres to run the migration against;
verified via `alembic heads` showing `0092` as the new head and via SQLite `create_all` in
the test suite, matching every prior phase's migration-verification depth).

```bash
docker compose build platform-api
docker compose exec platform-api alembic upgrade head
docker compose up -d platform-api platform-api-worker
```

## Verify live

- Trigger a Knowledge Graph rebuild for a project with the AI server unreachable or
  disabled, then load that project's graph and confirm `insightCards`/`tracePaths` are
  **not** empty (the deterministic structural cards) and the response carries
  `aiEnrichmentStatus: "unavailable"`.
- Open any insight card's evidence trace and confirm each hop names a
  `fromNodeId`/`toNodeId`/`relationshipType`, not just a flat node-id list.
- Ingest two different sources (e.g. a saved query and a reference document) that
  normalize to the same graph key but disagree on a shared property value; confirm the
  surviving node's properties include `evidence_conflicts` naming both values.
- Confirm a card grounded only in a company-tier reference document is **not** capped to
  `watch` severity, while one grounded only in a generic industry-tier reference document
  still is.
- Ask a project-scoped AI question containing a distinctive keyword (e.g. a specific KPI
  or supplier name) and confirm the generated dashboard/query's KG-grounded risks/KPIs
  favor items whose title/summary contain that keyword over unrelated higher-confidence
  ones.
- Call an AI dashboard/query-generation endpoint for a project with more risks/KPIs than
  `max_items` and confirm the KG context (or its logged/inspected form) carries
  `context_coverage` showing `available > selected` for the truncated bucket.
- Accept, then later change, an AI-suggested document family on a real asset and confirm
  `ai_confidence_decisions` gains one row per action, with the `changed` row's
  `ai_confidence_at_decision` equal to the *original* AI suggestion's confidence, not the
  value used for the change itself.

## Remaining work

**Section D is now fully closed** (all of #32/34–38/40 done). **All five sections (A, B, C,
D, E) of the 50-item Knowledge Graph validation review are now complete** — every P0 and
every P1 item has been validated against the real codebase and either fixed (scoped,
tested, documented) or explicitly recorded as deliberately deferred with the reasoning for
why. No items remain open.

## Report back

Confirm the seven live-verification steps above pass in a deployed environment. This closes
out the 50-item Knowledge Graph validation review in its entirety — every item across
Sections A–E has been validated, and every P0/P1 gap confirmed real has a scoped, tested
fix on `kg-validation-phase10-source-lineage`, with every deliberately-deferred piece of a
larger ask documented alongside its fix.

---

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01M7j8CDCHCdwHpw9FrRhLN5
